"""
HR Knowledge Base API Endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import logging
import os

from models import get_db
from services.hr_rag_service import HRRagService, SearchResult, AnswerResponse

logger = logging.getLogger(__name__)

hr_router = APIRouter(prefix="/api/hr", tags=["HR Knowledge"])

PINECONE_AVAILABLE = False
hr_pinecone_index = None

try:
    from pinecone import Pinecone
    
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if pinecone_key:
        hr_pc = Pinecone(api_key=pinecone_key)
        INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
        try:
            hr_pinecone_index = hr_pc.Index(INDEX_NAME)
            PINECONE_AVAILABLE = True
            logger.info(f"HR Routes: Pinecone connected to {INDEX_NAME}")
        except Exception as e:
            logger.warning(f"HR Routes: Pinecone index error: {e}")
except Exception as e:
    logger.warning(f"HR Routes: Pinecone not available: {e}")


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    category: Optional[str] = None


class AnswerRequest(BaseModel):
    query: str
    user_id: Optional[int] = None


class FeedbackRequest(BaseModel):
    content_id: str
    rating: int
    comment: Optional[str] = None


class SearchResultModel(BaseModel):
    content_id: str
    title: str
    text: str
    score: float
    category: Optional[str] = None


class AnswerResponseModel(BaseModel):
    text: str
    sources: List[SearchResultModel]
    from_preset: bool
    confidence: float


class ContentModel(BaseModel):
    content_id: str
    title: str
    content: str
    content_type: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    keywords: Optional[List[str]] = None
    video_url: Optional[str] = None


class MenuItemModel(BaseModel):
    menu_id: str
    title: str
    emoji: Optional[str] = None
    button_type: Optional[str] = None
    content_id: Optional[str] = None


def get_hr_service(db=None):
    """Create HR RAG service with dependencies"""
    db_session = next(get_db()) if db is None else db
    return HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)


@hr_router.post("/search", response_model=List[SearchResultModel])
async def search_knowledge(request: SearchRequest):
    """
    Semantic search in HR knowledge base
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        
        results = await service.semantic_search(
            query=request.query,
            top_k=request.top_k,
            filter_category=request.category
        )
        
        return [
            SearchResultModel(
                content_id=r.content_id,
                title=r.title,
                text=r.text,
                score=r.score,
                category=r.category
            )
            for r in results
        ]
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.post("/answer", response_model=AnswerResponseModel)
async def get_answer(request: AnswerRequest):
    """
    Get AI-generated answer with sources
    Uses presets first, then RAG if no match
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        
        answer = await service.get_answer_with_context(
            query=request.query,
            user_context={"user_id": request.user_id} if request.user_id else None
        )
        
        return AnswerResponseModel(
            text=answer.text,
            sources=[
                SearchResultModel(
                    content_id=s.content_id,
                    title=s.title,
                    text=s.text,
                    score=s.score,
                    category=s.category
                )
                for s in answer.sources
            ],
            from_preset=answer.from_preset,
            confidence=answer.confidence
        )
    except Exception as e:
        logger.error(f"Answer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.get("/content/{content_id}", response_model=ContentModel)
async def get_content(content_id: str):
    """
    Retrieve specific content by ID
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        
        content = await service.get_content_by_id(content_id)
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
        
        return ContentModel(**content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get content error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.get("/menu/{menu_id}", response_model=List[MenuItemModel])
async def get_menu(menu_id: str = "main"):
    """
    Get menu structure for navigation
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        
        items = await service.get_menu_structure(menu_id)
        
        return [MenuItemModel(**item) for item in items]
    except Exception as e:
        logger.error(f"Get menu error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.post("/hybrid-search", response_model=List[SearchResultModel])
async def hybrid_search(request: SearchRequest):
    """
    Hybrid search combining keyword and semantic search
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        
        results = await service.hybrid_search(query=request.query)
        
        return [
            SearchResultModel(
                content_id=r.content_id,
                title=r.title,
                text=r.text,
                score=r.score,
                category=r.category
            )
            for r in results
        ]
    except Exception as e:
        logger.error(f"Hybrid search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Track content helpfulness (for future improvements)
    """
    logger.info(f"Feedback received: content_id={request.content_id}, rating={request.rating}")
    return {"status": "success", "message": "Feedback recorded"}


@hr_router.post("/reload-presets")
async def reload_presets():
    """
    Force reload preset answers cache
    """
    try:
        db_session = next(get_db())
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db_session)
        service.reload_presets()
        return {"status": "success", "message": "Presets cache cleared"}
    except Exception as e:
        logger.error(f"Reload presets error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@hr_router.get("/stats")
async def get_stats():
    """
    Get HR knowledge base statistics
    """
    try:
        db_session = next(get_db())
        
        from models.hr_models import HRContent, HRPresetAnswer, HREmbedding
        
        content_count = db_session.query(HRContent).count()
        preset_count = db_session.query(HRPresetAnswer).filter(HRPresetAnswer.is_active == True).count()
        embedding_count = db_session.query(HREmbedding).count()
        
        top_presets = db_session.query(HRPresetAnswer).filter(
            HRPresetAnswer.is_active == True
        ).order_by(HRPresetAnswer.usage_count.desc()).limit(5).all()
        
        return {
            "content_items": content_count,
            "active_presets": preset_count,
            "embeddings": embedding_count,
            "pinecone_available": PINECONE_AVAILABLE,
            "top_preset_usage": [
                {"pattern": p.question_pattern[:50], "usage": p.usage_count}
                for p in top_presets
            ]
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
