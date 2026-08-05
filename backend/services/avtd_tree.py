"""
Shared AVTD knowledge-tree content and keyboard factories.

This module is bot-agnostic: no env access, no DB, no Telegram imports.
Callers supply a ``prefix`` string so the same factories can produce
callback_data for different bots without duplication.

With ``prefix='ax_'`` the output is byte-identical to the original
hardcoded keyboards in alex_avtd_webhook.py.
"""
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Leaf-answer content keyed by SUFFIX (the part after the bot-specific prefix,
# e.g. 'kpi_sc' not 'ax_kpi_sc').  Do not edit answer text or whitespace.
# ---------------------------------------------------------------------------

PRESETS: Dict[str, str] = {
    "client_terms": (
        "📋 *Умови співпраці з клієнтом*\n\n"
        "Доступні в двох місцях:\n"
        "• Сайт mobiletrade → Довідник → Контрагенти → Угоди\n"
        "• Blitz Trade → Маршрут → Торгова точка → Картка клієнта\n\n"
        "🔗 mobiletrade.tdav.net.ua/buyers"
    ),
    "client_debt": (
        "💰 *Дебіторська заборгованість*\n\n"
        "• Blitz Trade → Маршрут → Торгова точка (загальна ДЗ)\n"
        "• Сайт mobiletrade → Довідник → Контрагенти → Деталізація до накладної\n\n"
        "Штраф за ДЗ: `[ПДЗ – 10%×ДЗ] × 3%`\n\n"
        "🔗 mobiletrade.tdav.net.ua/buyers"
    ),
    "client_info": (
        "🏪 *Інформація по клієнту*\n\n"
        "Сайт mobiletrade → Довідник → Контрагенти:\n"
        "Основні, Торгові точки, Угоди, Маркетингові виплати,\n"
        "Замовлення, Відвантаження, Оплати, Мерчендайзинг, Фотозвіти\n\n"
        "Документи: mobiletrade → Документи → (Журнал, Замовлення, Накладні, Фотозвіт...)\n\n"
        "🔗 mobiletrade.tdav.net.ua/buyers"
    ),
    "kpi_photo": (
        "❓ *Чому не зарахувався фотозвіт?*\n\n"
        "Причини для МЧ, ДП, ДПХ:\n"
        "• ФЗ не синхронізовано в базу\n"
        "• Невірно вибрано результат візиту\n"
        "• Результат візиту не відповідає типу трт (МЧ на HoReCa — не зараховується)\n"
        "• МЧ2 — між візитами пройшло менше 5 днів\n\n"
        "Причини для СЦ, АКБ, ОА:\n"
        "• Випадіння товару при проведенні замовлення\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• Самовивіз не враховується для СЦ\n\n"
        "Виправити результат візиту можна на сайті mobiletrade → Документи → Фотозвіти (протягом 3 робочих днів)\n\n"
        "🔗 mobiletrade.tdav.net.ua/doc-jrn/photo-reports"
    ),
    "kpi_bonus": (
        "💵 *Бонус / штраф за ДЗ*\n\n"
        "Формула штрафу: `[ПДЗ – 10%×ДЗ] × 3%`\n\n"
        "Де дивитися виконання KPI:\n"
        "• Blitz Trade → Головна → Інфо\n"
        "• Blitz Trade → Маршрут → Торгова точка → Показники\n"
        "• Сайт mobiletrade → Головна → Дашборд\n"
        "• Звіти: Аналітика, ПП, Виконання СЦ"
    ),
    "kpi_sc": (
        "🎯 *Спецціль — чому не зарахована?*\n\n"
        "5 типових причин:\n"
        "• Випадіння товару при проведенні замовлення\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• ФЗ не синхронізовано\n"
        "• Невірний результат візиту\n"
        "• Самовивіз (для СЦ не враховується)\n\n"
        "Перевірити: mobiletrade → Звіти → Виконання СЦ"
    ),
    "kpi_where": (
        "📈 *Де дивитися показники?*\n\n"
        "• Blitz Trade → Головна → Інфо — загальне виконання\n"
        "• Blitz Trade → Маршрут → Торгова точка → Показники — по точці\n"
        "• Сайт mobiletrade → Головна → Дашборд\n"
        "• Звіт Аналітика — всі показники\n"
        "• Звіт ПП — по агентах і маршрутах\n"
        "• Звіт Виконання СЦ — по агент/ТРТ/товар\n\n"
        "🔗 mobiletrade.tdav.net.ua/home"
    ),
    "tech_blitz": (
        "📱 *Blitz Trade — інструкція*\n\n"
        "Повна інструкція на порталі:\n"
        "tdav.atlassian.net → Центр підтримки → IT AV Helpdesk → Мобільна торгівля → Інструкція з роботи з Blitz Trade\n\n"
        "Там же: перелік можливих помилок при синхронізації\n\n"
        "🔗 tdav.atlassian.net"
    ),
    "tech_promo": (
        "🎁 *Акція не спрацювала*\n\n"
        "Де дивитися:\n"
        "• КПК: Журнал → Замовлення → статус «Помилка експорту»\n"
        "• Сайт МТ: Документи → Замовлення → Примітки\n\n"
        "Причини:\n"
        "• Випадіння товару при замовленні\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• Акція закінчилась на філіалі\n"
        "• Перевищено ліміт акцій по ТРТ\n"
        "• Основне замовлення в СТОПАХ — акційне опрацюється після проведення\n\n"
        "Залишки по акціям — уточніть у старшого оператора\n\n"
        "🔗 mobiletrade.tdav.net.ua/doc-jrn/products-order"
    ),
    "tech_routes": (
        "🗺 *Маршрути та торгові точки*\n\n"
        "• Додати нову ТРТ в маршрут → подання інформації старшому оператору\n"
        "• Перемістити ТРТ в інший маршрут → старший оператор\n"
        "• Перемаршрутизація → шаблон Регіональному аналітику\n"
        "• Пропала ТРТ з маршруту → уточнити у старшого оператора стан точки"
    ),
    "tech_sync": (
        "🔄 *Помилка синхронізації замовлення*\n\n"
        "Перевірте:\n"
        "• Всі поля заповнені (н/д або ціна 0 → помилка)\n"
        "  → Видаліть замовлення, повна синхронізація, набийте заново\n"
        "• Немає пустих замовлень → видалити і синхронізувати\n"
        "• Статус замовлення: mobiletrade → Документи → Замовлення\n"
        "• Розшифровка статусів: tdav.atlassian.net → IT AV Helpdesk → Мобільна торгівля\n\n"
        "🔗 mobiletrade.tdav.net.ua/doc-jrn/products-order"
    ),
    "orders_status": (
        "🔤 *Статуси замовлень*\n\n"
        "• `R*` — Резерв (замовлення прийнято)\n"
        "• `ND*` — Немає даних / не оброблено\n"
        "• `CRE*` — Кредитне замовлення\n"
        "• `А*` — Архів\n"
        "• `АЕ*` — Архів з помилкою\n\n"
        "Повна розшифровка: tdav.atlassian.net → Мобільна торгівля → Документ замовлення\n\n"
        "🔗 mobiletrade.tdav.net.ua/doc-jrn/products-order"
    ),
    "orders_stock": (
        "📦 *Залишки товарів*\n\n"
        "• При створенні замовлення — залишки відображаються автоматично\n"
        "• Blitz Trade → Головна → Звіти → Залишки\n"
        "• Сайт МТ → Звіти → Залишки товарів на складі\n\n"
        "Товар відображається згідно вибраної фірми в замовленні\n\n"
        "🔗 mobiletrade.tdav.net.ua/rest-of-goods"
    ),
    "orders_missing": (
        "🚫 *Товар не відображається*\n\n"
        "• Якщо товар не відображається в КПК → його немає на залишках\n"
        "• Товар доступний згідно вибраної фірми в замовленні\n"
        "• Немає потрібної фірми → відсутній або закінчився договір\n"
        "  → Зверніться до старшого оператора"
    ),
}


def get_preset(suffix: str) -> Optional[str]:
    """Return the answer string for a leaf suffix, or None if not found."""
    return PRESETS.get(suffix)


# ---------------------------------------------------------------------------
# Keyboard factories
# All callback_data values are built as f"{prefix}{suffix}" so that callers
# choose the prefix (e.g. 'ax_' for Alex AVTD, 'hr_avtd:' for Maya HR).
# ---------------------------------------------------------------------------

def main_menu_keyboard(
    prefix: str,
    extra_rows: Optional[List[List[Dict]]] = None,
) -> Dict:
    """Root menu.  ``extra_rows`` are prepended before the branch buttons.
    Alex AVTD passes the photo-report URL row here; other callers omit it.
    """
    rows: List[List[Dict]] = []
    if extra_rows:
        rows.extend(extra_rows)
    rows.append([
        {"text": "👤 Клієнт", "callback_data": f"{prefix}client"},
        {"text": "📊 KPI", "callback_data": f"{prefix}kpi"},
    ])
    rows.append([
        {"text": "🔧 Технічні питання", "callback_data": f"{prefix}tech"},
        {"text": "📦 Замовлення", "callback_data": f"{prefix}orders"},
    ])
    return {"inline_keyboard": rows}


def back_keyboard(prefix: str) -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "◀ Головне меню", "callback_data": f"{prefix}menu"}]
        ]
    }


