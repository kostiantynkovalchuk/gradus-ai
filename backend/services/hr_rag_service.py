"""
HR RAG Service for Knowledge Retrieval
- Semantic search in Pinecone
- Preset answer matching
- Hybrid search combining keyword and semantic
- AI-generated answers with Claude
"""

import re
import os
import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from openai import OpenAI
from anthropic import Anthropic
from fuzzywuzzy import fuzz

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.3"))


@dataclass
class SearchResult:
    """Single search result"""
    content_id: str
    title: str
    text: str
    score: float
    category: Optional[str] = None
    metadata: Optional[Dict] = None


@dataclass
class AnswerResponse:
    """AI-generated answer with sources"""
    text: str
    sources: List[SearchResult]
    from_preset: bool = False
    confidence: float = 0.0


class HRRagService:
    """RAG service for HR knowledge base retrieval"""
    
    HR_NAMESPACE = "hr_docs"
    
    def __init__(self, pinecone_index=None, db_session=None):
        self.pinecone_index = pinecone_index
        self.db_session = db_session
        self._presets_cache = None
    
    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for query"""
        try:
            text = text[:8000]
            response = openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise
    
    async def semantic_search(
        self,
        query: str,
        top_k: int = None,
        filter_category: str = None
    ) -> List[SearchResult]:
        """
        Semantic search in Pinecone HR namespace
        """
        if not self.pinecone_index:
            logger.warning("Pinecone index not available")
            return []
        
        top_k = top_k or RAG_TOP_K
        
        try:
            query_embedding = self._get_embedding(query)
            
            filter_dict = {}
            if filter_category:
                filter_dict['category'] = filter_category
            
            results = self.pinecone_index.query(
                vector=query_embedding,
                top_k=top_k,
                namespace=self.HR_NAMESPACE,
                include_metadata=True,
                filter=filter_dict if filter_dict else None
            )
            
            search_results = []
            for match in results.get('matches', []):
                metadata = match.get('metadata', {})
                search_results.append(SearchResult(
                    content_id=metadata.get('content_id', ''),
                    title=metadata.get('title', ''),
                    text=metadata.get('text', ''),
                    score=match.get('score', 0.0),
                    category=metadata.get('category'),
                    metadata=metadata
                ))
            
            all_count = len(search_results)
            if search_results:
                logger.info(f"🎯 Top match score: {search_results[0].score:.4f} | Title: {search_results[0].title}")
            
            search_results = [r for r in search_results if r.score >= RAG_SIMILARITY_THRESHOLD]
            
            logger.info(f"Semantic search for '{query[:50]}...' returned {all_count} raw, {len(search_results)} above threshold ({RAG_SIMILARITY_THRESHOLD})")
            return search_results
            
        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []
    
    async def check_preset_answer(self, query: str) -> Optional[AnswerResponse]:
        """
        Check if query matches any preset answers
        Uses: exact match, fuzzy match, keyword detection
        """
        if self._presets_cache is None:
            await self._load_presets()
        
        if not self._presets_cache:
            return None
        
        query_lower = query.lower().strip()
        
        for preset in self._presets_cache:
            pattern = preset['pattern']
            
            if re.search(pattern, query_lower):
                await self._increment_preset_usage(preset['id'])
                return AnswerResponse(
                    text=preset['answer'],
                    sources=[],
                    from_preset=True,
                    confidence=1.0
                )
        
        for preset in self._presets_cache:
            keywords = preset['pattern'].split('|')
            for keyword in keywords:
                ratio = fuzz.partial_ratio(keyword.strip(), query_lower)
                if ratio >= 85:
                    await self._increment_preset_usage(preset['id'])
                    return AnswerResponse(
                        text=preset['answer'],
                        sources=[],
                        from_preset=True,
                        confidence=ratio / 100.0
                    )
        
        return None
    
    async def _load_presets(self):
        """Load preset answers from database"""
        if not self.db_session:
            self._presets_cache = []
            return
        
        try:
            from models.hr_models import HRPresetAnswer
            
            presets = self.db_session.query(HRPresetAnswer).filter(
                HRPresetAnswer.is_active == True
            ).order_by(HRPresetAnswer.priority.desc()).all()
            
            self._presets_cache = [
                {
                    'id': p.id,
                    'pattern': p.question_pattern,
                    'answer': p.answer_text,
                    'content_ids': p.content_ids or []
                }
                for p in presets
            ]
            
            logger.info(f"Loaded {len(self._presets_cache)} preset answers")
        except Exception as e:
            logger.error(f"Failed to load presets: {e}")
            self._presets_cache = []
    
    async def _increment_preset_usage(self, preset_id: int):
        """Increment usage count for a preset"""
        if not self.db_session:
            return
        
        try:
            from models.hr_models import HRPresetAnswer
            
            preset = self.db_session.query(HRPresetAnswer).filter(
                HRPresetAnswer.id == preset_id
            ).first()
            
            if preset:
                preset.usage_count = (preset.usage_count or 0) + 1
                self.db_session.commit()
        except Exception as e:
            logger.warning(f"Failed to increment preset usage: {e}")
    
    async def get_answer_with_context(
        self,
        query: str,
        user_context: dict = None
    ) -> AnswerResponse:
        """
        Get AI-generated answer with cost-optimized flow:
        1. Check presets first (instant, free)
        2. PostgreSQL keyword search (fast, free)
        3. RAG semantic search (only if keyword fails, costs $$$)
        """
        import time as _time
        _start = _time.time()
        
        preset_answer = await self.check_preset_answer(query)
        if preset_answer:
            _ms = int((_time.time() - _start) * 1000)
            logger.info(f"✅ PRESET hit for: '{query[:50]}' ({_ms}ms, cost: $0)")
            return preset_answer
        
        keyword_results = await self._keyword_search(query)
        keyword_results = sorted(keyword_results, key=lambda r: r.score, reverse=True)
        search_method = "keyword"
        
        def _keyword_quality_ok(results):
            if not results:
                return False
            best = results[0]
            if best.score >= 0.8:
                return True
            return False
        
        if _keyword_quality_ok(keyword_results):
            search_results = [r for r in keyword_results if r.score >= 0.5]
            _ms = int((_time.time() - _start) * 1000)
            logger.info(f"✅ KEYWORD hit for: '{query[:50]}' -> {len(search_results)} results (top: {search_results[0].score:.2f}, {_ms}ms, cost: $0)")
        else:
            if keyword_results:
                logger.info(f"⚠️ Keyword results below threshold (best: {keyword_results[0].score:.2f}), escalating to RAG")
            else:
                logger.info(f"🔍 No keyword matches, using RAG for: '{query[:50]}'")
            search_results = await self.semantic_search(query, top_k=5)
            search_method = "rag"
            
            if not search_results and keyword_results:
                search_results = [r for r in keyword_results if r.score > 0]
                search_method = "keyword_fallback"
                logger.info(f"🔄 RAG empty, using weak keyword results: {len(search_results)}")
            else:
                _ms = int((_time.time() - _start) * 1000)
                logger.info(f"{'✅' if search_results else '❌'} RAG search for: '{query[:50]}' -> {len(search_results)} results ({_ms}ms, cost: ~$0.0001)")
        
        if not search_results:
            logger.warning(f"❌ NO RESULTS for: '{query[:50]}' (tried keyword + RAG)")
            return AnswerResponse(
                text="Вибачте, я не знайшов відповідної інформації в базі знань. Спробуйте переформулювати питання або зверніться до HR-відділу.",
                sources=[],
                from_preset=False,
                confidence=0.0
            )
        
        context_parts = []
        for i, result in enumerate(search_results[:3], 1):
            context_parts.append(f"[Джерело {i}: {result.title}]\n{result.text}")
        
        context = "\n\n---\n\n".join(context_parts)
        
        system_prompt = """Ти — Maya, дружній HR-асистент компанії АВТД. 
