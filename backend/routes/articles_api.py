from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, defer
from sqlalchemy import desc, or_, func
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from models import get_db
from models.content import ContentQueue

router = APIRouter(prefix="/api/articles", tags=["Public Articles API"])

class ArticleResponse(BaseModel):
    id: int
    title: Optional[str]
    content: Optional[str]
    source: Optional[str]
    source_url: Optional[str]
    image_url: Optional[str]
    platforms: Optional[List[str]]
    published_at: Optional[datetime]
    language: Optional[str]
    
    class Config:
        from_attributes = True

class ArticlesListResponse(BaseModel):
    articles: List[ArticleResponse]
    total: int
    limit: int
    offset: int
    has_more: bool

@router.get("", response_model=ArticlesListResponse)
async def get_published_articles(
    limit: int = Query(default=20, le=100, ge=1),
    offset: int = Query(default=0, ge=0),
    platform: Optional[str] = Query(default=None, description="Filter by platform: facebook, linkedin"),
    db: Session = Depends(get_db)
):
    """
    Get published articles for gradusmedia.org
    Returns approved and posted content.
    Excludes binary image_data to prevent memory issues.
    """
    base_query = db.query(ContentQueue).filter(
        ContentQueue.status.in_(['approved', 'posted'])
    )
    
    if platform:
        from sqlalchemy import cast, String
        base_query = base_query.filter(cast(ContentQueue.platforms, String).like(f'%{platform}%'))
    
    total = base_query.count()
    
    articles = base_query.options(
        defer(ContentQueue.image_data),
        defer(ContentQueue.original_text)
    ).order_by(desc(ContentQueue.created_at)).offset(offset).limit(limit).all()
    
    result = []
    for article in articles:
        content_preview = None
        if article.translated_text:
            content_preview = article.translated_text[:500] + "..." if len(article.translated_text) > 500 else article.translated_text
        result.append(ArticleResponse(
            id=article.id,
            title=article.translated_title or article.source_title,
            content=content_preview,
            source=article.source,
            source_url=article.source_url,
            image_url=f"https://gradus-ai.onrender.com/api/images/serve/{article.id}",
            platforms=article.platforms,
            published_at=article.posted_at or article.reviewed_at or article.created_at,
            language=article.language
        ))
    
    return ArticlesListResponse(
        articles=result,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total
    )

@router.get("/search")
async def search_articles(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(default=20, le=50, ge=1),
    db: Session = Depends(get_db)
):
    """
    Search published articles by title or content.
    Excludes binary image_data to prevent memory issues.
    """
    search_term = f"%{q}%"
    
    articles = db.query(ContentQueue).filter(
        ContentQueue.status.in_(['approved', 'posted']),
        or_(
            ContentQueue.translated_title.ilike(search_term),
            ContentQueue.source_title.ilike(search_term)
        )
    ).options(
        defer(ContentQueue.image_data),
        defer(ContentQueue.original_text)
    ).order_by(desc(ContentQueue.created_at)).limit(limit).all()
    
    result = []
    for article in articles:
        content_preview = ""
        if article.translated_text:
            content_preview = article.translated_text[:300] + "..." if len(article.translated_text) > 300 else article.translated_text
        result.append({
            "id": article.id,
            "title": article.translated_title or article.source_title,
            "content": content_preview,
            "source": article.source,
            "image_url": f"https://gradus-ai.onrender.com/api/images/serve/{article.id}",
            "published_at": (article.posted_at or article.reviewed_at or article.created_at).isoformat() if (article.posted_at or article.reviewed_at or article.created_at) else None
        })
    
    return {
        "query": q,
        "count": len(result),
        "articles": result
    }

@router.get("/{article_id}")
async def get_article_by_id(
    article_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a single published article by ID.
    Excludes binary image_data to prevent memory issues.
    """
    article = db.query(ContentQueue).filter(
        ContentQueue.id == article_id,
        ContentQueue.status.in_(['approved', 'posted'])
    ).options(
        defer(ContentQueue.image_data)
    ).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return {
        "id": article.id,
        "title": article.translated_title or article.source_title,
        "content": article.translated_text or article.original_text,
        "source": article.source,
        "source_url": article.source_url,
        "image_url": f"https://gradus-ai.onrender.com/api/images/serve/{article.id}",
        "platforms": article.platforms,
        "published_at": (article.posted_at or article.reviewed_at or article.created_at).isoformat() if (article.posted_at or article.reviewed_at or article.created_at) else None,
        "language": article.language
    }

@router.get("/debug/status-count")
async def debug_status_count(db: Session = Depends(get_db)):
    """
    Debug endpoint: Show article status distribution in database.
    Helps diagnose why dashboard shows different counts than API.
    """
    from sqlalchemy import cast, String
    
    counts = db.query(
        ContentQueue.status,
        func.count(ContentQueue.id)
    ).group_by(ContentQueue.status).all()
    
    facebook_approved = db.query(ContentQueue).filter(
        ContentQueue.status == 'approved',
        cast(ContentQueue.platforms, String).like('%facebook%')
    ).count()
    
    linkedin_approved = db.query(ContentQueue).filter(
        ContentQueue.status == 'approved',
        cast(ContentQueue.platforms, String).like('%linkedin%')
    ).count()
    
    sample_approved = db.query(ContentQueue).filter(
        ContentQueue.status == 'approved'
    ).order_by(desc(ContentQueue.created_at)).limit(5).all()
    
    return {
        "status_counts": {status: count for status, count in counts},
        "total": sum(count for _, count in counts),
        "facebook_approved": facebook_approved,
        "linkedin_approved": linkedin_approved,
        "sample_approved_articles": [
            {
                "id": a.id,
                "title": (a.translated_title or a.source_title or "")[:50],
                "status": a.status,
                "platforms": a.platforms,
                "has_fb_post_id": bool(a.extra_metadata and a.extra_metadata.get('fb_post_id')),
                "has_linkedin_post_id": bool(a.extra_metadata and a.extra_metadata.get('linkedin_post_id'))
            } for a in sample_approved
        ]
    }
