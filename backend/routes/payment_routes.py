from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import hashlib
import base64
import json
import os
import logging

from models import get_db
from models.maya_models import MayaUser, MayaSubscription

router = APIRouter(prefix="/api/payments", tags=["payments"])
logger = logging.getLogger(__name__)

LIQPAY_PUBLIC_KEY = os.getenv("LIQPAY_PUBLIC_KEY")
LIQPAY_PRIVATE_KEY = os.getenv("LIQPAY_PRIVATE_KEY")

PRICES = {
    'standard': {'monthly': 7.00, 'annual': 70.00},
    'premium': {'monthly': 10.00, 'annual': 100.00},
}


class CheckoutRequest(BaseModel):
    email: EmailStr
    tier: str
    billing_cycle: str


class CheckoutResponse(BaseModel):
    data: str
    signature: str
    liqpay_url: str


def generate_liqpay_signature(data: str) -> str:
    sign_string = LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY
    return base64.b64encode(hashlib.sha1(sign_string.encode()).digest()).decode()


@router.post("/create-checkout", response_model=CheckoutResponse)
async def create_checkout(checkout: CheckoutRequest, db: Session = Depends(get_db)):
    try:
        if checkout.tier not in ('standard', 'premium'):
            raise HTTPException(400, "Invalid tier")
        if checkout.billing_cycle not in ('monthly', 'annual'):
            raise HTTPException(400, "Invalid billing cycle")

        if not LIQPAY_PUBLIC_KEY or not LIQPAY_PRIVATE_KEY:
            raise HTTPException(503, "Платіжна система тимчасово недоступна")

        user = db.query(MayaUser).filter(MayaUser.email == checkout.email).first()
        if not user:
            raise HTTPException(404, "Користувач не зареєстрований")

        amount = PRICES[checkout.tier][checkout.billing_cycle]
        order_id = f"SUB-{checkout.email}-{int(datetime.now().timestamp())}"

        payment_data = {
            "version": 3,
            "public_key": LIQPAY_PUBLIC_KEY,
            "action": "subscribe",
            "amount": amount,
            "currency": "USD",
            "description": f"Gradus Media {checkout.tier.capitalize()} - {checkout.billing_cycle}",
            "order_id": order_id,
            "subscribe_date_start": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "subscribe_periodicity": "month" if checkout.billing_cycle == "monthly" else "year",
            "result_url": "https://gradusmedia.org/payment/success",
            "server_url": "https://gradus-ai.onrender.com/api/payments/webhook",
            "language": "uk",
        }

        data_encoded = base64.b64encode(json.dumps(payment_data).encode()).decode()
        signature = generate_liqpay_signature(data_encoded)

        sub = MayaSubscription(
            email=checkout.email,
            tier=checkout.tier,
            billing_cycle=checkout.billing_cycle,
            amount=amount,
            currency="USD",
            liqpay_order_id=order_id,
            payment_status='pending',
        )
        db.add(sub)
        db.commit()

        logger.info(f"Checkout created: {order_id} for {checkout.email}")
        return CheckoutResponse(data=data_encoded, signature=signature, liqpay_url="https://www.liqpay.ua/api/3/checkout")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Checkout error: {e}")
        raise HTTPException(500, "Помилка створення платежу")


@router.post("/webhook")
async def liqpay_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        form_data = await request.form()
        data = form_data.get('data')
        signature = form_data.get('signature')

        if not data or not signature:
            raise HTTPException(400, "Missing data or signature")

        if not LIQPAY_PRIVATE_KEY:
            logger.error("LIQPAY_PRIVATE_KEY not configured")
            raise HTTPException(500, "Payment system not configured")

        expected_signature = generate_liqpay_signature(data)
        if signature != expected_signature:
            logger.error("Invalid LiqPay signature")
            raise HTTPException(401, "Invalid signature")

        payment_info = json.loads(base64.b64decode(data))
        order_id = payment_info.get('order_id')
        status = payment_info.get('status')

        logger.info(f"LiqPay webhook: {order_id}, status: {status}")

        sub = db.query(MayaSubscription).filter(MayaSubscription.liqpay_order_id == order_id).first()
        if not sub:
            logger.error(f"Subscription not found: {order_id}")
            return {"status": "error", "message": "Subscription not found"}

        email = sub.email
        tier = sub.tier
        billing_cycle = sub.billing_cycle

        if status in ('subscribed', 'success'):
            expires_at = datetime.now() + timedelta(days=30 if billing_cycle == 'monthly' else 365)

            sub.payment_status = 'success'
            sub.started_at = datetime.utcnow()
            sub.expires_at = expires_at
            sub.payment_data = payment_info
            sub.updated_at = datetime.utcnow()

            user = db.query(MayaUser).filter(MayaUser.email == email).first()
            if user:
                user.subscription_tier = tier
                user.subscription_status = 'active'
                user.subscription_started_at = datetime.utcnow()
                user.subscription_expires_at = expires_at
                user.liqpay_order_id = order_id
                user.updated_at = datetime.utcnow()

            db.commit()
            logger.info(f"Subscription activated: {email} -> {tier}")

        elif status in ('failure', 'error'):
            sub.payment_status = 'failed'
            sub.payment_data = payment_info
            sub.updated_at = datetime.utcnow()
            db.commit()
            logger.error(f"Payment failed: {order_id}")

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}
