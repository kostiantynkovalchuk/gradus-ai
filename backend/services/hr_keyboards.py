"""
HR Bot Telegram Keyboards
Interactive menu navigation for HR knowledge base
"""
import json
from typing import List, Dict, Optional


def create_main_menu_keyboard() -> Dict:
    """Main HR menu with 6 primary categories and distinct Ask Question button"""
    buttons = [
        [
            {"text": "📖 Про компанію", "callback_data": "hr_menu:about"},
            {"text": "🚀 Новачкам", "callback_data": "hr_menu:onboarding"}
        ],
        [
            {"text": "💼 Робочі питання", "callback_data": "hr_menu:work"},
            {"text": "💰 Зарплата", "callback_data": "hr_menu:salary"}
        ],
        [
            {"text": "🔧 Тех. підтримка", "callback_data": "hr_menu:tech"},
            {"text": "📞 Контакти", "callback_data": "hr_menu:contacts"}
        ],
        [
            {"text": "💬 Задати своє питання", "callback_data": "hr_ask"}
        ]
    ]
    
    return {"inline_keyboard": buttons}


def create_feedback_keyboard(sources: List[Dict] = None, log_id: int = None) -> Dict:
    """Keyboard with feedback and navigation, includes log_id for tracking"""
    log_suffix = f":{log_id}" if log_id else ""
    
    buttons = [
        [
            {"text": "👍 Корисно", "callback_data": f"hr_feedback:helpful{log_suffix}"},
            {"text": "👎 Не допомогло", "callback_data": f"hr_feedback:not_helpful{log_suffix}"}
        ]
    ]
    
    if sources:
        for idx, source in enumerate(sources[:2], 1):
            content_id = source.get('content_id', '')
            title = source.get('title', 'Документ')[:30]
            buttons.append([
                {"text": f"📄 {title}...", "callback_data": f"hr_content:{content_id}"}
            ])
    
    buttons.append([
        {"text": "🏠 Головне меню", "callback_data": "hr_menu:main"}
    ])
    
    return {"inline_keyboard": buttons}


def create_category_keyboard(category: str) -> Dict:
    """Create submenu for specific category"""
    
    SUBMENUS = {
        'onboarding': [
            ('📋 Документи для працевлаштування', 'hr_content:q1'),
            ('🔐 Корпоративний доступ', 'hr_content:q2'),
            ('📱 Перші кроки', 'hr_content:q3'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'salary': [
            ('💵 Строки виплати', 'hr_content:q4'),
            ('❓ Питання про нарахування', 'hr_content:q5'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'work': [
            ('🏖️ Відпустки', 'hr_content:q6'),
            ('🏥 Лікарняні', 'hr_content:q10'),
            ('🏠 Віддалена робота', 'hr_content:q11'),
            ('✈️ Відрядження', 'hr_content:q12'),
            ('🤝 Вирішення конфліктів', 'hr_content:q20'),
            ('📤 Звільнення', 'hr_content:q26'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'tech': [
            ('💻 Проблеми з ПК', 'hr_content:q17'),
            ('📱 КПК / Планшет', 'hr_content:q15'),
            ('📄 СЕД Бліц', 'hr_content:q8'),
            ('🌐 Віддалений робочий стіл', 'hr_content:q18'),
            ('🛠️ Канцтовари', 'hr_content:q19'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'about': [
            ('🎬 Загальна інформація', 'hr_content:video_overview'),
            ('🎬 Цінності компанії', 'hr_content:video_values'),
            ('🎬 Історія компанії', 'hr_content:video_history'),
            ('📊 Структура компанії', 'hr_content:section_4_structure'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'contacts': [
            ('📋 Список контактів', 'hr_content:section_appendix_22.'),
            ('🔙 Назад', 'hr_menu:main')
        ]
    }
    
    items = SUBMENUS.get(category, [])
    buttons = [[{"text": text, "callback_data": data}] for text, data in items]
    
    return {"inline_keyboard": buttons}


def create_back_keyboard() -> Dict:
    """Simple back to menu keyboard"""
    return {
        "inline_keyboard": [
            [{"text": "🏠 Головне меню", "callback_data": "hr_menu:main"}]
        ]
    }


CATEGORY_NAMES = {
    'about': 'Про компанію',
    'onboarding': 'Новачкам',
    'work': 'Робочі питання',
    'salary': 'Зарплата',
    'tech': 'Тех. підтримка',
    'contacts': 'Контакти'
}


def create_content_navigation_keyboard(parent_category: str = None) -> Dict:
    """
    Creates navigation buttons for content screens with Back + Main Menu
    
    Args:
        parent_category: Category to go back to (e.g., 'about', 'onboarding')
    
    Returns:
        Keyboard dict with Back and Main Menu buttons
    """
    row = []
    
    if parent_category and parent_category in CATEGORY_NAMES:
        row.append({
            "text": f"⬅️ {CATEGORY_NAMES[parent_category]}", 
            "callback_data": f"hr_menu:{parent_category}"
        })
    elif parent_category:
        row.append({
            "text": "⬅️ Назад", 
            "callback_data": f"hr_menu:{parent_category}"
        })
    
    row.append({
        "text": "🏠 Головне меню", 
        "callback_data": "hr_menu:main"
    })
    
    return {"inline_keyboard": [row]}


MENU_TITLES = {
    'about': '📖 Про компанію',
    'onboarding': '🚀 Інформація для новачків',
    'work': '💼 Робочі питання',
    'salary': '💰 Зарплата та виплати',
    'tech': '🔧 Технічна підтримка',
    'contacts': '📞 Контакти спеціалістів'
}


def split_long_message(text: str, max_length: int = 3800) -> List[str]:
    """Split long message into chunks"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    for paragraph in text.split('\n\n'):
        if len(current_chunk) + len(paragraph) + 2 <= max_length:
            current_chunk += paragraph + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = paragraph + "\n\n"
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text[:max_length]]
