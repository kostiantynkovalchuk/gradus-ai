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

from database import get_db

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
