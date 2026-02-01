#!/usr/bin/env python3
"""Manually refetch images for specific articles with non-congruent imagery"""

import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from services.unsplash_service import UnsplashService

DATABASE_URL = os.getenv('DATABASE_URL')

ARTICLE_IDS_TO_REFETCH = [
    325,  # Grey Goose Berry Rouge
    327,  # Звіт про бренди: Горілка
    333,  # Mahou San Miguel
    342,  # Троєщина супермаркети
    346,  # PepsiCo Іспанія
]

def refetch_article_images():
    """Refetch images using AI-powered semantic query generation"""
    
    unsplash = UnsplashService()
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    
    try:
        for article_id in ARTICLE_IDS_TO_REFETCH:
            print(f"\n{'='*60}")
            print(f"Processing Article ID: {article_id}")
            
            cur.execute(
                "SELECT id, translated_title, translated_text, image_photographer FROM content_queue WHERE id = %s",
                (article_id,)
            )
            row = cur.fetchone()
            
            if not row:
                print(f"Article {article_id} not found!")
                continue
            
            title = row['translated_title'] or ""
            content = row['translated_text'] or ""
            current_photographer = row['image_photographer']
            
            print(f"Title: {title[:60]}...")
            print(f"Current photographer: {current_photographer or 'None'}")
            
            queries = unsplash.generate_ai_queries(title, content)
            if not queries:
                queries = unsplash.extract_smart_keywords(title, content)
            
            print(f"Generated queries: {queries[:3]}...")
            
            images = unsplash.fetch_unsplash_images(queries, limit=3)
            
            if images:
                images.sort(key=lambda x: x.get('aesthetic_score', 0), reverse=True)
                best_image = images[0]
                
                print(f"\nNew Image Selected:")
                print(f"  Photographer: {best_image['photographer_name']}")
                print(f"  Aesthetic Score: {best_image.get('aesthetic_score', 'N/A')}")
                print(f"  Query Used: {best_image.get('query_used', 'N/A')}")
                print(f"  Likes: {best_image.get('likes', 0)}")
                
                cur.execute(
                    """
                        UPDATE content_queue SET 
                            image_url = %s,
                            image_photographer = %s,
                            image_credit = %s,
                            image_credit_url = %s,
                            unsplash_image_id = %s
                        WHERE id = %s
                    """,
                    (
                        best_image['url'],
                        best_image['photographer_name'],
                        f"Photo by {best_image['photographer_name']} on Unsplash",
                        best_image['photographer_url'],
                        best_image['id'],
                        article_id
                    )
                )
                conn.commit()
                
                unsplash.trigger_download(best_image['download_url'])
                
                print(f"Updated successfully!")
                
            else:
                print(f"No suitable images found")
            
            time.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"Refetch complete!")
        
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    refetch_article_images()
