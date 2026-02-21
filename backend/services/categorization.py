import anthropic
from os import getenv
from config.models import CLAUDE_MODEL_CONTENT

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

    trend_keywords = [
        'forecast', 'trend', 'prediction', 'outlook', 'next year',
        'consumer behavior', 'market shift', 'industry direction',
        'what to expect', 'year ahead', 'looking ahead', 'on the rise',
        'set to grow', 'poised to', 'projected',
        'тренд', 'прогноз', 'майбутнє', 'перспектив',
        'тенденці', 'розвиток ринку', 'очікуван'
    ]

    trend_title_keywords = [
        '2025', '2026', '2027', 'future', 'emerging',
        'зростання', 'напрямок'
    ]

    review_keywords = [
        'review', 'tasting', 'award', 'rating', 'flavor', 'palate', 'aroma',
        'distillery visit', 'blind tasting', 'nose', 'sip',
        'medal', 'gold medal', 'silver medal', 'bronze medal', 'winner', 'competition',
        'огляд', 'дегустація', 'нагорода', 'рейтинг', 'аромат',
        'рекомендуємо', 'переможець', 'медаль'
    ]

    review_title_keywords = [
        'review', 'tasting', 'award', 'rated', 'ranked',
        'огляд', 'дегустація', 'нагорода'
    ]

    news_keywords = [
        'announces', 'launches', 'acquires', 'invests', 'opens', 'expands',
        'partnership', 'deal', 'merger', 'acquisition', 'appointed', 'ceo',
        'revenue', 'profit', 'sales', 'quarterly', 'fiscal',
        'оголош', 'запуск', 'придба', 'інвест', 'відкри', 'розшир',
        'угода', 'призначен', 'виручка', 'прибуток'
    ]

    title_weight = 3
    content_weight = 1

    def score_category(keywords, title_only_keywords, text_title, text_content):
        score = 0
        for kw in keywords:
            if kw in text_title:
                score += title_weight
            elif kw in text_content:
                score += content_weight
        for kw in title_only_keywords:
            if kw in text_title:
                score += title_weight
        return score

    trend_score = score_category(trend_keywords, trend_title_keywords, title_lower, content_lower)
    review_score = score_category(review_keywords, review_title_keywords, title_lower, content_lower)
    news_score = score_category(news_keywords, [], title_lower, content_lower)
    
    scores = {'trends': trend_score, 'reviews': review_score, 'news': news_score}
    
    max_category = max(scores, key=scores.get)
    max_score = scores[max_category]

    if max_score >= 2:
        return max_category
    
    if max_score == 1 and max_category != 'news':
        second_best = sorted(scores.values(), reverse=True)[1]
        if second_best == 0:
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
            model=CLAUDE_MODEL_CONTENT,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        
        category = message.content[0].text.strip().lower()
        
        if category in ['news', 'reviews', 'trends']:
            return category
            
    except Exception as e:
        print(f"Claude categorization failed: {e}")
    
    return 'news'