Відповідай українською мовою, коротко та по суті.
Використовуй надану інформацію з бази знань для відповіді.
Якщо інформації недостатньо, чесно скажи про це.
Не вигадуй інформацію, якої немає в контексті."""
        
        user_prompt = f"""Контекст з бази знань HR:
{context}

Питання користувача: {query}

Дай коротку, корисну відповідь на основі наданого контексту."""
        
        try:
            response = anthropic_client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            
            answer_text = response.content[0].text
            
            avg_score = sum(r.score for r in search_results[:3]) / min(3, len(search_results))
            
            return AnswerResponse(
                text=answer_text,
                sources=search_results[:3],
                from_preset=False,
                confidence=avg_score
            )
            
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            best_result = search_results[0]
            return AnswerResponse(
                text=f"На основі бази знань:\n\n{best_result.text[:500]}...",
                sources=[best_result],
                from_preset=False,
                confidence=best_result.score
            )
    
    async def hybrid_search(
        self,
        query: str,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7
    ) -> List[SearchResult]:
        """
        Combine keyword search (PostgreSQL) with semantic search (Pinecone)
        """
        semantic_results = await self.semantic_search(query, top_k=10)
        
        keyword_results = await self._keyword_search(query)
        
        combined = {}
        
        for result in semantic_results:
            combined[result.content_id] = {
                'result': result,
                'score': result.score * semantic_weight
            }
        
        for result in keyword_results:
            if result.content_id in combined:
                combined[result.content_id]['score'] += result.score * keyword_weight
            else:
                combined[result.content_id] = {
                    'result': result,
                    'score': result.score * keyword_weight
                }
        
        sorted_results = sorted(
            combined.values(),
            key=lambda x: x['score'],
            reverse=True
        )
        
        return [item['result'] for item in sorted_results[:RAG_TOP_K]]
    
    STOP_WORDS_UK = {
        'як', 'що', 'де', 'чи', 'та', 'і', 'а', 'в', 'на', 'з', 'до', 'від',
        'за', 'по', 'для', 'при', 'про', 'це', 'той', 'та', 'ті', 'ця', 'цей',
        'мій', 'мені', 'мне', 'його', 'її', 'їх', 'наш', 'ваш', 'свій',
        'бути', 'є', 'був', 'була', 'було', 'будь', 'можна', 'треба', 'потрібно',
        'не', 'ні', 'так', 'вже', 'ще', 'або', 'але', 'якщо', 'коли',
        'хто', 'чому', 'скільки', 'який', 'яка', 'яке', 'які',
        'дуже', 'також', 'тому', 'тоді', 'зараз', 'після',
        'робота', 'роботи', 'працювати', 'робити', 'зробити',
        'системі', 'система', 'компанії', 'компанія'
    }
    
    async def _keyword_search(self, query: str) -> List[SearchResult]:
        """PostgreSQL keyword search in HR content"""
        if not self.db_session:
            return []
        
        try:
            from models.hr_models import HRContent
            from sqlalchemy import or_, func
            
            query_lower = query.lower()
            all_keywords = query_lower.split()
            keywords = [kw for kw in all_keywords if kw not in self.STOP_WORDS_UK and len(kw) > 2]
            
            if not keywords:
                keywords = [kw for kw in all_keywords if len(kw) > 2]
            
            if not keywords:
                return []
            
            filters = []
            for kw in keywords:
                filters.append(func.lower(HRContent.title).contains(kw))
                filters.append(func.lower(HRContent.content).contains(kw))
                filters.append(HRContent.keywords.any(kw))
            
            results = self.db_session.query(HRContent).filter(
                or_(*filters)
            ).limit(10).all()
            
            search_results = []
            for r in results:
                title_lower = r.title.lower()
                content_lower = r.content.lower()
                match_count = sum(1 for kw in keywords if kw in title_lower or kw in content_lower)
                title_match = sum(1 for kw in keywords if kw in title_lower)
                title_bonus = 0.2 if title_match > 0 else 0.0
                score = min(1.0, (match_count / len(keywords)) + title_bonus) if keywords else 0.0
                
                search_results.append(SearchResult(
                    content_id=r.content_id,
                    title=r.title,
                    text=r.content[:500],
                    score=score,
                    category=r.category
                ))
            
            return sorted(search_results, key=lambda x: x.score, reverse=True)
            
        except Exception as e:
            logger.error(f"Keyword search error: {e}")
            return []
    
    async def get_content_by_id(self, content_id: str) -> Optional[Dict]:
        """Retrieve specific content by ID"""
        if not self.db_session:
            return None
        
        try:
            from models.hr_models import HRContent
            
            content = self.db_session.query(HRContent).filter(
                HRContent.content_id == content_id
            ).first()
            
            if content:
                video_url = content.video_url
                if content.content_type == 'video' and not video_url and content.content_id.startswith('video_'):
                    base_url = os.getenv('BASE_URL', 'https://gradus-ai.onrender.com')
                    video_url = f"{base_url}/static/videos/{content.content_id}.mp4"
                
                return {
                    'content_id': content.content_id,
                    'title': content.title,
                    'content': content.content,
                    'content_type': content.content_type,
                    'category': content.category,
                    'subcategory': content.subcategory,
                    'keywords': content.keywords,
                    'video_url': video_url,
                    'attachments': content.attachments
                }
            return None
            
        except Exception as e:
            logger.error(f"Get content error: {e}")
            return None
    
    async def get_menu_structure(self, menu_id: str = 'main') -> List[Dict]:
        """Get menu structure for navigation"""
        if not self.db_session:
            return []
        
        try:
            from models.hr_models import HRMenuStructure
            
            if menu_id == 'main':
                menus = self.db_session.query(HRMenuStructure).filter(
                    HRMenuStructure.parent_id == None,
                    HRMenuStructure.is_active == True
                ).order_by(HRMenuStructure.order_index).all()
            else:
                menus = self.db_session.query(HRMenuStructure).filter(
                    HRMenuStructure.parent_id == menu_id,
                    HRMenuStructure.is_active == True
                ).order_by(HRMenuStructure.order_index).all()
            
            return [
                {
                    'menu_id': m.menu_id,
                    'title': m.title,
                    'emoji': m.emoji,
                    'button_type': m.button_type,
                    'content_id': m.content_id
                }
                for m in menus
            ]
            
        except Exception as e:
            logger.error(f"Get menu error: {e}")
            return []
    
    def reload_presets(self):
        """Force reload of preset answers cache"""
        self._presets_cache = None
        logger.info("Preset cache cleared, will reload on next request")
    
    async def log_query(
        self,
        user_id: int,
        query: str,
        preset_matched: bool = False,
        rag_used: bool = False,
        content_ids: List[str] = None,
        response_time_ms: int = 0,
        user_name: str = None,
        preset_id: int = None
    ) -> Optional[int]:
        """Log query to database for analytics"""
        if not self.db_session:
            return None
        
        try:
            from sqlalchemy import text
            
            query_normalized = query.lower().strip()
            content_ids_str = content_ids or []
            
            result = self.db_session.execute(text("""
                INSERT INTO hr_query_log (
                    user_id, user_name, query, query_normalized,
                    preset_matched, preset_id, rag_used,
                    content_ids, response_time_ms
                )
                VALUES (
                    :user_id, :user_name, :query, :query_normalized,
                    :preset_matched, :preset_id, :rag_used,
                    :content_ids, :response_time_ms
                )
                RETURNING id
            """), {
                'user_id': user_id,
                'user_name': user_name,
                'query': query,
                'query_normalized': query_normalized,
                'preset_matched': preset_matched,
                'preset_id': preset_id,
                'rag_used': rag_used,
                'content_ids': content_ids_str,
                'response_time_ms': response_time_ms
            })
            
            log_id = result.scalar()
            self.db_session.commit()
            
            logger.debug(f"Logged HR query: {query[:30]}... (log_id={log_id})")
            return log_id
            
        except Exception as e:
            logger.error(f"Failed to log query: {e}")
            return None
    
    async def log_feedback(
        self,
        log_id: int,
        user_id: int,
        feedback_type: str,
        comment: str = None
    ) -> bool:
        """Log user feedback for a query"""
        if not self.db_session or not log_id:
            return False
        
        try:
            from sqlalchemy import text
            
            self.db_session.execute(text("""
                INSERT INTO hr_feedback (query_log_id, user_id, feedback_type, comment)
                VALUES (:log_id, :user_id, :feedback_type, :comment)
            """), {
                'log_id': log_id,
                'user_id': user_id,
                'feedback_type': feedback_type,
                'comment': comment
            })
            
            satisfied = feedback_type == 'helpful'
            self.db_session.execute(text("""
                UPDATE hr_query_log SET satisfied = :satisfied WHERE id = :log_id
            """), {'log_id': log_id, 'satisfied': satisfied})
            
            self.db_session.commit()
            
            logger.info(f"Logged feedback: {feedback_type} for log_id={log_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")
            return False
    
    async def get_analytics_stats(self, days: int = 7) -> Dict:
        """Get HR bot analytics for the last N days"""
        if not self.db_session:
            return {}
        
        try:
            from sqlalchemy import text
            
            result = self.db_session.execute(text("""
                SELECT 
                    COUNT(*) as total_queries,
                    COUNT(*) FILTER (WHERE preset_matched = TRUE) as preset_hits,
                    COUNT(*) FILTER (WHERE rag_used = TRUE) as rag_queries,
                    COUNT(DISTINCT user_id) as unique_users,
                    COALESCE(AVG(response_time_ms)::INTEGER, 0) as avg_response_time_ms,
                    (COUNT(*) FILTER (WHERE satisfied = TRUE)::DECIMAL / 
                     NULLIF(COUNT(*) FILTER (WHERE satisfied IS NOT NULL), 0) * 100)::DECIMAL(5,2) as satisfaction_rate
                FROM hr_query_log
                WHERE created_at >= NOW() - make_interval(days => :days)
            """), {'days': days})
            
            row = result.fetchone()
            
            if row:
                return {
                    'total_queries': row[0] or 0,
                    'preset_hits': row[1] or 0,
                    'rag_queries': row[2] or 0,
                    'unique_users': row[3] or 0,
                    'avg_response_time_ms': row[4] or 0,
                    'satisfaction_rate': float(row[5]) if row[5] else None,
                    'preset_hit_rate': round((row[1] or 0) / max(row[0] or 1, 1) * 100, 1)
                }
            return {}
            
        except Exception as e:
            logger.error(f"Failed to get analytics: {e}")
            return {}
    
    async def get_unanswered_queries(self, limit: int = 20) -> List[Dict]:
        """Get queries that weren't answered by presets (candidates for new presets)"""
        if not self.db_session:
            return []
        
        try:
            from sqlalchemy import text
            
            result = self.db_session.execute(text("""
                SELECT 
                    query_normalized,
                    COUNT(*) as count,
                    MAX(created_at) as last_asked
                FROM hr_query_log
                WHERE preset_matched = FALSE
                GROUP BY query_normalized
                ORDER BY count DESC, last_asked DESC
                LIMIT :limit
            """), {'limit': limit})
            
            return [
                {
                    'query': row[0],
                    'count': row[1],
                    'last_asked': row[2].isoformat() if row[2] else None
                }
                for row in result.fetchall()
            ]
            
        except Exception as e:
            logger.error(f"Failed to get unanswered queries: {e}")
            return []
    
    async def get_common_questions(self, days: int = 30, limit: int = 20) -> List[Dict]:
        """Get most commonly asked questions overall (regardless of preset match)"""
        if not self.db_session:
            return []
        
        try:
            from sqlalchemy import text
            
            result = self.db_session.execute(text("""
                SELECT 
                    query_normalized,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE preset_matched = TRUE) as preset_hits,
                    COUNT(*) FILTER (WHERE satisfied = TRUE) as satisfied_count,
                    COUNT(*) FILTER (WHERE satisfied IS NOT NULL) as feedback_count,
                    COALESCE(AVG(response_time_ms)::INTEGER, 0) as avg_response_time,
                    MAX(created_at) as last_asked
                FROM hr_query_log
                WHERE created_at >= NOW() - make_interval(days => :days)
                GROUP BY query_normalized
                ORDER BY count DESC, last_asked DESC
                LIMIT :limit
            """), {'days': days, 'limit': limit})
            
            return [
                {
                    'query': row[0],
                    'count': row[1],
                    'preset_hits': row[2],
                    'satisfaction_rate': round(row[3] / row[4] * 100, 1) if row[4] > 0 else None,
                    'avg_response_time_ms': row[5],
                    'last_asked': row[6].isoformat() if row[6] else None
                }
                for row in result.fetchall()
            ]
            
        except Exception as e:
            logger.error(f"Failed to get common questions: {e}")
            return []


    async def ingest_document(
        self,
        title: str,
        content: str,
        category: str = "uploaded",
        subcategory: str = "hr_admin",
        content_type: str = "document",
        keywords: list = None
    ) -> Dict:
        if not self.db_session or not self.pinecone_index:
            raise ValueError("Database session and Pinecone index required for ingestion")

        import re as _re
        import uuid as _uuid
        slug = _re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄґҐ0-9]+', '_', title.lower())[:50].strip('_')
        uid = _uuid.uuid4().hex[:8]
        content_id = f"doc_{slug}_{uid}"

        from models.hr_models import HRContent
        new_doc = HRContent(
            content_id=content_id,
            content_type=content_type,
            title=title,
            content=content,
            category=category,
            subcategory=subcategory,
            keywords=keywords or []
        )
        self.db_session.add(new_doc)
        self.db_session.commit()
        logger.info(f"DB insert OK: {content_id}")

        try:
            embedding = self._get_embedding(content[:8000])

            preview = content[:800].replace('\n', ' ')
            self.pinecone_index.upsert(
                vectors=[(
                    f"hr_content_{content_id}",
                    embedding,
                    {
                        'content_id': content_id,
                        'title': title,
                        'category': category,
                        'text': preview
                    }
                )],
                namespace=self.HR_NAMESPACE
            )
            logger.info(f"Pinecone upsert OK: {content_id}")
        except Exception as e:
            logger.error(f"Embedding/Pinecone error for {content_id}: {e}")
            return {
                'content_id': content_id,
                'status': 'partial',
                'error': f'DB OK, but embedding failed: {e}'
            }

        return {
            'content_id': content_id,
            'status': 'success',
            'title': title,
            'content_length': len(content)
        }


def get_hr_rag_service(pinecone_index=None, db_session=None) -> HRRagService:
    """Factory function to create HR RAG service instance"""
    return HRRagService(pinecone_index=pinecone_index, db_session=db_session)
