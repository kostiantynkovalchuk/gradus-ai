from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from typing import Optional, List
import os
import logging

from services.avatar_personalities import (
    detect_avatar_role,
    get_avatar_personality,
    AVATAR_METADATA
)
from services.rag_utils import (
    ingest_website,
    retrieve_context,
    extract_urls,
    is_ingestion_request,
    extract_company_name_from_url
)
from services.query_expansion import expand_brand_query

logger = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/chat", tags=["chat"])

chat_claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PINECONE_AVAILABLE = False
chat_index = None

try:
    from pinecone import Pinecone, ServerlessSpec
    
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if pinecone_key:
        chat_pc = Pinecone(api_key=pinecone_key)
        
        INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
        try:
            chat_index = chat_pc.Index(INDEX_NAME)
            PINECONE_AVAILABLE = True
            logger.info(f"Pinecone connected to index: {INDEX_NAME}")
        except Exception as e:
            logger.warning(f"Pinecone index not found, creating: {e}")
            try:
                chat_pc.create_index(
                    name=INDEX_NAME,
                    dimension=1536,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
                chat_index = chat_pc.Index(INDEX_NAME)
                PINECONE_AVAILABLE = True
            except Exception as create_err:
                logger.error(f"Failed to create Pinecone index: {create_err}")
    else:
        logger.warning("PINECONE_API_KEY not set - RAG features disabled")
except ImportError as e:
    logger.warning(f"Pinecone not installed: {e}")
except Exception as e:
    logger.error(f"Error initializing Pinecone: {e}")

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None
    avatar: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    type: str
    avatar_used: str
    ingestion_data: Optional[dict] = None
    sources_used: Optional[List[str]] = None

@chat_router.post("/")
async def chat_with_avatars(request: ChatRequest):
    """Chat with Gradus AI avatars (Maya/Alex/General)"""
    
    message = request.message
    history = request.conversation_history or []
    
    urls = extract_urls(message)
    
    if urls and is_ingestion_request(message) and PINECONE_AVAILABLE:
        url = urls[0]
        company_name = extract_company_name_from_url(url)
        
        result = await ingest_website(url, company_name, chat_index)
        
        if result['status'] == 'success':
            response_text = f"""{result['message']}

Тепер можу відповідати на питання про {company_name} на основі їхнього сайту.

Що саме вас цікавить?"""
            
            return ChatResponse(
                response=response_text,
                type="ingestion_result",
                avatar_used="general",
                ingestion_data=result
            )
        else:
            return ChatResponse(
                response=f"Вибачте, виникла проблема: {result['message']}",
                type="error",
                avatar_used="general",
                ingestion_data=result
            )
    
    if request.avatar:
        avatar_role = request.avatar
    else:
        avatar_role = detect_avatar_role(message, history)
    
    system_prompt = get_avatar_personality(avatar_role)
    
    rag_context = ""
    sources = []
    if PINECONE_AVAILABLE:
        expanded_query = expand_brand_query(message)
        rag_context, sources = await retrieve_context(expanded_query, chat_index)
        
        if rag_context:
            system_prompt += f"\n\n{rag_context}\n\nIMPORTANT: Use the above information when relevant. Mention sources."
    
    messages = history.copy()
    messages.append({"role": "user", "content": message})
    
    try:
        response = chat_claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            messages=messages
        )
        
        assistant_message = response.content[0].text
        
        return ChatResponse(
            response=assistant_message,
            type="chat",
            avatar_used=avatar_role,
            sources_used=sources if sources else None
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {str(e)}"
        )

@chat_router.get("/avatars")
async def list_avatars():
    """List available avatars"""
    return {
        "avatars": ["maya", "alex", "general"],
        "metadata": AVATAR_METADATA
    }

@chat_router.post("/switch-avatar")
async def switch_avatar(avatar: str):
    """Switch to specific avatar"""
    if avatar not in ["maya", "alex", "general"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid avatar. Choose: maya, alex, or general"
        )
    
    return {
        "avatar": avatar,
        "metadata": AVATAR_METADATA[avatar],
        "message": f"Switched to {AVATAR_METADATA[avatar]['name']}"
    }

@chat_router.get("/knowledge-stats")
async def knowledge_stats():
    """Get vector database statistics"""
    if not PINECONE_AVAILABLE:
        return {
            "status": "disabled",
            "message": "Pinecone not configured. Set PINECONE_API_KEY to enable RAG."
        }
    
    try:
        stats = chat_index.describe_index_stats()
        return {
            "total_vectors": stats.total_vector_count,
            "namespaces": dict(stats.namespaces) if stats.namespaces else {},
            "dimension": 1536,
            "index_name": os.getenv("PINECONE_INDEX_NAME", "gradus-media")
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@chat_router.delete("/clear-knowledge")
async def clear_knowledge(confirm: bool = False):
    """Clear vector database (use with caution!)"""
    if not PINECONE_AVAILABLE:
        return {"status": "disabled", "message": "Pinecone not configured"}
    
    if not confirm:
        return {
            "message": "Add ?confirm=true to actually clear the knowledge base"
        }
    
    try:
        chat_index.delete(delete_all=True, namespace="company_knowledge")
        return {
            "status": "success",
            "message": "Knowledge base cleared"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@chat_router.get("/health")
async def chat_health():
    """Health check for chat system"""
    return {
        "status": "healthy",
        "system": "Gradus AI Chat",
        "avatars_available": ["maya", "alex", "general"],
        "features": ["url_detection", "multi_avatar"],
        "rag_enabled": PINECONE_AVAILABLE,
        "pinecone_connected": PINECONE_AVAILABLE,
        "claude_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }
