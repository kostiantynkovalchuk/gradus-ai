#!/usr/bin/env python3
"""
Fix formatting issues in Modern Restaurant Management articles.
Removes photo credits and formats subtitles with markdown bold.

Usage: python scripts/fix_mrm_article.py
       python scripts/fix_mrm_article.py --article-id 177
       python scripts/fix_mrm_article.py --all-mrm
"""

import os
import sys
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.content import ContentQueue

PHOTO_CREDIT_PATTERNS = [
    r'^Photo(?:s)?\s+by\s+[A-Za-z\s\.\-\']+$',
    r'^Top\s+photo:\s+.*$',
    r'^Photo:\s+.*$',
    r'^Image(?:s)?:\s+.*$',
    r'^Credit:\s+.*$',
    r'^Photo\s+courtesy\s+.*$',
    r'^\([Pp]hoto(?:s)?\s+by\s+[^)]+\)$',
    r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s+[Pp]hoto(?:s)?$',
    r'^Arrels\s+[Pp]hoto(?:s)?\s+by\s+.*$',
    r'^[A-Z][a-z]+\s+[Pp]hoto(?:s)?\s+by\s+.*$',
]

KNOWN_SUBTITLES = [
    "Постійне прагнення до зручності",
    "Досвід як перевага ресторанів майбутнього",
    "Вплив та привабливість досвідів, керованих шефами",
    "Проектування для довголіття та гнучкості",
    "Більш навмисне майбутнє",
]


def clean_article_content(text: str) -> str:
    """
    Clean article content:
    - Remove photo credit lines
    - Format known subtitles with markdown bold
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    removed_count = 0
    
    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            cleaned_lines.append(line)
            continue
        
        is_photo_credit = False
        for pattern in PHOTO_CREDIT_PATTERNS:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                is_photo_credit = True
                print(f"  🗑️  Removed photo credit: '{line_stripped}'")
                removed_count += 1
                break
        
        if is_photo_credit:
            continue
        
        if re.search(r'[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,40}$', line_stripped):
            clean_line = re.sub(r',?\s*[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,40}$', '', line_stripped)
            if clean_line != line_stripped:
                print(f"  ✂️  Trimmed photo credit from line: '{line_stripped}' -> '{clean_line}'")
                removed_count += 1
                line_stripped = clean_line
        
        if re.match(r'^[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,40},?\s*', line_stripped):
            clean_line = re.sub(r'^[Pp]hoto(?:s)?\s+by\s+[A-Za-z\s\.\-\']{3,40},?\s*', '', line_stripped)
            if clean_line != line_stripped:
                print(f"  ✂️  Trimmed photo credit from start: '{line_stripped}' -> '{clean_line}'")
                removed_count += 1
                line_stripped = clean_line
        
        if line_stripped in KNOWN_SUBTITLES:
            if not line_stripped.startswith('**'):
                line_stripped = f"\n**{line_stripped}**\n"
                print(f"  📝 Formatted subtitle: {line_stripped.strip()}")
        
        if line_stripped:
            cleaned_lines.append(line_stripped)
    
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{4,}', '\n\n\n', result)
    
    print(f"  📊 Removed {removed_count} photo credit references")
    return result.strip()


def fix_article(db, article_id: int) -> bool:
    """Fix a specific article by ID"""
    article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
    
    if not article:
        print(f"❌ Article {article_id} not found")
        return False
    
    print(f"\n📰 Processing article {article_id}: {article.translated_title[:60] if article.translated_title else 'No title'}...")
    print(f"   Source: {article.source}")
    print(f"   Status: {article.status}")
    
    original_length = len(article.translated_text) if article.translated_text else 0
    
    cleaned_content = clean_article_content(article.translated_text)
    
    new_length = len(cleaned_content) if cleaned_content else 0
    
    if cleaned_content != article.translated_text:
        article.translated_text = cleaned_content
        db.commit()
        print(f"✅ Article {article_id} updated successfully!")
        print(f"   Content length: {original_length} -> {new_length} chars")
        return True
    else:
        print(f"ℹ️  Article {article_id} - no changes needed")
        return False


def fix_all_mrm_articles(db) -> int:
    """Fix all Modern Restaurant Management articles"""
    articles = db.query(ContentQueue).filter(
        ContentQueue.source == 'Modern Restaurant Management',
        ContentQueue.status.in_(['posted', 'approved', 'pending_approval'])
    ).all()
    
    print(f"\n🔍 Found {len(articles)} Modern Restaurant Management articles")
    
    fixed_count = 0
    for article in articles:
        if fix_article(db, article.id):
            fixed_count += 1
    
    return fixed_count


def main():
    parser = argparse.ArgumentParser(description='Fix MRM article formatting')
    parser.add_argument('--article-id', type=int, help='Specific article ID to fix')
    parser.add_argument('--all-mrm', action='store_true', help='Fix all MRM articles')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without saving')
    args = parser.parse_args()
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL environment variable not set")
        sys.exit(1)
    
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        if args.article_id:
            fix_article(db, args.article_id)
        elif args.all_mrm:
            fixed = fix_all_mrm_articles(db)
            print(f"\n✅ Fixed {fixed} articles total")
        else:
            article = db.query(ContentQueue).filter(
                ContentQueue.source == 'Modern Restaurant Management',
                ContentQueue.translated_title.ilike('%2026%дизайн%')
            ).first()
            
            if article:
                fix_article(db, article.id)
            else:
                print("❌ Target article not found. Use --article-id or --all-mrm")
                print("\nMRM articles in database:")
                mrm_articles = db.query(ContentQueue).filter(
                    ContentQueue.source == 'Modern Restaurant Management'
                ).all()
                for a in mrm_articles[:10]:
                    print(f"  ID {a.id}: {a.translated_title[:60] if a.translated_title else 'No title'}... ({a.status})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
