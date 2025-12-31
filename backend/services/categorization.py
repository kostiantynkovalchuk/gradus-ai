import anthropic
from os import getenv

def categorize_article(title: str, content: str) -> str:
    """
    Categorize article into: news, reviews, or trends
    
    Categories:
    - news: Market updates, company announcements, acquisitions, investments
    - reviews: Product reviews, tastings, awards, ratings, recommendations
    - trends: Industry forecasts, predictions, future outlook, year-ahead analysis
    """
    
    title_lower = (title or "").lower()
    content_lower = (content or "").lower()
    
    trend_keywords = ['2025', '2026', 'forecast', 'trend', 'future', 'prediction', 'outlook', 'next year', 'прогноз', 'тренд', 'майбутн']
    review_keywords = ['review', 'tasting', 'award', 'rating', 'flavor', 'taste', 'recommend', 'best', 'огляд', 'дегустац', 'нагород', 'смак']
    news_keywords = ['announces', 'launches', 'acquires', 'invests', 'opens', 'expands', 'partnership', 'оголош', 'запуск', 'придба', 'інвест', 'відкри', 'розшир']
    
    trend_score = sum(1 for kw in trend_keywords if kw in title_lower or kw in content_lower)
    review_score = sum(1 for kw in review_keywords if kw in title_lower or kw in content_lower)
    news_score = sum(1 for kw in news_keywords if kw in title_lower or kw in content_lower)
    
    scores = {'trends': trend_score, 'reviews': review_score, 'news': news_score}
    
    max_category = max(scores, key=scores.get)
    if scores[max_category] >= 2:
        return max_category
    
    try:
        client = anthropic.Anthropic(api_key=getenv("ANTHROPIC_API_KEY"))
        
        prompt = f"""Categorize this Ukrainian alcohol industry article into ONE category:

Title: {title}
Content: {content[:1000]}

Categories:
- news: Company announcements, market updates, acquisitions, investments, launches
- reviews: Product tastings, awards, ratings, recommendations, quality assessments  
- trends: Industry forecasts, predictions, future outlook, trend analysis

Respond with ONLY one word: news, reviews, or trends"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        
        category = message.content[0].text.strip().lower()
        
        if category in ['news', 'reviews', 'trends']:
            return category
            
    except Exception as e:
        print(f"Claude categorization failed: {e}")
    
    return 'news'
