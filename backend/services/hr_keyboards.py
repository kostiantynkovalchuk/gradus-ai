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
            {"text": "📄 Юр. документи", "callback_data": "hr_menu:legal"},
            {"text": "📚 Навчання", "callback_data": "hr_menu:training"}
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
            ('🪑 Основні фонди', 'hr_content:q20'),
            ('🤝 Вирішення конфліктів', 'hr_content:q19'),
            ('📤 Звільнення', 'hr_content:q26'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'tech': [
            ('💻 Проблеми з ПК', 'hr_content:q17'),
            ('📱 КПК / Планшет', 'hr_content:q15'),
            ('📄 СЕД Бліц', 'hr_content:q8'),
            ('🌐 Віддалений робочий стіл', 'hr_content:q18'),
            ('🛠️ Канцтовари', 'hr_content:q21'),
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
            ('📞 Контакти ЦО', 'hr_content:appendix_22_contacts'),
            ('🔙 Назад', 'hr_menu:main')
        ],
        'legal': [
            ('🏢 Бест Брендс (ББ)', 'hr_menu:legal_bb'),
            ('🏭 Торговий Дім АВ', 'hr_menu:legal_tdav'),
            ('🥐 Світ Бейкерс', 'hr_menu:legal_sb'),
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
            ('📄 Поставки (представник) - передоплата', 'hr_doc:bb_421_supply_agent_prepay'),
            ('📄 Для закупівлі', 'hr_doc:bb_4011_purchase'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_bb_additional': [
            ('📄 ДУ дистрибюція - зведена податк. накладна', 'hr_doc:bb_511_du_dist'),
            ('📄 ДУ поставки - зведена податк. накладна', 'hr_doc:bb_521_du_supply'),
            ('📄 ДУ M.E.DOC', 'hr_doc:bb_601_du_medoc'),
            ('📄 ДУ Вчасно', 'hr_doc:bb_611_du_vchasno'),
            ('📄 ДУ Пролонгація', 'hr_doc:bb_621_du_prolongation'),
            ('🔙 Назад', 'hr_menu:legal_bb')
        ],
        'legal_tdav': [
            ('📝 Маркетинг', 'hr_menu:legal_tdav_marketing'),
            ('🚚 Логістика', 'hr_menu:legal_tdav_logistics'),
            ('📦 Дистрибюція', 'hr_menu:legal_tdav_distribution'),
            ('📥 Поставки/Закупівлі', 'hr_menu:legal_tdav_supply'),
            ('📋 Додаткові угоди', 'hr_menu:legal_tdav_additional'),
            ('🔙 Назад', 'hr_menu:legal')
        ],
        'legal_tdav_marketing': [
            ('📄 Договір маркетингу', 'hr_doc:tdav_002_marketing'),
            ('🔙 Назад', 'hr_menu:legal_tdav')
        ],
        'legal_tdav_logistics': [
            ('📄 Логістика з паливним калькулятором', 'hr_doc:tdav_102_logistics'),
            ('📄 Транспортне експедирування', 'hr_doc:tdav_202_transport'),
            ('📄 Транспортне експедирування + банк. гарантія', 'hr_doc:tdav_222_transport_bank'),
            ('📄 Договір перевезення', 'hr_doc:tdav_302_shipping'),
            ('🔙 Назад', 'hr_menu:legal_tdav')
        ],
        'legal_tdav_distribution': [
            ('📄 Дистрибюція - передоплата', 'hr_doc:tdav_312_dist_prepay'),
            ('📄 Дистрибюція - відстрочка + банк. гарантія', 'hr_doc:tdav_322_dist_delay_bank'),
            ('📄 Дистрибюція (представник) - відстрочка', 'hr_doc:tdav_3202_dist_agent'),
            ('🔙 Назад', 'hr_menu:legal_tdav')
        ],
        'legal_tdav_supply': [
            ('📄 Поставки - відстрочка', 'hr_doc:tdav_402_supply_delay'),
            ('📄 Поставки - передоплата', 'hr_doc:tdav_412_supply_prepay'),
            ('📄 Поставки - Вчасно', 'hr_doc:tdav_4022_supply_vchasno'),
            ('📄 Поставки (представник) - відстрочка', 'hr_doc:tdav_4202_supply_agent'),
            ('📄 Поставки (представник) - передоплата', 'hr_doc:tdav_422_supply_agent_prepay'),
            ('📄 Для закупівлі', 'hr_doc:tdav_4012_purchase'),
            ('🔙 Назад', 'hr_menu:legal_tdav')
        ],
        'legal_tdav_additional': [
            ('📄 ДУ дистрибюція - зведена податк. накладна', 'hr_doc:tdav_512_du_dist'),
            ('📄 ДУ поставки - зведена податк. накладна', 'hr_doc:tdav_522_du_supply'),
            ('📄 ДУ M.E.DOC', 'hr_doc:tdav_602_du_medoc'),
            ('📄 ДУ Вчасно', 'hr_doc:tdav_612_du_vchasno'),
            ('📄 ДУ Пролонгація', 'hr_doc:tdav_622_du_prolongation'),
            ('🔙 Назад', 'hr_menu:legal_tdav')
        ],
        'legal_sb': [
            ('📝 Маркетинг', 'hr_menu:legal_sb_marketing'),
            ('🚚 Логістика', 'hr_menu:legal_sb_logistics'),
            ('📥 Поставки/Закупівлі', 'hr_menu:legal_sb_supply'),
            ('📋 Додаткові угоди', 'hr_menu:legal_sb_additional'),
            ('🔙 Назад', 'hr_menu:legal')
        ],
        'legal_sb_marketing': [
            ('📄 Договір маркетингу', 'hr_doc:sb_701_marketing'),
            ('🔙 Назад', 'hr_menu:legal_sb')
        ],
        'legal_sb_logistics': [
            ('📄 Договір логістики', 'hr_doc:sb_702_logistics'),
            ('🔙 Назад', 'hr_menu:legal_sb')
        ],
        'legal_sb_supply': [
            ('📄 Поставки - відстрочка', 'hr_doc:sb_705_supply_delay'),
            ('📄 Поставки - автопролонгація', 'hr_doc:sb_706_supply_auto'),
            ('🔙 Назад', 'hr_menu:legal_sb')
        ],
        'legal_sb_additional': [
            ('📄 Звіт про надані послуги', 'hr_doc:sb_703_report'),
            ('📄 ДУ Ретро-бонус', 'hr_doc:sb_704_du_retrobonus'),
            ('🔙 Назад', 'hr_menu:legal_sb')
        ]
    }
    
    items = SUBMENUS.get(category, [])
    if not items:
        return {"inline_keyboard": []}

    back_btn = None
    content_items = []
    for text, data in items:
        if text.startswith('🔙'):
            back_btn = {"text": text, "callback_data": data}
        else:
            content_items.append({"text": text, "callback_data": data})

    buttons = []
    for i in range(0, len(content_items), 2):
        if i + 1 < len(content_items):
            buttons.append([content_items[i], content_items[i + 1]])
        else:
            buttons.append([content_items[i]])

    if back_btn:
        buttons.append([back_btn])

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
    'legal_bb_additional': 'Додаткові угоди',
    'legal_tdav': 'Торговий Дім АВ',
    'legal_tdav_marketing': 'Маркетинг',
    'legal_tdav_logistics': 'Логістика',
    'legal_tdav_distribution': 'Дистрибюція',
    'legal_tdav_supply': 'Поставки/Закупівлі',
    'legal_tdav_additional': 'Додаткові угоди',
    'legal_sb': 'Світ Бейкерс',
    'legal_sb_marketing': 'Маркетинг',
    'legal_sb_logistics': 'Логістика',
    'legal_sb_supply': 'Поставки/Закупівлі',
    'legal_sb_additional': 'Додаткові угоди'
}


