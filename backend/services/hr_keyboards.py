"""
HR Bot Telegram Keyboards
Interactive menu navigation for HR knowledge base
"""
import json
from typing import List, Dict, Optional


def create_main_menu_keyboard() -> Dict:
    """Main HR menu with 7 primary categories and distinct Ask Question button"""
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
            {"text": "📄 Юридичні документи", "callback_data": "hr_menu:legal"}
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
        ],
        'legal': [
            ('🏢 Бест Брендс (ББ)', 'hr_menu:legal_bb'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'legal_bb': [
            ('📝 Маркетинг', 'hr_menu:legal_bb_marketing'),
            ('🚚 Логістика', 'hr_menu:legal_bb_logistics'),
            ('📦 Дистрибюція', 'hr_menu:legal_bb_distribution'),
            ('📥 Поставки/Закупівлі', 'hr_menu:legal_bb_supply'),
            ('📋 Додаткові угоди', 'hr_menu:legal_bb_additional'),
            ('🔙 Назад', 'hr_menu:legal')
        ],
        'legal_bb_marketing': [
            ('📄 Договір маркетингу', 'hr_doc:bb_001_marketing'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_bb_logistics': [
            ('📄 Логістика з паливним калькулятором', 'hr_doc:bb_101_logistics'),
            ('📄 Транспортне експедирування', 'hr_doc:bb_201_transport'),
            ('📄 Транспортне експедирування + банк. гарантія', 'hr_doc:bb_211_transport_bank'),
            ('📄 Договір перевезення', 'hr_doc:bb_301_shipping'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_bb_distribution': [
            ('📄 Дистрибюція - передоплата', 'hr_doc:bb_311_dist_prepay'),
            ('📄 Дистрибюція - відстрочка + банк. гарантія', 'hr_doc:bb_321_dist_delay_bank'),
            ('📄 Дистрибюція (представник) - відстрочка', 'hr_doc:bb_3201_dist_agent'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_bb_supply': [
            ('📄 Поставки - відстрочка', 'hr_doc:bb_401_supply_delay'),
            ('📄 Поставки - передоплата', 'hr_doc:bb_411_supply_prepay'),
            ('📄 Поставки - Вчасно', 'hr_doc:bb_4021_supply_vchasno'),
            ('📄 Поставки (представник) - відстрочка', 'hr_doc:bb_4201_supply_agent'),
            ('📄 Для закупівлі', 'hr_doc:bb_4011_purchase'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_bb_additional': [
            ('📄 ДУ поставки - зведена податк. накладна', 'hr_doc:bb_521_du_supply'),
            ('📄 ДУ M.E.DOC', 'hr_doc:bb_601_du_medoc'),
            ('📄 ДУ Вчасно', 'hr_doc:bb_611_du_vchasno'),
            ('🔙 Назад', 'hr_menu:legal_bb')
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
    'contacts': 'Контакти',
    'legal': 'Юридичні документи',
    'legal_bb': 'Бест Брендс',
    'legal_bb_marketing': 'Маркетинг',
    'legal_bb_logistics': 'Логістика',
    'legal_bb_distribution': 'Дистрибюція',
    'legal_bb_supply': 'Поставки/Закупівлі',
    'legal_bb_additional': 'Додаткові угоди'
}


LEGAL_CONTRACTS = {
    'bb_001_marketing': {
        'name': 'Договір маркетингу ББ 2026',
        'file': 'best_brands/001_Договір_маркетингу_ББ_2026.doc'
    },
    'bb_101_logistics': {
        'name': 'Логістика з паливним калькулятором 2026',
        'file': 'best_brands/101_Типовий_логістика_з_пал_калькул._2026_1769087829765.doc'
    },
    'bb_201_transport': {
        'name': 'Транспортне експедирування ББ 2026',
        'file': 'best_brands/201_Транспортне_експедирування_ББ_2026.docx'
    },
    'bb_211_transport_bank': {
        'name': 'Транспортне експедирування + банк. гарантія 2026',
        'file': 'best_brands/211_Транспортне_експедирування_ББ+_банк_гарантія_2026.docx'
    },
    'bb_301_shipping': {
        'name': 'Договір перевезення ББ 2026',
        'file': 'best_brands/301_Договір_перевезення_ББ_2026.docx'
    },
    'bb_311_dist_prepay': {
        'name': 'Дистрибюція - передоплата 2026',
        'file': 'best_brands/311_Типовий_Дистрибюція_ББ_-_передоплата_2026.doc'
    },
    'bb_321_dist_delay_bank': {
        'name': 'Дистрибюція - відстрочка + банк. гарантія 2026',
        'file': 'best_brands/321_Типовий_Дистрибюція_ББ_-_відсрочка_+_банк._гарантія_2026.doc'
    },
    'bb_3201_dist_agent': {
        'name': 'Дистрибюція (представник) - відстрочка 2026',
        'file': 'best_brands/3201_Типовий_Дистрибуція_(представник)_ББ_-_відстрочяка_+_бан.doc'
    },
    'bb_401_supply_delay': {
        'name': 'Поставки - відстрочка 2026',
        'file': 'best_brands/401_Типовий_Поставки_ББ_2026_-_отсрочка.doc'
    },
    'bb_411_supply_prepay': {
        'name': 'Поставки - передоплата 2026',
        'file': 'best_brands/411_Типовий_Поставки_ББ_-_передоплата_2026.doc'
    },
    'bb_4021_supply_vchasno': {
        'name': 'Поставки - Вчасно 2026',
        'file': 'best_brands/4021_Типовой_Поставки_ББ_-_отсрочкаВчасно_2026.doc'
    },
    'bb_4201_supply_agent': {
        'name': 'Поставки (представник) - відстрочка 2026',
        'file': 'best_brands/4201_Типовой_Поставки_ББ_(представник)_-_отсрочка_2026.doc'
    },
    'bb_4011_purchase': {
        'name': 'Для закупівлі ББ 2026',
        'file': 'best_brands/4011_Типовий_для_закупівлі_ББ_2026.doc'
    },
    'bb_521_du_supply': {
        'name': 'ДУ поставки - зведена податкова накладна 2026',
        'file': 'best_brands/521_Додаткова_угода_поставки_зведена_податкова_накладна_ББ_20.docx'
    },
    'bb_601_du_medoc': {
        'name': 'ДУ M.E.DOC ББ 2026',
        'file': 'best_brands/601_Типова_ДУ_-_M.E.DOC_ББ_2026.doc'
    },
    'bb_611_du_vchasno': {
        'name': 'ДУ Вчасно ББ 2026',
        'file': 'best_brands/611_Типова_ДУ_-_Вчасно_ББ_2026.doc'
    }
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
