"""
Query expansion service to improve RAG retrieval for Торговий Дім АВ products.
Expands brand names with category keywords to match stored documents.
"""

import logging

logger = logging.getLogger(__name__)


def expand_brand_query(user_message: str) -> str:
    """
    Expand brand name queries with product category keywords.
    
    This improves RAG retrieval when users mention brand names without 
    specifying the product category (e.g., "greenday" without "vodka").
    
    Examples:
    - "розкажи про greenday" → "розкажи про greenday (greenday vodka горілка водка)"
    - "що таке довбуш" → "що таке довбуш (dovbush spirits горілка настоянка)"
    
    Args:
        user_message: Original user query
        
    Returns:
        Expanded query for better RAG matching (or original if no expansion needed)
    """
    message_lower = user_message.lower().strip()
    
    brand_expansions = {
        'greenday': 'greenday vodka горілка водка premium',
        'грінді': 'greenday vodka горілка водка premium',
        'green day': 'greenday vodka горілка vodka premium',
        'грін дей': 'greenday vodka горілка водка premium',
        
        'довбуш': 'dovbush spirits горілка настоянка liqueur traditional',
        'dovbush': 'dovbush spirits горілка настоянка liqueur traditional',
        
        'funju': 'funju cocktails коктейлі ready-to-drink RTD',
        'фунжу': 'funju cocktails коктейлі ready-to-drink RTD',
        'фунджу': 'funju cocktails коктейлі ready-to-drink RTD',
        
        'villa': 'villa wine вино villa.ua',
        'вілла': 'villa wine вино villa.ua',
        'villa.ua': 'villa wine вино',
    }
    
    category_keywords = [
        'vodka', 'водка', 'горілка', 'горилка',
        'wine', 'вино', 'вина',
        'spirits', 'спірт', 'алкоголь',
        'коктейлі', 'коктейль', 'cocktails', 'cocktail',
        'настоянка', 'liqueur', 'лікер',
        'rtd', 'ready-to-drink',
    ]
    
    for brand, expansion in brand_expansions.items():
        if brand in message_lower:
            has_category = any(keyword in message_lower for keyword in category_keywords)
            
            if not has_category:
                expanded = f"{user_message} ({expansion})"
                logger.debug(f"Query expanded: '{user_message}' → '{expanded}'")
                return expanded
    
    return user_message
