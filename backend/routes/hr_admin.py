"""
HR Admin Dashboard API
Protected by HTTP Basic Auth
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text
from datetime import date, timedelta
import secrets
import logging
from typing import Optional

from models import get_db

router = APIRouter(prefix="/hr", tags=["HR Admin"])
security = HTTPBasic()
logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Maya_2026"


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify HTTP Basic Auth credentials"""
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Render admin dashboard HTML"""
    import os
    template_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'hr_admin.html')
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Dashboard template not found")


@router.get("/api/overview")
async def get_overview(
    days: int = 7,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Get overview statistics"""
    db_session = next(get_db())
    
    try:
        result = db_session.execute(text("""
            SELECT
                COUNT(*) as total_queries,
                COUNT(*) FILTER (WHERE preset_matched = TRUE) as preset_hits,
                COUNT(*) FILTER (WHERE rag_used = TRUE) as rag_queries,
                COUNT(DISTINCT user_id) as unique_users,
                COALESCE(AVG(response_time_ms)::INTEGER, 0) as avg_response_time,
                (COUNT(*) FILTER (WHERE satisfied = TRUE)::DECIMAL / 
                 NULLIF(COUNT(*) FILTER (WHERE satisfied IS NOT NULL), 0) * 100)::DECIMAL(5,2) as satisfaction_rate
            FROM hr_query_log
            WHERE created_at >= NOW() - make_interval(days => :days)
        """), {'days': days})
        
        stats = result.fetchone()
        
        total = stats[0] or 0
        preset_rate = (stats[1] / total * 100) if total > 0 else 0
        rag_rate = (stats[2] / total * 100) if total > 0 else 0
    
        return {
            'period': {
                'days': days
            },
            'stats': {
                'total_queries': total,
                'preset_hits': stats[1] or 0,
                'preset_coverage': round(preset_rate, 1),
                'rag_queries': stats[2] or 0,
                'rag_usage': round(rag_rate, 1),
                'unique_users': stats[3] or 0,
                'avg_response_time_ms': stats[4] or 0,
                'satisfaction_rate': float(stats[5]) if stats[5] else 0.0
            }
        }
    except Exception as e:
        logger.error(f"Overview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/top-queries")
