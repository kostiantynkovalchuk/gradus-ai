"""
HR Content Processor for Maya HR Bot
- Parses HR knowledge base content
- Creates text chunks for embedding
- Generates embeddings via OpenAI
- Stores in Pinecone and PostgreSQL
"""

import re
import os
import logging
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from openai import OpenAI

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))


@dataclass
class ContentItem:
    """Structured HR content item"""
    content_id: str
    content_type: str
    title: str
    content: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    keywords: Optional[List[str]] = None
    video_url: Optional[str] = None
    attachments: Optional[Dict] = None
    metadata: Optional[Dict] = None


@dataclass
class ContentChunk:
    """A chunk of content ready for embedding"""
    content_id: str
    chunk_index: int
    text: str
    metadata: Dict


class HRContentProcessor:
    """Process HR knowledge base content for RAG system"""
    
    SECTION_PATTERNS = {
        'main_section': r'^#{1,2}\s*(.+)$',
        'question': r'^(\d+)\.\s*(.+)$',
        'appendix': r'^#\s*Приложение\s*№?(\d+)',
        'video_marker': r'видео|відео|video',
        'table_start': r'^\|',
    }
    
    CATEGORY_MAPPING = {
        'документи': 'onboarding',
        'працевлаштування': 'onboarding',
        'прийом': 'onboarding',
        'зарплата': 'salary',
        'виплата': 'salary',
        'аванс': 'salary',
        'нарахування': 'salary',
        'відпустка': 'vacation',
        'відпочинок': 'vacation',
        'лікарняний': 'sick_leave',
        'захворів': 'sick_leave',
        'хвороба': 'sick_leave',
        'графік': 'schedule',
        'робочий час': 'schedule',
        'техніка': 'tech_support',
        'обладнання': 'tech_support',
        'ноутбук': 'tech_support',
        'комп\'ютер': 'tech_support',
        'урс': 'tech_support',
        'віддалений': 'remote_work',
        'удаленка': 'remote_work',
        'контакт': 'contacts',
        'телефон': 'contacts',
        'компанія': 'about',
        'структура': 'about',
        'бонус': 'bonuses',
        'премія': 'bonuses',
        'командировка': 'business_trip',
        'відрядження': 'business_trip',
        'канцтовари': 'supplies',
        'меблі': 'supplies',
        'конфлікт': 'hr',
        'звільнення': 'hr',
        'юридич': 'legal',
        'договір': 'legal',
    }
    
    def __init__(self):
        self.total_chunks = 0
        self.total_presets = 0
        self.processed_items: List[ContentItem] = []
    
    def parse_google_doc(self, doc_text: str) -> List[ContentItem]:
        """Parse Google Doc text into structured content items"""
        items = []
        current_section = None
        current_content = []
        current_title = None
        question_number = 0
        
        lines = doc_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            appendix_match = re.match(self.SECTION_PATTERNS['appendix'], line)
            if appendix_match:
                if current_content and current_title:
                    if current_section:
                        cid = f"section_{current_section}"
                    elif question_number:
                        cid = f"q{question_number}"
                    else:
                        cid = "section_unknown"
                    items.append(self._create_content_item(
                        content_id=cid,
                        title=current_title,
                        content='\n'.join(current_content),
                        content_type='text'
                    ))
                
                current_section = f"appendix_{appendix_match.group(1)}"
                current_title = line.lstrip('#').strip()
                current_content = []
                question_number = 0
                continue
            
            question_match = re.match(self.SECTION_PATTERNS['question'], line)
            if question_match:
                if current_content and current_title:
                    items.append(self._create_content_item(
                        content_id=f"q{question_number}" if question_number else f"section_{current_section}",
                        title=current_title,
                        content='\n'.join(current_content),
                        content_type='text'
                    ))
                
                question_number = int(question_match.group(1))
                current_title = question_match.group(2)
                current_content = []
                current_section = None
                continue
            
            section_match = re.match(self.SECTION_PATTERNS['main_section'], line)
            if section_match and not line.startswith('|'):
                if current_content and current_title:
                    content_type = 'video' if self._is_video_content('\n'.join(current_content)) else 'text'
                    items.append(self._create_content_item(
                        content_id=f"section_{current_section}" if current_section else f"q{question_number}",
                        title=current_title,
                        content='\n'.join(current_content),
                        content_type=content_type
                    ))
                
                section_name = section_match.group(1).strip()
                current_section = self._generate_section_id(section_name)
                current_title = section_name
                current_content = []
                question_number = 0
                continue
            
            current_content.append(line)
        
        if current_content and current_title:
            items.append(self._create_content_item(
                content_id=f"q{question_number}" if question_number else f"section_{current_section}",
                title=current_title,
                content='\n'.join(current_content),
                content_type='text'
            ))
        
        self.processed_items = items
        logger.info(f"Parsed {len(items)} content items from document")
        return items
    
    def _create_content_item(
        self,
        content_id: str,
        title: str,
        content: str,
        content_type: str
    ) -> ContentItem:
        """Create a ContentItem with auto-detected category and keywords"""
        category = self._detect_category(title + ' ' + content)
        keywords = self._extract_keywords(title + ' ' + content)
        
        return ContentItem(
            content_id=content_id,
            content_type=content_type,
            title=title,
            content=content,
            category=category,
            keywords=keywords
        )
    
    def _is_video_content(self, text: str) -> bool:
        """Check if content is video-related"""
        return bool(re.search(self.SECTION_PATTERNS['video_marker'], text.lower()))
    
    def _generate_section_id(self, section_name: str) -> str:
        """Generate a clean section ID from name"""
        clean_name = re.sub(r'[^\w\s]', '', section_name.lower())
        clean_name = re.sub(r'\s+', '_', clean_name.strip())
        return clean_name[:50] if len(clean_name) > 50 else clean_name
    
    def _detect_category(self, text: str) -> str:
        """Auto-detect category from content"""
        text_lower = text.lower()
        for keyword, category in self.CATEGORY_MAPPING.items():
            if keyword in text_lower:
                return category
        return 'general'
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from text"""
        text_lower = text.lower()
        keywords = []
        
        hr_keywords = [
            'документи', 'паспорт', 'інн', 'договір', 'трудовий',
            'зарплата', 'аванс', 'виплата', 'оклад', 'премія',
            'відпустка', 'лікарняний', 'графік', 'робочий',
            'техніка', 'ноутбук', 'пошта', 'slack', 'vpn',
            'контакт', 'hr', 'бухгалтерія', 'керівник',
            'навчання', 'адаптація', 'випробувальний',
            'сед', 'бліц', 'урс', 'віддалений', 'командировка',
            'відрядження', 'канцтовари', 'конфлікт', 'звільнення',
            'клієнт', 'crm', 'ліміт', 'бронювання', 'меблі',
            'обладнання', 'кпк', 'планшет', 'мобільна торгівля'
        ]
        
        for kw in hr_keywords:
            if kw in text_lower:
                keywords.append(kw)
        
        return list(set(keywords))[:15]
    
    def _parse_table(self, table_text: str) -> dict:
        """Parse markdown tables into structured format"""
        lines = [l for l in table_text.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            return {'headers': [], 'rows': [], 'row_count': 0, 'column_count': 0}
        
        header = [cell.strip() for cell in lines[0].split('|') if cell.strip()]
        rows = []
        
        for line in lines[2:]:
            if '|' in line and '---' not in line:
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    rows.append(cells)
        
        return {
            'headers': header,
            'rows': rows,
            'row_count': len(rows),
            'column_count': len(header)
        }
    
    def _detect_table_in_content(self, content: str) -> bool:
        """Check if content contains a markdown table"""
        return '|' in content and '---' in content
    
    def chunk_content(self, content: str, max_chars: int = 2000) -> List[str]:
        """Split content into overlapping chunks"""
        if len(content) <= max_chars:
            return [content]
        
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', content)
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= max_chars:
                current_chunk += (" " if current_chunk else "") + sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        if len(chunks) > 1:
            overlap_chars = CHUNK_OVERLAP * 4
            overlapped_chunks = []
            for i, chunk in enumerate(chunks):
                if i > 0:
                    overlap = chunks[i-1][-overlap_chars:] if len(chunks[i-1]) > overlap_chars else chunks[i-1]
                    chunk = overlap + " " + chunk
                overlapped_chunks.append(chunk)
            chunks = overlapped_chunks
        
        return chunks
    
    def create_chunks(self, items: List[ContentItem]) -> List[ContentChunk]:
        """Create chunks from all content items"""
        all_chunks = []
        
        for item in items:
            text_to_chunk = f"{item.title}\n\n{item.content}"
            chunks = self.chunk_content(text_to_chunk)
            
            for i, chunk_text in enumerate(chunks):
                chunk = ContentChunk(
                    content_id=item.content_id,
                    chunk_index=i,
                    text=chunk_text,
                    metadata={
                        'content_id': item.content_id,
                        'chunk_index': i,
                        'title': item.title,
                        'category': item.category or 'general',
                        'subcategory': item.subcategory or '',
                        'content_type': item.content_type,
                        'keywords': item.keywords or []
                    }
                )
                all_chunks.append(chunk)
        
        self.total_chunks = len(all_chunks)
        logger.info(f"Created {len(all_chunks)} chunks from {len(items)} items")
        return all_chunks
    
    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a text chunk"""
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
    
    def generate_embeddings(self, chunks: List[ContentChunk]) -> List[Tuple[ContentChunk, List[float]]]:
        """Generate embeddings for all chunks"""
        results = []
        
        for i, chunk in enumerate(chunks):
            try:
                embedding = self.generate_embedding(chunk.text)
                results.append((chunk, embedding))
                
                if (i + 1) % 10 == 0:
                    logger.info(f"Generated embeddings: {i + 1}/{len(chunks)}")
            except Exception as e:
                logger.error(f"Failed to embed chunk {chunk.content_id}_{chunk.chunk_index}: {e}")
        
        return results
    
    def generate_pinecone_id(self, content_id: str, chunk_index: int) -> str:
        """Generate unique Pinecone vector ID (ASCII only)"""
        raw_id = f"hr_{content_id}_{chunk_index}"
        hash_part = hashlib.md5(raw_id.encode()).hexdigest()
        return f"hr_{hash_part}_{chunk_index}"
    
    async def upload_to_pinecone(
        self,
        chunks_with_embeddings: List[Tuple[ContentChunk, List[float]]],
        pinecone_index,
        namespace: str = "hr_docs"
    ) -> List[str]:
        """Upload embeddings to Pinecone"""
        vectors = []
        pinecone_ids = []
        
        for chunk, embedding in chunks_with_embeddings:
            pinecone_id = self.generate_pinecone_id(chunk.content_id, chunk.chunk_index)
            pinecone_ids.append(pinecone_id)
            
            vectors.append({
                'id': pinecone_id,
                'values': embedding,
                'metadata': {
                    **chunk.metadata,
                    'text': chunk.text[:1000]
                }
            })
        
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            try:
                pinecone_index.upsert(vectors=batch, namespace=namespace)
                logger.info(f"Uploaded batch {i // batch_size + 1} to Pinecone")
            except Exception as e:
                logger.error(f"Pinecone upload error: {e}")
                raise
        
        logger.info(f"Uploaded {len(vectors)} vectors to Pinecone namespace '{namespace}'")
        return pinecone_ids
    
    async def store_in_database(self, items: List[ContentItem], chunks: List[ContentChunk], pinecone_ids: List[str], db_session):
        """Store content and embeddings in PostgreSQL (with upsert logic)"""
        from models.hr_models import HRContent, HREmbedding
        
        for item in items:
            existing = db_session.query(HRContent).filter(
                HRContent.content_id == item.content_id
            ).first()
            
            if existing:
                existing.content_type = item.content_type
                existing.title = item.title
                existing.content = item.content
                existing.category = item.category
                existing.subcategory = item.subcategory
                existing.keywords = item.keywords
                existing.video_url = item.video_url
                existing.attachments = item.attachments
                existing.extra_data = item.metadata
            else:
                db_content = HRContent(
                    content_id=item.content_id,
                    content_type=item.content_type,
                    title=item.title,
                    content=item.content,
                    category=item.category,
                    subcategory=item.subcategory,
                    keywords=item.keywords,
                    video_url=item.video_url,
                    attachments=item.attachments,
                    extra_data=item.metadata
                )
                db_session.add(db_content)
        
        for chunk, pinecone_id in zip(chunks, pinecone_ids):
            existing_emb = db_session.query(HREmbedding).filter(
                HREmbedding.pinecone_id == pinecone_id
            ).first()
            
            if existing_emb:
                existing_emb.chunk_text = chunk.text
            else:
                db_embedding = HREmbedding(
                    content_id=chunk.content_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.text,
                    pinecone_id=pinecone_id
                )
                db_session.add(db_embedding)
        
        db_session.commit()
        logger.info(f"Stored {len(items)} content items and {len(chunks)} embeddings in PostgreSQL")
    
    async def generate_presets(self, db_session) -> int:
        """Generate preset answers for common questions"""
        from models.hr_models import HRPresetAnswer
        
        presets = [
            {
                'pattern': 'зарплата|виплата|коли платять|аванс',
                'answer': 'Заробітна плата виплачується 2 рази на місяць:\n• 20-22 числа — аванс\n• 5-7 числа — зарплата за відпрацьований місяць',
                'content_ids': ['q13_salary_dates'],
                'priority': 10
            },
            {
                'pattern': 'відпустка|скільки днів|відпочинок',
                'answer': 'У вас є 18 робочих днів (24 календарних) оплачуваної відпустки.\nНараховується 1,5 дня за кожен місяць роботи.\nОформити можна після 6 місяців роботи.',
                'content_ids': ['q8_vacation', 'q9_vacation_days'],
                'priority': 10
            },
            {
                'pattern': 'лікарняний|хворий|захворів',
                'answer': 'Якщо ви захворіли:\n1. Повідомте керівника\n2. Зверніться до лікаря для отримання лікарняного листа\n3. Надайте лікарняний лист до HR після одужання\n\nОплата: перші 5 днів — роботодавець, далі — фонд соціального страхування.',
                'content_ids': ['q10_sick_leave'],
                'priority': 10
            },
            {
                'pattern': 'документи|працевлаштування|що потрібно',
                'answer': 'Для працевлаштування потрібні:\n• Паспорт громадянина України\n• ІПН (ідентифікаційний код)\n• Трудова книжка (якщо є)\n• Диплом про освіту\n• Військовий квиток (для чоловіків)',
                'content_ids': ['q1_documents'],
                'priority': 10
            },
            {
                'pattern': 'графік|робочий день|час роботи',
                'answer': 'Робочий графік:\n• Пн-Пт: 9:00 - 18:00\n• Обідня перерва: 13:00 - 14:00\n• Субота, Неділя: вихідні',
                'content_ids': ['q5_schedule'],
                'priority': 10
            },
            {
                'pattern': 'техпідтримка|технічна|ноутбук|комп\'ютер',
                'answer': 'З питань технічної підтримки:\n• Telegram: @it_support_avtd\n• Email: it@avtd.ua\n• Slack: #it-help\n\nПроблеми з обладнанням, VPN, поштою — звертайтесь до IT-відділу.',
                'content_ids': ['q20_tech_support'],
                'priority': 10
            },
        ]
        
        count = 0
        for preset in presets:
            db_preset = HRPresetAnswer(
                question_pattern=preset['pattern'],
                answer_text=preset['answer'],
                content_ids=preset['content_ids'],
                priority=preset['priority'],
                is_active=True
            )
            db_session.merge(db_preset)
            count += 1
        
        db_session.commit()
        self.total_presets = count
        logger.info(f"Generated {count} preset answers")
        return count


async def process_hr_knowledge_base(doc_path: str, pinecone_index, db_session) -> Dict:
    """Main function to process HR knowledge base"""
    processor = HRContentProcessor()
    
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_text = f.read()
    
    logger.info("Parsing content...")
    items = processor.parse_google_doc(doc_text)
    
    logger.info("Creating chunks...")
    chunks = processor.create_chunks(items)
    
    logger.info("Generating embeddings...")
    chunks_with_embeddings = processor.generate_embeddings(chunks)
    
    logger.info("Uploading to Pinecone...")
    pinecone_ids = await processor.upload_to_pinecone(chunks_with_embeddings, pinecone_index)
    
    logger.info("Storing in database...")
    await processor.store_in_database(items, chunks, pinecone_ids, db_session)
    
    logger.info("Generating preset answers...")
    await processor.generate_presets(db_session)
    
    return {
        'content_items': len(items),
        'chunks': processor.total_chunks,
        'presets': processor.total_presets
    }
