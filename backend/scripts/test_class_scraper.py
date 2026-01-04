#!/usr/bin/env python3
"""
Test script for Class Magazine scraper
Usage: python scripts/test_class_scraper.py
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

from services.scrapers.class_magazine import ClassMagazineScraper


def test_scraper():
    print("=" * 60)
    print("Testing Class Magazine Scraper")
    print("=" * 60)
    
    scraper = ClassMagazineScraper()
    
    print(f"\nSource: {scraper.source_name}")
    print(f"Language: {scraper.language}")
    print(f"Needs translation: {scraper.needs_translation}")
    print(f"Rate limit delay: {scraper.get_rate_limit_delay()}s")
    
    print("\n" + "-" * 60)
    print("Scraping 2 articles...")
    print("-" * 60)
    
    articles = scraper.scrape_articles(limit=2)
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {len(articles)} articles scraped")
    print("=" * 60)
    
    for i, article in enumerate(articles, 1):
        print(f"\n{i}. {article.title}")
        print(f"   URL: {article.url}")
        print(f"   Author: {article.author or 'N/A'}")
        print(f"   Published: {article.published_at or 'N/A'}")
        print(f"   Content length: {len(article.content)} chars")
        print(f"   Tags: {article.tags}")
        print(f"\n   Preview (first 200 chars):")
        print(f"   {article.content[:200]}...")
    
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    
    errors = []
    warnings = []
    
    if len(articles) == 0:
        errors.append("No articles scraped!")
    
    for article in articles:
        if not article.title:
            errors.append(f"Missing title for article")
        if not article.url:
            errors.append(f"Missing URL for article")
        if not article.content:
            errors.append(f"Missing content for {article.title}")
        if len(article.content) < 500:
            warnings.append(f"Short content ({len(article.content)} chars) for {article.title}")
        if "PRINT" in article.content[:50] and "DIGITAL" in article.content[:50]:
            errors.append(f"Header garbage in content for {article.title}")
    
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\nNo errors found.")
    
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")
    
    success = len(errors) == 0 and len(articles) > 0
    print("\n" + "=" * 60)
    if success:
        print("TEST PASSED")
    else:
        print("TEST FAILED")
    print("=" * 60)
    
    return success


if __name__ == "__main__":
    success = test_scraper()
    sys.exit(0 if success else 1)
