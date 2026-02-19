import re
import logging
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DocumentService:
    
    @staticmethod
    def extract_document_numbers(text: str) -> List[str]:
        patterns = [
            r'№\s*(\d+(?:\.\d+)?)',
            r'шаблон\s+(\d+)',
            r'додаток\s+(\d+(?:\.\d+)?)',
        ]
        
        numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            numbers.extend([f"№{m}" for m in matches])
        
        return list(set(numbers))
    
    @staticmethod
    def find_documents_by_numbers(db: Session, numbers: List[str]) -> List[Dict]:
        if not numbers:
            return []
        
        from models.hr_models import HRDocument
        
        docs = db.query(HRDocument).filter(
            HRDocument.document_number.in_(numbers),
            HRDocument.is_active == True
        ).order_by(HRDocument.document_type, HRDocument.document_number).all()
        
        return [
            {
                'id': doc.id,
                'title': doc.title,
                'document_type': doc.document_type,
                'document_number': doc.document_number,
                'url': doc.url,
                'category': doc.category,
                'description': doc.description
            }
            for doc in docs
        ]
    
    @staticmethod
    def find_documents_by_topics(db: Session, query: str, limit: int = 3) -> List[Dict]:
        query_lower = query.lower()
        words = re.findall(r'\b\w{3,}\b', query_lower)
        
        stopwords = {'який', 'яка', 'яке', 'як', 'що', 'коли', 'де', 'можна', 'треба', 
                      'потрібно', 'для', 'при', 'або', 'але', 'та', 'це', 'той', 'ця'}
        keywords = [w for w in words if w not in stopwords]
        
        if not keywords:
            return []
        
        from sqlalchemy import text
        
        rows = db.execute(text("""
            SELECT id, title, document_type, document_number,
                   url, category, description
            FROM hr_documents
            WHERE topics && CAST(:keywords AS varchar[])
              AND is_active = TRUE
            ORDER BY document_number
            LIMIT :limit
        """), {"keywords": keywords, "limit": limit}).fetchall()
        
        return [
            {
                'id': row[0],
                'title': row[1],
                'document_type': row[2],
                'document_number': row[3],
                'url': row[4],
                'category': row[5],
                'description': row[6]
            }
            for row in rows
        ]
    
    @staticmethod
    def find_documents(db: Session, query: str, answer_text: str, category: Optional[str] = None) -> List[Dict]:
        documents = []
        
        mentioned_numbers = DocumentService.extract_document_numbers(answer_text)
        if mentioned_numbers:
            logger.info(f"Found document numbers in answer: {mentioned_numbers}")
            mentioned_docs = DocumentService.find_documents_by_numbers(db, mentioned_numbers)
            documents.extend(mentioned_docs)
        
        if len(documents) < 2:
            topic_docs = DocumentService.find_documents_by_topics(db, query, limit=2)
            documents.extend(topic_docs)
        
        seen_ids = set()
        unique_docs = []
        for doc in documents:
            if doc['id'] not in seen_ids:
                seen_ids.add(doc['id'])
                unique_docs.append(doc)
        
        if unique_docs:
            logger.info(f"📄 Found {len(unique_docs)} documents for query: '{query[:50]}'")
        return unique_docs[:3]
    
    @staticmethod
    def format_documents_text(documents: List[Dict]) -> str:
        if not documents:
            return ""
        
        lines = ["\n\n📚 Документи:"]
        
        for doc in documents:
            title = doc['title']
            url = doc['url']
            lines.append(f"• {title}\n  {url}")
        
        return "\n".join(lines)


document_service = DocumentService()