async def get_top_queries(
    days: int = 7,
    limit: int = 20,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Get most popular queries"""
    db_session = next(get_db())
    
    try:
        result = db_session.execute(text("""
            SELECT 
                query_normalized,
                COUNT(*) as frequency,
                COUNT(*) FILTER (WHERE preset_matched = TRUE) as preset_hits,
                COUNT(*) FILTER (WHERE satisfied = TRUE) as helpful_count,
                COUNT(*) FILTER (WHERE satisfied = FALSE) as not_helpful_count,
                COUNT(*) FILTER (WHERE satisfied IS NOT NULL) as feedback_count,
                COALESCE(AVG(response_time_ms)::INTEGER, 0) as avg_response_time
            FROM hr_query_log
            WHERE created_at >= NOW() - make_interval(days => :days)
            GROUP BY query_normalized
            ORDER BY frequency DESC
            LIMIT :limit
        """), {'days': days, 'limit': limit})
        
        queries = result.fetchall()
    
        return {
            'queries': [
                {
                    'query': q[0],
                    'frequency': q[1],
                    'preset_hits': q[2],
                    'helpful_count': q[3],
                    'not_helpful_count': q[4],
                    'feedback_count': q[5],
                    'satisfaction_rate': round((q[3] / q[5] * 100) if q[5] > 0 else 0, 1),
                    'avg_response_time_ms': q[6],
                    'has_feedback': q[5] > 0
                }
                for q in queries
            ]
        }
    except Exception as e:
        logger.error(f"Top queries error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/satisfaction-breakdown")
async def get_satisfaction_breakdown(
    days: int = 7,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Get satisfaction breakdown"""
    db_session = next(get_db())
    
    try:
        result = db_session.execute(text("""
            SELECT 
                query_normalized,
                COUNT(*) as frequency,
                COUNT(*) FILTER (WHERE satisfied = FALSE) as not_helpful
            FROM hr_query_log
            WHERE 
                created_at >= NOW() - make_interval(days => :days)
                AND satisfied = FALSE
            GROUP BY query_normalized
            ORDER BY frequency DESC
            LIMIT 10
        """), {'days': days})
        
        dissatisfied = result.fetchall()
        
        result2 = db_session.execute(text("""
            SELECT 
                query_normalized,
                COUNT(*) as frequency,
                COUNT(*) FILTER (WHERE satisfied = TRUE) as helpful
            FROM hr_query_log
            WHERE 
                created_at >= NOW() - make_interval(days => :days)
                AND satisfied = TRUE
            GROUP BY query_normalized
            ORDER BY frequency DESC
            LIMIT 10
        """), {'days': days})
        
        satisfied = result2.fetchall()
    
        return {
            'not_helpful': [
                {
                    'query': q[0],
                    'frequency': q[1],
                    'not_helpful_count': q[2]
                }
                for q in dissatisfied
            ],
            'helpful': [
                {
                    'query': q[0],
                    'frequency': q[1],
                    'helpful_count': q[2]
                }
                for q in satisfied
            ]
        }
    except Exception as e:
        logger.error(f"Satisfaction breakdown error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/preset-candidates")
async def get_preset_candidates(
    min_frequency: int = 3,
    days: int = 30,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Find queries that should become presets"""
    db_session = next(get_db())
    
    try:
        result = db_session.execute(text("""
            SELECT 
                query_normalized,
                COUNT(*) as frequency,
                COALESCE(AVG(response_time_ms)::INTEGER, 0) as avg_time,
                COUNT(*) FILTER (WHERE satisfied = FALSE) as dissatisfied_count,
                COUNT(*) FILTER (WHERE satisfied IS NOT NULL) as feedback_count
            FROM hr_query_log
            WHERE 
                preset_matched = FALSE
                AND created_at >= NOW() - make_interval(days => :days)
            GROUP BY query_normalized
            HAVING COUNT(*) >= :min_freq
            ORDER BY frequency DESC, dissatisfied_count DESC
            LIMIT 20
        """), {'days': days, 'min_freq': min_frequency})
        
        candidates = result.fetchall()
    
        return {
            'candidates': [
                {
                    'query': c[0],
                    'frequency': c[1],
                    'avg_response_time_ms': c[2],
                    'dissatisfied_count': c[3],
                    'feedback_count': c[4],
                    'priority': 'high' if c[1] >= 10 else ('medium' if c[1] >= 5 else 'low'),
                    'should_add': c[1] >= 5 or c[3] >= 2
                }
                for c in candidates
            ]
        }
    except Exception as e:
        logger.error(f"Preset candidates error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/recent-queries")
async def get_recent_queries(
    limit: int = 50,
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Get recent queries for review"""
    db_session = next(get_db())
    
    try:
        result = db_session.execute(text("""
            SELECT 
                id,
                user_name,
                query,
                preset_matched,
                rag_used,
                response_time_ms,
                satisfied,
                created_at
            FROM hr_query_log
            ORDER BY created_at DESC
            LIMIT :limit
        """), {'limit': limit})
        
        queries = result.fetchall()
    
        return {
            'queries': [
                {
                    'id': q[0],
                    'user': q[1] or 'Anonymous',
                    'query': q[2],
                    'preset_hit': q[3],
                    'rag_used': q[4],
                    'response_ms': q[5] or 0,
                    'satisfied': q[6],
                    'timestamp': q[7].isoformat() if q[7] else None
                }
                for q in queries
            ]
        }
    except Exception as e:
        logger.error(f"Recent queries error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/hunt-analytics")
async def get_hunt_analytics(
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    db_session = next(get_db())

    try:
        stats_result = db_session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM hunt_vacancies) as total_vacancies,
                (SELECT COUNT(*) FROM hunt_vacancies WHERE status = 'filled') as total_filled,
                (SELECT COUNT(*) FROM hunt_candidates) as total_candidates,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision = 'hired') as total_hires,
                (SELECT COUNT(*) FROM hunt_postings WHERE status = 'posted') as total_posted,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision = 'approved') as approved,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision = 'rejected') as rejected,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision = 'saved') as saved,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision = 'pending') as pending,
                (SELECT COUNT(*) FROM hunt_candidates WHERE created_at >= CURRENT_DATE) as candidates_today,
                (SELECT COUNT(*) FROM hunt_candidates WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') as candidates_week,
                (SELECT COUNT(DISTINCT channel) FROM hunt_postings WHERE status = 'posted') as total_channels,
                (SELECT COUNT(*) FROM hunt_candidates WHERE hr_decision NOT IN ('pending')) as reviewed
        """))
        s = stats_result.fetchone()
        total_vacancies = s[0] or 0
        total_filled = s[1] or 0
        total_candidates = s[2] or 0
        total_hires = s[3] or 0
        total_posted = s[4] or 0
        approved = s[5] or 0
        rejected = s[6] or 0
        saved = s[7] or 0
        pending = s[8] or 0
        candidates_today = s[9] or 0
        candidates_week = s[10] or 0
        total_channels = s[11] or 0
        reviewed = s[12] or 0

        shown = approved + rejected + saved + total_hires
        acceptance_rate = round((approved + total_hires) / shown * 100, 1) if shown > 0 else 0
        avg_per_vacancy = round(total_candidates / total_vacancies, 1) if total_vacancies > 0 else 0
        estimated_reach = total_posted * 5000
        cost_saved_usd = total_hires * 385
        hours_saved = round(total_vacancies * 2.67, 1)
        cost_per_hire_maya = round(total_vacancies * 0.15 / max(total_hires, 1), 2)

        kpi = {
            "total_vacancies": total_vacancies,
            "total_filled": total_filled,
            "total_hires": total_hires,
            "total_candidates_processed": total_candidates,
            "candidates_today": candidates_today,
            "candidates_this_week": candidates_week,
            "acceptance_rate": acceptance_rate,
            "avg_candidates_per_vacancy": avg_per_vacancy,
            "total_channels_posted": total_channels,
            "estimated_reach": estimated_reach,
            "cost_saved_usd": cost_saved_usd,
            "hours_saved": hours_saved,
            "cost_per_hire_maya": cost_per_hire_maya,
            "traditional_cost_per_hire": 400,
            "decisions": {
                "approved": approved,
                "rejected": rejected,
                "saved": saved,
                "pending": pending,
                "hired": total_hires,
            }
        }

        hire_funnel = {
            "found": total_candidates,
            "reviewed": reviewed,
            "approved": approved,
            "saved": saved,
            "hired": total_hires,
        }

        source_result = db_session.execute(text("""
            SELECT
                c.source,
                COUNT(*) as candidates_found,
                COUNT(*) FILTER (WHERE c.hr_decision = 'approved') as approved,
                COUNT(*) FILTER (WHERE c.hr_decision = 'hired') as hired
            FROM hunt_candidates c
            GROUP BY c.source
            ORDER BY candidates_found DESC
        """))
        source_performance = []
        for r in source_result.fetchall():
            found = r[1] or 0
            appr = r[2] or 0
            hired = r[3] or 0
            rate = round(appr / found * 100, 1) if found > 0 else 0
            source_performance.append({
                "source": r[0] or "unknown",
                "candidates_found": found,
                "approved": appr,
                "hired": hired,
                "approval_rate": rate,
            })

        posting_result = db_session.execute(text("""
            SELECT
                channel,
                COUNT(*) as total_posted,
                MAX(posted_at) as last_posted
            FROM hunt_postings
            WHERE status = 'posted'
            GROUP BY channel
            ORDER BY total_posted DESC
        """))
        posting_performance = [
            {
                "channel": r[0],
                "total_posted": r[1],
                "last_posted": r[2].strftime("%Y-%m-%d %H:%M") if r[2] else None,
            }
            for r in posting_result.fetchall()
        ]

        salary_result = db_session.execute(text("""
            SELECT
                city,
                position,
                data_type,
                COALESCE(AVG(COALESCE(salary_median_usd, salary_median)), 0)::INTEGER as median_usd,
                COALESCE(AVG(salary_median_uah), 0)::INTEGER as median_uah,
                COUNT(*) as sample_size,
                STRING_AGG(DISTINCT source, ', ') as sources
            FROM hunt_salary_data
            WHERE city IS NOT NULL AND (salary_median IS NOT NULL OR salary_median_usd IS NOT NULL)
            GROUP BY city, position, data_type
            ORDER BY city, position
        """))
        salary_rows = salary_result.fetchall()

        city_map = {}
        for row in salary_rows:
            key = f"{row[0]}|{row[1]}"
            if key not in city_map:
                city_map[key] = {
                    "city": row[0],
                    "position": row[1],
                    "candidate_median": 0,
                    "employer_median": 0,
                    "candidate_median_uah": 0,
                    "employer_median_uah": 0,
                    "gap": 0,
                    "sample_size": 0,
                    "sources": [],
                }
            entry = city_map[key]
            if row[2] == "candidate":
                entry["candidate_median"] = row[3]
                entry["candidate_median_uah"] = row[4]
            else:
                entry["employer_median"] = row[3]
                entry["employer_median_uah"] = row[4]
            entry["sample_size"] += row[5]
            for src in (row[6] or "").split(", "):
                if src and src not in entry["sources"]:
                    entry["sources"].append(src)

        for entry in city_map.values():
            entry["gap"] = entry["candidate_median"] - entry["employer_median"]

        salary_by_city = list(city_map.values())

        skills_result = db_session.execute(text("""
            SELECT
                TRIM(skill) as skill,
                COUNT(*) as cnt,
                COALESCE(AVG(COALESCE(salary_median_usd, salary_median)), 0)::INTEGER as avg_salary_usd,
                COALESCE(AVG(salary_median_uah), 0)::INTEGER as avg_salary_uah
            FROM hunt_salary_data,
                 LATERAL unnest(string_to_array(skills, ',')) AS skill
            WHERE skills IS NOT NULL AND skills != ''
            GROUP BY TRIM(skill)
            ORDER BY cnt DESC
            LIMIT 10
        """))
        top_skills = [
            {"skill": r[0], "count": r[1], "avg_salary": r[2], "avg_salary_uah": r[3]}
            for r in skills_result.fetchall()
        ]

        trends_result = db_session.execute(text("""
            SELECT
                TO_CHAR(collected_at, 'YYYY-MM') as month,
                data_type,
                COALESCE(AVG(COALESCE(salary_median_usd, salary_median)), 0)::INTEGER as median_usd,
                COALESCE(AVG(salary_median_uah), 0)::INTEGER as median_uah
            FROM hunt_salary_data
            WHERE salary_median IS NOT NULL OR salary_median_usd IS NOT NULL
            GROUP BY TO_CHAR(collected_at, 'YYYY-MM'), data_type
            ORDER BY month
        """))
        trends_map = {}
        for row in trends_result.fetchall():
            if row[0] not in trends_map:
                trends_map[row[0]] = {
                    "month": row[0],
                    "candidate_median": 0, "employer_median": 0,
                    "candidate_median_uah": 0, "employer_median_uah": 0,
                }
            if row[1] == "candidate":
                trends_map[row[0]]["candidate_median"] = row[2]
                trends_map[row[0]]["candidate_median_uah"] = row[3]
            else:
                trends_map[row[0]]["employer_median"] = row[2]
                trends_map[row[0]]["employer_median_uah"] = row[3]
        salary_trends = list(trends_map.values())

        recent_result = db_session.execute(text("""
            SELECT
                v.id,
                v.position,
                v.city,
                v.status,
                (SELECT COUNT(*) FROM hunt_postings p WHERE p.vacancy_id = v.id AND p.status = 'posted') as channels_posted,
                (SELECT COUNT(*) FROM hunt_candidates c WHERE c.vacancy_id = v.id) as candidates_found,
                (SELECT COUNT(*) > 0 FROM hunt_candidates c WHERE c.vacancy_id = v.id AND c.hr_decision = 'hired') as has_hire,
                v.created_at
            FROM hunt_vacancies v
            ORDER BY v.created_at DESC
            LIMIT 10
        """))
        recent_vacancies = [
            {
                "id": r[0],
                "position": r[1] or "—",
                "city": r[2] or "—",
                "status": r[3] or "new",
                "channels_posted": r[4] or 0,
                "candidates_found": r[5] or 0,
                "hired": bool(r[6]),
                "created_at": r[7].strftime("%Y-%m-%d") if r[7] else None,
            }
            for r in recent_result.fetchall()
        ]

        source_count_result = db_session.execute(text("""
            SELECT COUNT(*) FROM hunt_sources WHERE is_active = TRUE
        """))
        active_sources = source_count_result.scalar() or 0

        return {
            "kpi": kpi,
            "hire_funnel": hire_funnel,
            "source_performance": source_performance,
            "posting_performance": posting_performance,
            "salary_by_city": salary_by_city,
            "top_skills": top_skills,
            "salary_trends": salary_trends,
            "recent_vacancies": recent_vacancies,
            "active_sources": active_sources,
        }

    except Exception as e:
        logger.error(f"Hunt analytics error: {e}", exc_info=True)
        return {
            "kpi": {
                "total_vacancies": 0, "total_filled": 0, "total_hires": 0,
                "total_candidates_processed": 0, "candidates_today": 0,
                "candidates_this_week": 0, "acceptance_rate": 0,
                "avg_candidates_per_vacancy": 0, "total_channels_posted": 0,
                "estimated_reach": 0, "cost_saved_usd": 0, "hours_saved": 0,
                "cost_per_hire_maya": 0, "traditional_cost_per_hire": 400,
                "decisions": {"approved": 0, "rejected": 0, "saved": 0, "pending": 0, "hired": 0},
            },
            "hire_funnel": {"found": 0, "reviewed": 0, "approved": 0, "saved": 0, "hired": 0},
            "source_performance": [],
            "posting_performance": [],
            "salary_by_city": [],
            "top_skills": [],
            "salary_trends": [],
            "recent_vacancies": [],
            "active_sources": 0,
        }


@router.get("/api/system-info")
async def get_system_info(
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Get system information"""
    db_session = next(get_db())
    
    try:
        content_result = db_session.execute(text("SELECT COUNT(*) FROM hr_content"))
        content_count = content_result.scalar() or 0
        
        try:
            preset_result = db_session.execute(text(
                "SELECT COUNT(*) FROM hr_preset_answers WHERE is_active = TRUE"
            ))
            preset_count = preset_result.scalar() or 0
        except:
            preset_count = 6
        
        try:
            embedding_result = db_session.execute(text("SELECT COUNT(*) FROM hr_embeddings"))
            embedding_count = embedding_result.scalar() or 0
        except:
            embedding_count = 0
    
        return {
            'content_items': content_count,
            'active_presets': preset_count,
            'embeddings': embedding_count,
            'status': 'operational'
        }
    except Exception as e:
        logger.error(f"System info error: {e}")
        return {
            'content_items': 0,
            'active_presets': 6,
            'embeddings': 0,
            'status': 'operational'
        }
