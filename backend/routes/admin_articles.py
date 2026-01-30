"""
Admin Article Management API
Provides endpoints for viewing, searching, and deleting articles
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, defer
from sqlalchemy import desc, or_, func, text
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, date
import logging

from models import get_db
from models.content import ContentQueue, ApprovalLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/articles", tags=["Admin Articles"])


class AdminArticleResponse(BaseModel):
    id: int
    title: Optional[str]
    source: Optional[str]
    source_url: Optional[str]
    status: Optional[str]
    category: Optional[str]
    platforms: Optional[List[str]]
    has_image: bool
    created_at: Optional[datetime]
    posted_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class AdminArticlesListResponse(BaseModel):
    articles: List[AdminArticleResponse]
    total: int
    limit: int
    offset: int
    stats: dict


class ArticleDetailResponse(BaseModel):
    id: int
    title: Optional[str]
    content: Optional[str]
    source: Optional[str]
    source_url: Optional[str]
    status: Optional[str]
    category: Optional[str]
    platforms: Optional[List[str]]
    has_image: bool
    image_url: Optional[str]
    created_at: Optional[datetime]
    posted_at: Optional[datetime]
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]
    approval_logs: List[dict]
    
    class Config:
        from_attributes = True


class DeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_article_id: int
    deleted_logs_count: int


class BulkDeleteRequest(BaseModel):
    article_ids: List[int]


class BulkDeleteResponse(BaseModel):
    success: bool
    deleted_count: int
    failed_ids: List[int]
    message: str


class DateRangeDeleteRequest(BaseModel):
    date_from: date
    date_to: date
    status_filter: Optional[str] = None


class FetchImageResponse(BaseModel):
    success: bool
    message: str
    image_url: Optional[str] = None
    image_credit: Optional[str] = None
    image_credit_url: Optional[str] = None
    image_photographer: Optional[str] = None
    all_images: Optional[List[dict]] = None


@router.post("/{article_id}/fetch-image", response_model=FetchImageResponse)
async def fetch_image_for_article(
    article_id: int,
    db: Session = Depends(get_db)
):
    """
    Fetch a new image from Unsplash for an article.
    Auto-applies the best matching image and returns alternatives.
    """
    from services.unsplash_service import unsplash_service
    
    article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    title = article.translated_title or article.source_title or ""
    content = article.translated_text or article.original_text or ""
    
    if not title and not content:
        raise HTTPException(status_code=400, detail="Article has no content for image search")
    
    try:
        result = unsplash_service.select_image_for_article(title, content)
        
        if not result:
            raise HTTPException(
                status_code=404, 
                detail="No suitable images found. Try again later or with different content."
            )
        
        article.image_url = result['image_url']
        article.image_credit = result['image_credit']
        article.image_credit_url = result['image_credit_url']
        article.image_photographer = result['image_photographer']
        article.unsplash_image_id = result['unsplash_image_id']
        article.image_data = None
        article.local_image_path = None
        article.image_prompt = None
        
        db.commit()
        
        logger.info(f"Fetched Unsplash image for article {article_id}: {result['unsplash_image_id']}")
        
        return FetchImageResponse(
            success=True,
            message=f"Image fetched successfully from Unsplash",
            image_url=result['image_url'],
            image_credit=result['image_credit'],
            image_credit_url=result['image_credit_url'],
            image_photographer=result['image_photographer'],
            all_images=result.get('all_images', [])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching Unsplash image for article {article_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to fetch image: {str(e)}")


@router.get("/stats")
async def get_article_stats(db: Session = Depends(get_db)):
    """Get article statistics"""
    total = db.query(func.count(ContentQueue.id)).scalar() or 0
    
    status_counts = db.query(
        ContentQueue.status,
        func.count(ContentQueue.id)
    ).group_by(ContentQueue.status).all()
    
    by_status = {status: count for status, count in status_counts if status}
    
    category_counts = db.query(
        ContentQueue.category,
        func.count(ContentQueue.id)
    ).group_by(ContentQueue.category).all()
    
    by_category = {cat or 'uncategorized': count for cat, count in category_counts}
    
    return {
        "total": total,
        "by_status": by_status,
        "by_category": by_category
    }


@router.get("/export/csv")
async def export_articles_csv(
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Export articles as CSV"""
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    query = db.query(ContentQueue).options(
        defer(ContentQueue.image_data),
        defer(ContentQueue.original_text),
        defer(ContentQueue.translated_text)
    )
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ContentQueue.source_title.ilike(search_term),
                ContentQueue.translated_title.ilike(search_term)
            )
        )
    
    if status:
        query = query.filter(ContentQueue.status == status)
    
    if date_from:
        query = query.filter(ContentQueue.created_at >= datetime.combine(date_from, datetime.min.time()))
    
    if date_to:
        from datetime import timedelta
        query = query.filter(ContentQueue.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    
    articles = query.order_by(desc(ContentQueue.created_at)).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Title', 'Source', 'Status', 'Category', 'Platforms', 'Created', 'Posted', 'URL'])
    
    for article in articles:
        writer.writerow([
            article.id,
            article.translated_title or article.source_title or '',
            article.source or '',
            article.status or '',
            article.category or '',
            ','.join(article.platforms) if article.platforms else '',
            article.created_at.strftime('%Y-%m-%d %H:%M') if article.created_at else '',
            article.posted_at.strftime('%Y-%m-%d %H:%M') if article.posted_at else '',
            article.source_url or ''
        ])
    
    output.seek(0)
    
    filename = f"articles_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_articles(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db)
):
    """Delete multiple articles at once"""
    
    if not request.article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")
    
    if len(request.article_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 articles per request")
    
    deleted_count = 0
    failed_ids = []
    
    for article_id in request.article_ids:
        try:
            article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
            
            if not article:
                failed_ids.append(article_id)
                continue
            
            db.query(ApprovalLog).filter(ApprovalLog.content_id == article_id).delete()
            db.delete(article)
            deleted_count += 1
            
        except Exception as e:
            logger.error(f"Failed to delete article {article_id}: {e}")
            failed_ids.append(article_id)
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to commit deletions: {str(e)}")
    
    return BulkDeleteResponse(
        success=len(failed_ids) == 0,
        deleted_count=deleted_count,
        failed_ids=failed_ids,
        message=f"Deleted {deleted_count} articles" + (f", {len(failed_ids)} failed" if failed_ids else "")
    )


@router.post("/delete-by-date")
async def delete_articles_by_date_range(
    request: DateRangeDeleteRequest,
    db: Session = Depends(get_db)
):
    """Delete articles within a date range"""
    
    from datetime import timedelta
    
    query = db.query(ContentQueue).filter(
        ContentQueue.created_at >= datetime.combine(request.date_from, datetime.min.time()),
        ContentQueue.created_at < datetime.combine(request.date_to + timedelta(days=1), datetime.min.time())
    )
    
    if request.status_filter:
        query = query.filter(ContentQueue.status == request.status_filter)
    
    articles = query.all()
    article_ids = [a.id for a in articles]
    
    if not article_ids:
        return {"success": True, "deleted_count": 0, "message": "No articles found in date range"}
    
    try:
        db.query(ApprovalLog).filter(ApprovalLog.content_id.in_(article_ids)).delete(synchronize_session=False)
        deleted_count = query.delete(synchronize_session=False)
        db.commit()
        
        logger.info(f"Deleted {deleted_count} articles from {request.date_from} to {request.date_to}")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Deleted {deleted_count} articles from {request.date_from} to {request.date_to}"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting articles by date: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete articles: {str(e)}")


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article_detail(
    article_id: int,
    db: Session = Depends(get_db)
):
    """Get full article details with approval history"""
    
    article = db.query(ContentQueue).options(
        defer(ContentQueue.image_data)
    ).filter(ContentQueue.id == article_id).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    logs = db.query(ApprovalLog).filter(ApprovalLog.content_id == article_id).order_by(desc(ApprovalLog.timestamp)).all()
    
    approval_logs = [
        {
            "id": log.id,
            "action": log.action,
            "moderator": log.moderator,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "details": log.details
        }
        for log in logs
    ]
    
    has_image = bool(article.image_data or article.local_image_path or article.image_url)
    
    return ArticleDetailResponse(
        id=article.id,
        title=article.translated_title or article.source_title,
        content=article.translated_text or article.original_text,
        source=article.source,
        source_url=article.source_url,
        status=article.status,
        category=article.category,
        platforms=article.platforms,
        has_image=has_image,
        image_url=article.image_url,
        created_at=article.created_at,
        posted_at=article.posted_at,
        reviewed_at=article.reviewed_at,
        reviewed_by=article.reviewed_by,
        approval_logs=approval_logs
    )


