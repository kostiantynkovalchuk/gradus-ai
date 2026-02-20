from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import hmac
import hashlib
import time
import os
import logging
import httpx

from models import get_db
from models.maya_models import MayaUser, MayaSubscription

router = APIRouter(prefix="/api/payments", tags=["payments"])
logger = logging.getLogger(__name__)

PRICES = {
    'standard': 7,
    'premium': 10,
}


class CheckoutRequest(BaseModel):
    email: EmailStr
    tier: str


async def get_usd_to_uah_rate() -> float:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json",
                timeout=5.0
            )
            data = r.json()
            return float(data[0]['rate'])
    except Exception as e:
        logger.warning(f"NBU rate fetch failed: {e}, using fallback")
        return 41.5


def generate_wayforpay_signature(params: list, secret_key: str) -> str:
    string = ";".join(str(p) for p in params)
    return hmac.new(
        secret_key.encode('utf-8'),
        string.encode('utf-8'),
        hashlib.md5
    ).hexdigest()


@router.get("/uah-rate")
async def get_rate():
    rate = await get_usd_to_uah_rate()
    return {"rate": rate}


@router.post("/create-checkout")
async def create_checkout(checkout: CheckoutRequest, db: Session = Depends(get_db)):
    merchant_login = os.getenv("WAYFORPAY_MERCHANT_LOGIN")
    secret_key = os.getenv("WAYFORPAY_MERCHANT_SECRET")

    if not merchant_login or not secret_key:
        raise HTTPException(503, "Платіжна система тимчасово недоступна")

    if checkout.tier not in ('standard', 'premium'):
        raise HTTPException(400, "Invalid tier")

    user = db.query(MayaUser).filter(MayaUser.email == checkout.email).first()
    if not user:
        raise HTTPException(404, "Користувач не зареєстрований")

    order_reference = f"gradus_{checkout.email.replace('@', '_')}_{int(time.time())}"
    order_date = int(time.time())

    uah_rate = await get_usd_to_uah_rate()
    usd_price = PRICES[checkout.tier]
    amount = round(usd_price * uah_rate, 2)

    product_name = (
        "Підписка Gradus Media Standard"
        if checkout.tier == "standard"
        else "Підписка Gradus Media Premium"
    )

    signature_params = [
        merchant_login,
        "gradusmedia.org",
        order_reference,
        order_date,
        amount,
        "UAH",
        product_name,
        1,
        amount
    ]
    signature = generate_wayforpay_signature(signature_params, secret_key)

    try:
        sub = MayaSubscription(
            email=checkout.email,
            tier=checkout.tier,
            billing_cycle="monthly",
            amount=amount,
            currency="UAH",
            wayforpay_order_id=order_reference,
            payment_status='pending',
        )
        db.add(sub)
        db.commit()
        logger.info(f"WayForPay checkout created: {order_reference} for {checkout.email} ({amount} UAH)")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save subscription: {e}")
        raise HTTPException(500, "Помилка створення платежу")

    return {
        "merchantAccount": merchant_login,
        "merchantDomainName": "gradusmedia.org",
        "orderReference": order_reference,
        "orderDate": order_date,
        "amount": amount,
        "currency": "UAH",
        "productName": product_name,
        "productPrice": amount,
        "productCount": 1,
        "merchantSignature": signature,
        "language": "UA",
        "usdPrice": usd_price,
        "uahRate": uah_rate
    }


@router.post("/webhook")
async def wayforpay_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        secret_key = os.getenv("WAYFORPAY_MERCHANT_SECRET")

        if not secret_key:
            logger.error("WAYFORPAY_MERCHANT_SECRET not configured")
            raise HTTPException(500, "Payment system not configured")

        sig_params = [
            data.get('merchantAccount', ''),
            data.get('orderReference', ''),
            data.get('amount', ''),
            data.get('currency', ''),
            data.get('authCode', ''),
            data.get('cardPan', ''),
            data.get('transactionStatus', ''),
            data.get('reasonCode', '')
        ]
        expected = generate_wayforpay_signature(sig_params, secret_key)
        if data.get('merchantSignature') != expected:
            logger.error("Invalid WayForPay signature")
            raise HTTPException(401, "Invalid signature")

        order_id = data.get('orderReference')
        status = data.get('transactionStatus')

        logger.info(f"WayForPay webhook: {order_id}, status: {status}")

        sub = db.query(MayaSubscription).filter(
            MayaSubscription.wayforpay_order_id == order_id
        ).first()

        if not sub:
            logger.error(f"Subscription not found: {order_id}")
            return {"status": "error", "message": "Subscription not found"}

        if status == 'Approved':
            expires_at = datetime.now() + timedelta(days=30)

            sub.payment_status = 'success'
            sub.started_at = datetime.utcnow()
            sub.expires_at = expires_at
            sub.payment_data = data
            sub.updated_at = datetime.utcnow()

            user = db.query(MayaUser).filter(MayaUser.email == sub.email).first()
            if user:
                user.subscription_tier = sub.tier
                user.subscription_status = 'active'
                user.subscription_started_at = datetime.utcnow()
                user.subscription_expires_at = expires_at
                user.wayforpay_order_id = order_id
                user.updated_at = datetime.utcnow()

            db.commit()
            logger.info(f"Subscription activated: {sub.email} -> {sub.tier}")

        elif status in ('Declined', 'Expired', 'RefundedFull'):
            sub.payment_status = 'failed'
            sub.payment_data = data
            sub.updated_at = datetime.utcnow()
            db.commit()
            logger.error(f"Payment failed: {order_id}, status: {status}")

        confirm_time = int(time.time())
        confirm_params = [order_id, 'accept', confirm_time]
        confirm_sig = generate_wayforpay_signature(confirm_params, secret_key)

        return {
            "orderReference": order_id,
            "status": "accept",
            "time": confirm_time,
            "signature": confirm_sig
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}
