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
        # Vodka brands
        'greenday': 'greenday vodka горілка водка premium Торговий Дім АВ',
        'грінді': 'greenday vodka горілка водка premium Торговий Дім АВ',
        'green day': 'greenday vodka горілка vodka premium Торговий Дім АВ',
        'грін дей': 'greenday vodka горілка водка premium Торговий Дім АВ',
        'helsinki': 'helsinki vodka горілка водка premium scandinavian Торговий Дім АВ',
        'хельсінкі': 'helsinki vodka горілка водка premium scandinavian Торговий Дім АВ',
        'ukrainka': 'ukrainka vodka горілка водка traditional ukrainian Торговий Дім АВ',
        'українка': 'ukrainka vodka горілка водка traditional ukrainian Торговий Дім АВ',
        
        # Cognac brands
        'довбуш': 'dovbush cognac коньяк spirits Торговий Дім АВ',
        'dovbush': 'dovbush cognac коньяк spirits Торговий Дім АВ',
        'adjari': 'adjari cognac wine коньяк вино georgian Торговий Дім АВ',
        'аджарі': 'adjari cognac wine коньяк вино georgian Торговий Дім АВ',
        
        # Soju brand
        'funju': 'funju soju соджу korean Торговий Дім АВ',
        'фунжу': 'funju soju соджу korean Торговий Дім АВ',
        'фунджу': 'funju soju соджу korean Торговий Дім АВ',
        
        # Wine brands
        'villa': 'villa wine вино villa.ua ukrainian Торговий Дім АВ',
        'вілла': 'villa wine вино villa.ua ukrainian Торговий Дім АВ',
        'villa.ua': 'villa wine вино Торговий Дім АВ',
        'kristi valley': 'kristi valley wine вино french Торговий Дім АВ',
        'крісті': 'kristi valley wine вино french Торговий Дім АВ',
        'didi lari': 'didi lari wine вино georgian Торговий Дім АВ',
        'діді ларі': 'didi lari wine вино georgian Торговий Дім АВ',
        'wineviaggio': 'wineviaggio wine вино italian Торговий Дім АВ',
        
        # Company name recognition
        'торговий дім ав': 'Торговий Дім АВ ТДАВ бренди портфоліо vodka wine cognac soju',
        'тдав': 'Торговий Дім АВ ТДАВ бренди портфоліо vodka wine cognac soju',
        'td av': 'Торговий Дім АВ ТДАВ бренди портфоліо vodka wine cognac soju',
        'trading house av': 'Торговий Дім АВ ТДАВ бренди портфоліо vodka wine cognac soju',
        
        # Product queries
        'які бренди': 'Торговий Дім АВ портфоліо бренди GREENDAY HELSINKI UKRAINKA VILLA FUNJU DOVBUSH ADJARI',
        'яка продукція': 'Торговий Дім АВ портфоліо бренди продукція асортимент vodka wine cognac soju',
        'асортимент': 'Торговий Дім АВ портфоліо бренди продукція асортимент',
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