def client_keyboard(prefix: str) -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "📋 Умови співпраці", "callback_data": f"{prefix}client_terms"}],
            [{"text": "💰 Дебіторська заборгованість", "callback_data": f"{prefix}client_debt"}],
            [{"text": "🏪 Інформація по точці", "callback_data": f"{prefix}client_info"}],
            [{"text": "◀ Назад", "callback_data": f"{prefix}menu"}],
        ]
    }


def kpi_keyboard(prefix: str) -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "❓ Чому не зарахувався фотозвіт?", "callback_data": f"{prefix}kpi_photo"}],
            [{"text": "💵 Розрахунок бонусу / штраф за ДЗ", "callback_data": f"{prefix}kpi_bonus"}],
            [{"text": "🎯 Як рахується спецціль?", "callback_data": f"{prefix}kpi_sc"}],
            [{"text": "📈 Де дивитися мої показники?", "callback_data": f"{prefix}kpi_where"}],
            [{"text": "◀ Назад", "callback_data": f"{prefix}menu"}],
        ]
    }


def tech_keyboard(prefix: str) -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "📱 Blitz Trade — інструкція", "callback_data": f"{prefix}tech_blitz"}],
            [{"text": "🎁 Акція не спрацювала", "callback_data": f"{prefix}tech_promo"}],
            [{"text": "🗺 Маршрути та точки", "callback_data": f"{prefix}tech_routes"}],
            [{"text": "🔄 Помилка синхронізації", "callback_data": f"{prefix}tech_sync"}],
            [{"text": "◀ Назад", "callback_data": f"{prefix}menu"}],
        ]
    }


def orders_keyboard(prefix: str) -> Dict:
    return {
        "inline_keyboard": [
            [{"text": "🔤 Статуси замовлень (R*, ND*, CRE*...)", "callback_data": f"{prefix}orders_status"}],
            [{"text": "📦 Залишки товарів", "callback_data": f"{prefix}orders_stock"}],
            [{"text": "🚫 Товар не відображається", "callback_data": f"{prefix}orders_missing"}],
            [{"text": "◀ Назад", "callback_data": f"{prefix}menu"}],
        ]
    }