LEGAL_CONTRACTS = {
    'bb_001_marketing': {
        'name': 'Договір маркетингу ББ 2026',
        'file': 'best_brands/001_Договір_маркетингу_ББ_2026.doc'
    },
    'bb_101_logistics': {
        'name': 'Логістика з паливним калькулятором 2026',
        'file': 'best_brands/101_Типовий_логістика_з_пал_калькул._2026.doc'
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
    },
    'bb_421_supply_agent_prepay': {
        'name': 'Поставки (представник) - передоплата 2026',
        'file': 'best_brands/421_Типовийй_Поставки_(представник)_-_передоплата_2026.doc'
    },
    'bb_511_du_dist': {
        'name': 'ДУ Дистрибюція - зведена податкова накладна 2026',
        'file': 'best_brands/511_Додаткова_угода_Дистрибюція_зведена_податкова_накладна_20.docx'
    },
    'bb_621_du_prolongation': {
        'name': 'ДУ Пролонгація 2026',
        'file': 'best_brands/621_ТИПОВА_ДУ_пролонгація_2026.docx'
    },
    # ТД АВ (Торговий Дім АВ) contracts
    'tdav_002_marketing': {
        'name': 'Договір маркетингу ТД АВ 2026',
        'file': 'td_av/002_Договір_маркетингу_ТД_АВ_2026.doc'
    },
    'tdav_102_logistics': {
        'name': 'Логістика з паливним калькулятором ТД АВ 2026',
        'file': 'td_av/102_Типовий_логістика_ТД_АВ_з_пал_калькул._2026.doc'
    },
    'tdav_202_transport': {
        'name': 'Транспортне експедирування ТД АВ 2026',
        'file': 'td_av/202_Транспортне_експедирування_ТД_АВ_2026.docx'
    },
    'tdav_222_transport_bank': {
        'name': 'Транспортне експедирування + банк. гарантія ТД АВ 2026',
        'file': 'td_av/222_Транспортне_експедирування_ТД_АВ_+_банк_гарантія_2026.docx'
    },
    'tdav_302_shipping': {
        'name': 'Договір перевезення ТД АВ 2026',
        'file': 'td_av/302_Договір_перевезення_ТД_АВ_2026.docx'
    },
    'tdav_312_dist_prepay': {
        'name': 'Дистрибюція - передоплата ТД АВ 2026',
        'file': 'td_av/312_Типовий_Дистрибюція_ТД_АВ_-_передоплата_2026.doc'
    },
    'tdav_322_dist_delay_bank': {
        'name': 'Дистрибюція - відстрочка + банк. гарантія ТД АВ 2026',
        'file': 'td_av/322_Типовий_Дистрибюція_ТД_АВ_-_відсрочка_+_банк._гарантія_20.doc'
    },
    'tdav_3202_dist_agent': {
        'name': 'Дистрибюція (представник) - відстрочка ТД АВ 2026',
        'file': 'td_av/3202_Типовий_Дистрибюція_ТД_АВ_(представник)_-_відсрочка_+_ба.doc'
    },
    'tdav_402_supply_delay': {
        'name': 'Поставки - відстрочка ТД АВ 2026',
        'file': 'td_av/402_Типовий_Поставки_ТД_АВ_2026_-_отсрочка.doc'
    },
    'tdav_412_supply_prepay': {
        'name': 'Поставки - передоплата ТД АВ 2026',
        'file': 'td_av/412_Типовий_Поставки_ТД_АВ_-_передоплата_2026.doc'
    },
    'tdav_4022_supply_vchasno': {
        'name': 'Поставки - Вчасно ТД АВ 2026',
        'file': 'td_av/4022_Типовой_Поставки_ТД_АВ_-_отсрочкаВчасно_2026.doc'
    },
    'tdav_4202_supply_agent': {
        'name': 'Поставки (представник) - відстрочка ТД АВ 2026',
        'file': 'td_av/4202_Типовой_Поставки_ТД_АВ_(представник)_-_отсрочка_2026.doc'
    },
    'tdav_422_supply_agent_prepay': {
        'name': 'Поставки (представник) - передоплата ТД АВ 2026',
        'file': 'td_av/422_Типовий_Поставки_ТД_АВ_(представник)_-_передоплата_2026.doc'
    },
    'tdav_4012_purchase': {
        'name': 'Для закупівлі ТД АВ 2026',
        'file': 'td_av/4012_Типовий_для_закупівлі_ТД_АВ_2026.doc'
    },
    'tdav_512_du_dist': {
        'name': 'ДУ Дистрибюція - зведена податкова накладна ТД АВ 2026',
        'file': 'td_av/512_Додаткова_угода_Дистрибюція_зведена_податкова_накладна_20.docx'
    },
    'tdav_522_du_supply': {
        'name': 'ДУ Поставки - зведена податкова накладна ТД АВ 2026',
        'file': 'td_av/522_Додаткова_угода_поставки_зведена_податкова_накладна_ТД_АВ.docx'
    },
    'tdav_602_du_medoc': {
        'name': 'ДУ M.E.DOC ТД АВ 2026',
        'file': 'td_av/602_Типова_ДУ_-_M.E.DOC_ТД_АВ_2026.doc'
    },
    'tdav_612_du_vchasno': {
        'name': 'ДУ Вчасно ТД АВ 2026',
        'file': 'td_av/612_Типова_ДУ_-_Вчасно_ТД_АВ_2026.doc'
    },
    'tdav_622_du_prolongation': {
        'name': 'ДУ Пролонгація ТД АВ 2026',
        'file': 'td_av/622_ТИПОВА_ДУ_пролонгація_2026.docx'
    },
    # Світ Бейкерс contracts
    'sb_701_marketing': {
        'name': 'Договір маркетингу Світ Бейкерс',
        'file': 'svit_bakers/701_Типовий_договір_маркетингу_Світ_Бейкерс.doc'
    },
    'sb_702_logistics': {
        'name': 'Договір логістики Світ Бейкерс',
        'file': 'svit_bakers/702_Договір_логистики_Світ_Бейкерс_типовий_12_23.doc'
    },
    'sb_703_report': {
        'name': 'Звіт про надані послуги Світ Бейкерс',
        'file': 'svit_bakers/703_Звіт_про_надані_послуги_Світ_Бейкерс.doc'
    },
    'sb_704_du_retrobonus': {
        'name': 'ДУ Ретро-бонус Світ Бейкерс',
        'file': 'svit_bakers/704_Типова_ДУ_ретро-бонус.docx'
    },
    'sb_705_supply_delay': {
        'name': 'Поставки - відстрочка Світ Бейкерс 2024',
        'file': 'svit_bakers/705_Типовой_Поставки_(закупівля)_Світ_Бейкерс_2024_-_отсрочк.doc'
    },
    'sb_706_supply_auto': {
        'name': 'Поставки - автопролонгація Світ Бейкерс 2025',
        'file': 'svit_bakers/706_Типовой_Поставки_(закупівля)_Світ_Бейкерс_2025_та_автопр.doc'
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
    'contacts': '📞 Контакти спеціалістів',
    'legal': '📄 Юридичні документи',
    'legal_bb': '🏢 Бест Брендс - Договори',
    'legal_bb_marketing': '📝 Маркетинг',
    'legal_bb_logistics': '🚚 Логістика',
    'legal_bb_distribution': '📦 Дистрибюція',
    'legal_bb_supply': '📥 Поставки/Закупівлі',
    'legal_bb_additional': '📋 Додаткові угоди',
    'legal_tdav': '🏭 Торговий Дім АВ - Договори',
    'legal_tdav_marketing': '📝 Маркетинг',
    'legal_tdav_logistics': '🚚 Логістика',
    'legal_tdav_distribution': '📦 Дистрибюція',
    'legal_tdav_supply': '📥 Поставки/Закупівлі',
    'legal_tdav_additional': '📋 Додаткові угоди',
    'legal_sb': '🥐 Світ Бейкерс - Договори',
    'legal_sb_marketing': '📝 Маркетинг',
    'legal_sb_logistics': '🚚 Логістика',
    'legal_sb_supply': '📥 Поставки/Закупівлі',
    'legal_sb_additional': '📋 Додаткові угоди'
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
