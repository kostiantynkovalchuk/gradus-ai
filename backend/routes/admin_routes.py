"""
Admin Dashboard Routes for GradusMedia
Protected by X-Admin-Key header or session cookie
"""

from fastapi import APIRouter, HTTPException, Request, Response, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text
from datetime import datetime
import secrets
import logging
import os

from models import get_db

router = APIRouter(tags=["Admin"])
logger = logging.getLogger(__name__)

ADMIN_PASSWORD = "GradusAdmin_2026"


def _get_db():
    import models
    if models.SessionLocal is None:
        models.init_db()
    return models.SessionLocal()


def verify_admin_header(request: Request):
    key = request.headers.get("X-Admin-Key", "")
    cookie = request.cookies.get("admin_session", "")
    if key == ADMIN_PASSWORD or cookie == ADMIN_PASSWORD:
        return True
    raise HTTPException(status_code=403, detail="Access denied")


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    password = request.query_params.get("password", "")
    cookie = request.cookies.get("admin_session", "")

    if password == ADMIN_PASSWORD or cookie == ADMIN_PASSWORD:
        template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'admin_dashboard.html')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            response = HTMLResponse(content=html_content)
            if password == ADMIN_PASSWORD:
                response.set_cookie("admin_session", ADMIN_PASSWORD, httponly=True, max_age=86400)
            return response
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="Dashboard template not found")

    login_html = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Admin Login</title>
    <style>
    body{background:#0f172a;color:#e2e8f0;font-family:Inter,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
    .login{background:#1e293b;padding:2.5rem;border-radius:12px;width:360px;box-shadow:0 4px 30px rgba(0,0,0,.3)}
    h2{margin:0 0 1.5rem;text-align:center;color:#38bdf8}
    input{width:100%;padding:.75rem;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#e2e8f0;margin-bottom:1rem;box-sizing:border-box;font-size:1rem}
    button{width:100%;padding:.75rem;border:none;border-radius:8px;background:#38bdf8;color:#0f172a;font-weight:600;cursor:pointer;font-size:1rem}
    button:hover{background:#0ea5e9}
    .err{color:#f87171;text-align:center;font-size:.9rem;margin-top:.5rem;display:none}
    </style></head><body>
    <div class="login"><h2>GradusMedia Admin</h2>
    <form method="GET" action="/admin">
    <input type="password" name="password" placeholder="Enter admin password" autofocus>
    <button type="submit">Login</button>
    </form></div></body></html>"""
    return HTMLResponse(content=login_html)


@router.get("/api/admin/analytics/overview")
async def analytics_overview(request: Request):
    verify_admin_header(request)
    db = _get_db()
    try:
        users = db.execute(text("SELECT COUNT(*) FROM maya_users")).scalar() or 0
        subs = db.execute(text(
            "SELECT COUNT(*) FROM maya_users WHERE subscription_tier IN ('standard','premium') AND subscription_status='active'"
        )).scalar() or 0
        total_q = db.execute(text("SELECT COUNT(*) FROM maya_query_log")).scalar() or 0
        today_q = db.execute(text(
            "SELECT COUNT(*) FROM maya_query_log WHERE created_at::date = CURRENT_DATE"
        )).scalar() or 0
        week_q = db.execute(text(
            "SELECT COUNT(*) FROM maya_query_log WHERE created_at >= NOW() - INTERVAL '7 days'"
        )).scalar() or 0
        month_q = db.execute(text(
            "SELECT COUNT(*) FROM maya_query_log WHERE created_at >= NOW() - INTERVAL '30 days'"
        )).scalar() or 0
        avg_ms = db.execute(text(
            "SELECT COALESCE(AVG(response_time_ms)::INTEGER, 0) FROM maya_query_log"
        )).scalar() or 0

        tier_counts = db.execute(text(
            "SELECT COALESCE(user_tier, 'free'), COUNT(*) FROM maya_query_log GROUP BY COALESCE(user_tier, 'free')"
        ))
        questions_by_tier = {"free": 0, "standard": 0, "premium": 0}
        for r in tier_counts:
            t = r[0] if r[0] in questions_by_tier else 'free'
            questions_by_tier[t] += r[1]

        today_tier = db.execute(text(
            "SELECT COALESCE(user_tier, 'free'), COUNT(*) FROM maya_query_log WHERE created_at::date = CURRENT_DATE GROUP BY COALESCE(user_tier, 'free')"
        ))
        questions_today_by_tier = {"free": 0, "standard": 0, "premium": 0}
        for r in today_tier:
            t = r[0] if r[0] in questions_today_by_tier else 'free'
            questions_today_by_tier[t] += r[1]

        avg_tier = db.execute(text(
            "SELECT COALESCE(user_tier, 'free'), COALESCE(AVG(response_time_ms)::INTEGER, 0) FROM maya_query_log GROUP BY COALESCE(user_tier, 'free')"
        ))
        avg_response_time_by_tier = {"free": 0, "standard": 0, "premium": 0}
        for r in avg_tier:
            t = r[0] if r[0] in avg_response_time_by_tier else 'free'
            avg_response_time_by_tier[t] = r[1]

        preset_total = db.execute(text("SELECT COUNT(*) FROM alex_preset_answers WHERE is_active = TRUE")).scalar() or 0
        preset_used = db.execute(text(
            "SELECT SUM(usage_count) FROM alex_preset_answers WHERE is_active = TRUE"
        )).scalar() or 0
        preset_hit_pct = round((preset_used / total_q * 100) if total_q > 0 and preset_used else 0, 1)

        preset_patterns_list = db.execute(text(
            "SELECT question_pattern FROM alex_preset_answers WHERE is_active = TRUE"
        ))
        p_patterns = [r[0].lower() for r in preset_patterns_list]
        preset_hit_rate_by_tier = {}
        if p_patterns:
            from fuzzywuzzy import fuzz
            tier_logs = db.execute(text("""
                SELECT query_text, COALESCE(user_tier, 'free')
                FROM maya_query_log
                WHERE created_at >= NOW() - INTERVAL '30 days'
            """))
            tier_hits = {"free": 0, "standard": 0, "premium": 0}
            for r in tier_logs:
                qt = r[0].lower() if r[0] else ''
                ut = r[1] if r[1] in tier_hits else 'free'
                if any(fuzz.ratio(qt, p) >= 85 for p in p_patterns):
                    tier_hits[ut] += 1
            for t in ["free", "standard", "premium"]:
                tier_total = questions_by_tier.get(t, 0)
                preset_hit_rate_by_tier[t] = round((tier_hits[t] / tier_total * 100) if tier_total > 0 else 0, 1)
        else:
            preset_hit_rate_by_tier = {"free": 0, "standard": 0, "premium": 0}

        top_q = db.execute(text("""
            SELECT query_text, COUNT(*) as cnt 
            FROM maya_query_log 
            GROUP BY query_text 
            ORDER BY cnt DESC LIMIT 10
        """))
        top_questions = [{"text": r[0][:80], "count": r[1]} for r in top_q]

        top_by_tier = {}
        for t in ["free", "standard", "premium"]:
            rows = db.execute(text("""
                SELECT query_text, COUNT(*) as cnt 
                FROM maya_query_log 
                WHERE COALESCE(user_tier, 'free') = :tier
                GROUP BY query_text 
                ORDER BY cnt DESC LIMIT 10
            """), {"tier": t})
            top_by_tier[t] = [{"text": r[0][:80], "count": r[1]} for r in rows]

        daily = db.execute(text("""
            SELECT created_at::date as d, 
                   COUNT(*) FILTER (WHERE COALESCE(user_tier, 'free') = 'free') as free_cnt,
                   COUNT(*) FILTER (WHERE user_tier = 'standard') as standard_cnt,
                   COUNT(*) FILTER (WHERE user_tier = 'premium') as premium_cnt
            FROM maya_query_log 
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY d ORDER BY d
        """))
        questions_per_day = [{"date": str(r[0]), "free": r[1], "standard": r[2], "premium": r[3]} for r in daily]

        roles_rows = db.execute(text("""
            SELECT COALESCE(NULLIF(TRIM(position), ''), 'Unknown') as role, COUNT(*) as cnt
            FROM maya_users
            GROUP BY role ORDER BY cnt DESC
        """))
        roles_breakdown = [{"role": r[0], "count": r[1]} for r in roles_rows]

        rtm_rows = db.execute(text("""
            SELECT COALESCE(NULLIF(TRIM(position), ''), 'Unknown') as role,
                   COALESCE(subscription_tier, 'free') as tier, COUNT(*) as cnt
            FROM maya_users
            GROUP BY role, tier ORDER BY role, tier
        """))
        role_tier_map = {}
        for r in rtm_rows:
            role = r[0]
            if role not in role_tier_map:
                role_tier_map[role] = {"role": role, "free": 0, "standard": 0, "premium": 0, "total": 0}
            tier = r[1] if r[1] in ("free", "standard", "premium") else "free"
            role_tier_map[role][tier] += r[2]
            role_tier_map[role]["total"] += r[2]
        role_tier_matrix = sorted(role_tier_map.values(), key=lambda x: x["total"], reverse=True)

        return {
            "total_users": users,
            "active_subscriptions": subs,
            "total_questions": total_q,
            "questions_today": today_q,
            "questions_this_week": week_q,
            "questions_this_month": month_q,
            "questions_by_tier": questions_by_tier,
            "questions_today_by_tier": questions_today_by_tier,
            "preset_hit_rate_pct": preset_hit_pct,
            "preset_hit_rate_by_tier": preset_hit_rate_by_tier,
            "avg_response_time_ms": avg_ms,
            "avg_response_time_by_tier": avg_response_time_by_tier,
            "top_questions": top_questions,
            "top_questions_by_tier": top_by_tier,
            "questions_per_day": questions_per_day,
            "roles_breakdown": roles_breakdown,
            "role_tier_matrix": role_tier_matrix,
        }
    finally:
        db.close()


@router.get("/api/admin/users")
async def list_users(
    request: Request,
    tier: str = Query(None),
    position: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    verify_admin_header(request)
    db = _get_db()
    try:
        where = "WHERE 1=1"
        params = {"offset": (page - 1) * limit, "limit": limit}
        if tier:
            where += " AND subscription_tier = :tier"
            params["tier"] = tier
        if position:
            where += " AND LOWER(COALESCE(position, '')) = LOWER(:position)"
            params["position"] = position

        total = db.execute(text(f"SELECT COUNT(*) FROM maya_users {where}"), params).scalar() or 0

        rows = db.execute(text(f"""
            SELECT email, name, position, subscription_tier, subscription_status,
                   subscription_expires_at, questions_today, questions_limit,
                   registered_at, updated_at,
                   (SELECT COUNT(*) FROM maya_query_log WHERE email = maya_users.email) as total_questions
            FROM maya_users {where}
            ORDER BY registered_at DESC
            OFFSET :offset LIMIT :limit
        """), params)

        users = []
        for r in rows:
            users.append({
                "email": r[0], "name": r[1], "position": r[2],
                "tier": r[3], "status": r[4],
                "expires_at": str(r[5]) if r[5] else None,
                "questions_today": r[6] or 0,
                "questions_limit": r[7] or 5,
                "registered_at": str(r[8]) if r[8] else None,
                "last_active": str(r[9]) if r[9] else None,
                "total_questions": r[10] or 0,
            })

        pos_rows = db.execute(text(
            "SELECT DISTINCT position FROM maya_users WHERE position IS NOT NULL AND TRIM(position) != '' ORDER BY position"
        ))
        distinct_positions = [r[0] for r in pos_rows]

        return {"total": total, "page": page, "limit": limit, "users": users, "positions": distinct_positions}
    finally:
        db.close()


@router.get("/api/admin/subscriptions")
async def list_subscriptions(
    request: Request,
    status: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    verify_admin_header(request)
    db = _get_db()
    try:
        where = "WHERE 1=1"
        params = {"offset": (page - 1) * limit, "limit": limit}
        if status:
            where += " AND payment_status = :status"
            params["status"] = status

        total = db.execute(text(f"SELECT COUNT(*) FROM maya_subscriptions {where}"), params).scalar() or 0

        mrr = db.execute(text(
            "SELECT COALESCE(SUM(amount), 0) FROM maya_subscriptions WHERE payment_status='success' AND expires_at > NOW()"
        )).scalar() or 0

        failed = db.execute(text(
            "SELECT COUNT(*) FROM maya_subscriptions WHERE payment_status='failed' AND created_at >= DATE_TRUNC('month', NOW())"
        )).scalar() or 0

        churned = db.execute(text(
            "SELECT COUNT(*) FROM maya_subscriptions WHERE expires_at < NOW() AND expires_at >= DATE_TRUNC('month', NOW())"
        )).scalar() or 0

        rows = db.execute(text(f"""
            SELECT email, tier, billing_cycle, amount, currency,
                   payment_status, wayforpay_order_id, started_at, expires_at, created_at
            FROM maya_subscriptions {where}
            ORDER BY created_at DESC
            OFFSET :offset LIMIT :limit
        """), params)

        subs = []
        for r in rows:
            subs.append({
                "email": r[0], "tier": r[1], "billing_cycle": r[2],
                "amount": float(r[3]) if r[3] else 0, "currency": r[4],
                "payment_status": r[5], "order_id": r[6],
                "started_at": str(r[7]) if r[7] else None,
                "expires_at": str(r[8]) if r[8] else None,
                "created_at": str(r[9]) if r[9] else None,
            })

        return {
            "total": total, "page": page, "limit": limit,
            "mrr_usd": float(mrr), "failed_this_month": failed,
            "churned_this_month": churned, "subscriptions": subs
        }
    finally:
        db.close()


@router.get("/api/admin/alex/presets")
async def list_presets(request: Request):
    verify_admin_header(request)
    db = _get_db()
    try:
        rows = db.execute(text("""
            SELECT id, question_pattern, answer_text, category, priority,
                   usage_count, is_active, last_used_at, created_at
            FROM alex_preset_answers ORDER BY priority DESC, usage_count DESC
        """))
        presets = []
        for r in rows:
            presets.append({
                "id": r[0], "question_pattern": r[1],
                "answer_text": r[2][:200] + "..." if r[2] and len(r[2]) > 200 else r[2],
                "category": r[3], "priority": r[4],
                "usage_count": r[5] or 0, "is_active": r[6],
                "last_used_at": str(r[7]) if r[7] else None,
                "created_at": str(r[8]) if r[8] else None,
            })
        return {"presets": presets}
    finally:
        db.close()


@router.post("/api/admin/alex/presets")
async def create_preset(request: Request):
    verify_admin_header(request)
    body = await request.json()
    db = _get_db()
    try:
        result = db.execute(text("""
            INSERT INTO alex_preset_answers (question_pattern, answer_text, category, priority)
            VALUES (:q, :a, :cat, :pri) RETURNING id
        """), {
            'q': body['question_pattern'], 'a': body['answer_text'],
            'cat': body.get('category', 'general'), 'pri': body.get('priority', 5)
        })
        db.commit()
        new_id = result.scalar()

        from services.preset_service import preset_service
        preset_service.reload_presets()

        return {"id": new_id, "status": "created"}
    finally:
        db.close()


@router.put("/api/admin/alex/presets/{preset_id}")
async def update_preset(preset_id: int, request: Request):
    verify_admin_header(request)
    body = await request.json()
    db = _get_db()
    try:
        sets = []
        params = {"id": preset_id}
        for field in ['question_pattern', 'answer_text', 'category', 'priority', 'is_active']:
            if field in body:
                sets.append(f"{field} = :{field}")
                params[field] = body[field]
        if not sets:
            raise HTTPException(status_code=400, detail="No fields to update")
        sets.append("updated_at = NOW()")
        db.execute(text(f"UPDATE alex_preset_answers SET {', '.join(sets)} WHERE id = :id"), params)
        db.commit()

        from services.preset_service import preset_service
        preset_service.reload_presets()

        return {"status": "updated"}
    finally:
        db.close()


@router.get("/api/admin/alex/preset-candidates")
async def list_candidates(request: Request):
    verify_admin_header(request)
    db = _get_db()
    try:
        rows = db.execute(text("""
            SELECT id, question_text, frequency, avg_response_time_ms,
                   first_seen_at, last_seen_at, status, sample_claude_answer,
                   COALESCE(dominant_tier, 'free') as dominant_tier
            FROM alex_preset_candidates
            ORDER BY 
                CASE WHEN status = 'candidate' THEN 0 WHEN status = 'promoted' THEN 1 ELSE 2 END,
                frequency DESC
        """))
        candidates = []
        for r in rows:
            candidates.append({
                "id": r[0], "question_text": r[1], "frequency": r[2],
                "avg_response_time_ms": r[3],
                "first_seen_at": str(r[4]) if r[4] else None,
                "last_seen_at": str(r[5]) if r[5] else None,
                "status": r[6],
                "sample_claude_answer": r[7],
                "dominant_tier": r[8],
            })
        return {"candidates": candidates}
    finally:
        db.close()


@router.post("/api/admin/alex/preset-candidates/{candidate_id}/generate-answer")
async def generate_candidate_answer(candidate_id: int, request: Request):
    verify_admin_header(request)
    db = _get_db()
    try:
        row = db.execute(text(
            "SELECT question_text FROM alex_preset_candidates WHERE id = :id"
        ), {"id": candidate_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")

        question = row[0]

        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        from services.avatar_personalities import get_avatar_personality
        system = get_avatar_personality("alex", is_first_message=False)
        system += "\n\nВАЖЛИВО: Це відповідь для preset-системи. Будь конкретним, з цифрами та ROI."
        system += "\nЗгадай продукти AVTD: GREENDAY, HELSINKI, UKRAINKA (горілка), DOVBUSH, ADJARI (бренді), VILLA UA, KRISTI VALLEY (вино), FUNJU (соджу)."

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": question}]
        )
        answer = response.content[0].text

        db.execute(text(
            "UPDATE alex_preset_candidates SET sample_claude_answer = :a WHERE id = :id"
        ), {"a": answer, "id": candidate_id})
        db.commit()

        return {"answer": answer}
    finally:
        db.close()


@router.post("/api/admin/alex/preset-candidates/{candidate_id}/promote")
async def promote_candidate(candidate_id: int, request: Request):
    verify_admin_header(request)
    body = await request.json()
    db = _get_db()
    try:
        row = db.execute(text(
            "SELECT question_text, sample_claude_answer FROM alex_preset_candidates WHERE id = :id AND status = 'candidate'"
        ), {"id": candidate_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found or already processed")

        answer_text = body.get("answer_text") or row[1]
        if not answer_text:
            raise HTTPException(status_code=400, detail="Answer text required")

        result = db.execute(text("""
            INSERT INTO alex_preset_answers (question_pattern, answer_text, category, priority)
            VALUES (:q, :a, :cat, :pri) RETURNING id
        """), {
            'q': row[0], 'a': answer_text,
            'cat': body.get('category', 'general'),
            'pri': body.get('priority', 5)
        })
        preset_id = result.scalar()

        db.execute(text("""
            UPDATE alex_preset_candidates SET status = 'promoted', promoted_preset_id = :pid WHERE id = :id
        """), {"pid": preset_id, "id": candidate_id})
        db.commit()

        from services.preset_service import preset_service
        preset_service.reload_presets()

        return {"status": "promoted", "preset_id": preset_id}
    finally:
        db.close()


@router.post("/api/admin/alex/preset-candidates/{candidate_id}/dismiss")
async def dismiss_candidate(candidate_id: int, request: Request):
    verify_admin_header(request)
    db = _get_db()
    try:
        db.execute(text(
            "UPDATE alex_preset_candidates SET status = 'dismissed' WHERE id = :id"
        ), {"id": candidate_id})
        db.commit()
        return {"status": "dismissed"}
    finally:
        db.close()