@router.delete("/{article_id}", response_model=DeleteResponse)
async def delete_article(
    article_id: int,
    db: Session = Depends(get_db)
):
    """Delete a single article and all related records"""
    
    article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    title = article.translated_title or article.source_title or "Untitled"
    
    try:
        deleted_logs = db.query(ApprovalLog).filter(ApprovalLog.content_id == article_id).delete()
        
        db.delete(article)
        db.commit()
        
        logger.info(f"Deleted article {article_id}: {title}")
        
        return DeleteResponse(
            success=True,
            message=f"Successfully deleted article: {title}",
            deleted_article_id=article_id,
            deleted_logs_count=deleted_logs
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting article {article_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete article: {str(e)}")


@router.get("", response_model=AdminArticlesListResponse)
async def get_admin_articles(
    limit: int = Query(default=20, le=100, ge=1),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Get articles with filtering for admin dashboard"""
    
    base_query = db.query(ContentQueue).options(
        defer(ContentQueue.image_data),
        defer(ContentQueue.original_text),
        defer(ContentQueue.translated_text)
    )
    
    if search:
        search_term = f"%{search}%"
        base_query = base_query.filter(
            or_(
                ContentQueue.source_title.ilike(search_term),
                ContentQueue.translated_title.ilike(search_term)
            )
        )
    
    if status:
        base_query = base_query.filter(ContentQueue.status == status)
    
    if date_from:
        base_query = base_query.filter(ContentQueue.created_at >= datetime.combine(date_from, datetime.min.time()))
    
    if date_to:
        from datetime import timedelta
        base_query = base_query.filter(ContentQueue.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    
    total = base_query.count()
    
    total_all = db.query(func.count(ContentQueue.id)).scalar() or 0
    
    status_counts = db.query(
        ContentQueue.status,
        func.count(ContentQueue.id)
    ).group_by(ContentQueue.status).all()
    
    by_status = {status: count for status, count in status_counts if status}
    
    category_counts = db.query(
        ContentQueue.category,
        func.count(ContentQueue.id)
    ).group_by(ContentQueue.category).all()
    
    by_category = {cat or 'uncategorized': count for cat, count in category_counts}
    
    stats = {
        "total": total_all,
        "by_status": by_status,
        "by_category": by_category
    }
    
    articles = base_query.order_by(desc(ContentQueue.created_at)).offset(offset).limit(limit).all()
    
    result = []
    for article in articles:
        has_image = bool(article.image_data or article.local_image_path or article.image_url)
        result.append(AdminArticleResponse(
            id=article.id,
            title=article.translated_title or article.source_title,
            source=article.source,
            source_url=article.source_url,
            status=article.status,
            category=article.category,
            platforms=article.platforms,
            has_image=has_image,
            created_at=article.created_at,
            posted_at=article.posted_at
        ))
    
    return AdminArticlesListResponse(
        articles=result,
        total=total,
        limit=limit,
        offset=offset,
        stats=stats
    )
