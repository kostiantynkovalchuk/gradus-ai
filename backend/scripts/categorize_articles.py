"""Categorize all existing articles"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from models import engine
from models.content import ContentQueue
from sqlalchemy.orm import Session
from services.categorization import categorize_article

def add_category_column():
    """Add category column if it doesn't exist"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'content_queue' AND column_name = 'category'
        """))
        if not result.fetchone():
            print("Adding category column...")
            conn.execute(text("ALTER TABLE content_queue ADD COLUMN category VARCHAR(20)"))
            conn.commit()
            print("Category column added!")
        else:
            print("Category column already exists")

def categorize_all_articles():
    print("Starting article categorization...")
    
    add_category_column()
    
    with Session(engine) as db:
        articles = db.query(ContentQueue).filter(
            ContentQueue.status == 'posted',
            ContentQueue.category.is_(None)
        ).all()
        
        print(f"Found {len(articles)} articles to categorize\n")
        
        if not articles:
            print("No articles need categorization!")
            return
        
        categories_count = {'news': 0, 'reviews': 0, 'trends': 0}
        
        for i, article in enumerate(articles, 1):
            try:
                category = categorize_article(
                    article.translated_title or article.source_title,
                    (article.translated_text or article.original_text or "")[:2000]
                )
                
                article.category = category
                categories_count[category] += 1
                
                title_preview = (article.translated_title or article.source_title or "")[:60]
                print(f"{i}/{len(articles)} - [{category.upper()}] {title_preview}...")
                
                if i % 10 == 0:
                    db.commit()
                    print(f"  Saved batch\n")
                    
            except Exception as e:
                print(f"  Error: {e}")
                continue
        
        db.commit()
        
        print(f"\nCategorization complete!")
        print(f"   News: {categories_count['news']}")
        print(f"   Reviews: {categories_count['reviews']}")
        print(f"   Trends: {categories_count['trends']}")

if __name__ == "__main__":
    categorize_all_articles()
