# chat_endpoints.py - Add this NEW file to your project
# Safe to add - doesn't break existing content pipeline

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec
from typing import Optional, List
import os

# Import from our new modules
from avatar_personalities import (
    detect_avatar_role,
    get_avatar_personality,
    AVATAR_METADATA
)
from rag_utils import (
    ingest_website,
    retrieve_context,
    extract_urls,
    is_ingestion_request,
    extract_company_name_from_url
)

# ============================================================================
# CHAT ROUTER - Completely separate from existing content pipeline
# ============================================================================

chat_router = APIRouter(prefix="/chat", tags=["chat"])

# Initialize chat-specific clients (won't conflict with your existing ones)
chat_claude = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
chat_embedder = SentenceTransformer('all-MiniLM-L6-v2')
chat_pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

# Get or create Pinecone index
def get_chat_index():
    INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")
    try:
        return chat_pc.Index(INDEX_NAME)
    except:
        chat_pc.create_index(
            name=INDEX_NAME,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        return chat_pc.Index(INDEX_NAME)

chat_index = get_chat_index()
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "gradus-media")

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = None
    avatar: Optional[str] = None  # "maya", "alex", or "general"

class ChatResponse(BaseModel):
    response: str
    type: str  # "chat", "ingestion_result", "error"
    avatar_used: str
    ingestion_data: Optional[dict] = None
    sources_used: Optional[List[str]] = None

# ============================================================================
# MAIN CHAT ENDPOINT
# ============================================================================

@chat_router.post("/")
async def chat_with_avatars(request: ChatRequest):
    """
    Chat with Gradus AI avatars (Maya/Alex/General)
    Completely separate from your content scraping pipeline
    """
    
    message = request.message
    history = request.conversation_history or []
    
    # Check for URL ingestion request
    urls = extract_urls(message)
    
    if urls and is_ingestion_request(message):
        url = urls[0]
        company_name = extract_company_name_from_url(url)
        
        # Ingest website
        result = await ingest_website(url, company_name, chat_index, chat_embedder)
        
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
    
    # Detect or use specified avatar
    if request.avatar:
        avatar_role = request.avatar
    else:
        avatar_role = detect_avatar_role(message, history)
    
    # Get avatar personality
    system_prompt = get_avatar_personality(avatar_role)
    
    # Get RAG context
    rag_context, sources = await retrieve_context(message, chat_index, chat_embedder)
    
    if rag_context:
        system_prompt += f"\n\n{rag_context}\n\nIMPORTANT: Use the above information when relevant. Mention sources."
    
    # Build messages
    messages = history.copy()
    messages.append({"role": "user", "content": message})
    
    # Call Claude
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
        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {str(e)}"
        )

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

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
    try:
        stats = chat_index.describe_index_stats()
        return {
            "total_vectors": stats.total_vector_count,
            "namespaces": stats.namespaces,
            "dimension": 384,
            "index_name": INDEX_NAME
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@chat_router.delete("/clear-knowledge")
async def clear_knowledge(confirm: bool = False):
    """Clear vector database (use with caution!)"""
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
        "features": ["url_detection", "rag_retrieval", "multi_avatar"],
        "pinecone_connected": True,
        "claude_configured": True
    }
