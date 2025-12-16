from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
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
    """
    query = db.query(ContentQueue).filter(
        ContentQueue.status.in_(['approved', 'posted'])
    )
    
    if platform:
        query = query.filter(ContentQueue.platforms.contains([platform]))
    
    total = query.count()
    
    articles = query.order_by(desc(ContentQueue.created_at)).offset(offset).limit(limit).all()
    
    result = []
    for article in articles:
        result.append(ArticleResponse(
            id=article.id,
            title=article.translated_title or article.source_title,
            content=article.translated_text or article.original_text,
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
    limit: int = Query(default=20, le=100, ge=1),
    db: Session = Depends(get_db)
):
    """
    Search published articles by title or content.
    """
    search_term = f"%{q}%"
    
    articles = db.query(ContentQueue).filter(
        ContentQueue.status.in_(['approved', 'posted']),
        or_(
            ContentQueue.translated_title.ilike(search_term),
            ContentQueue.translated_text.ilike(search_term),
            ContentQueue.source_title.ilike(search_term),
            ContentQueue.original_text.ilike(search_term)
        )
    ).order_by(desc(ContentQueue.created_at)).limit(limit).all()
    
    result = []
    for article in articles:
        result.append({
            "id": article.id,
            "title": article.translated_title or article.source_title,
            "content": (article.translated_text or article.original_text or "")[:300] + "...",
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
    """
    article = db.query(ContentQueue).filter(
        ContentQueue.id == article_id,
        ContentQueue.status.in_(['approved', 'posted'])
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
