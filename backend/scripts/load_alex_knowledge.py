"""
One-time script: load Alex AVTD mobiletrade knowledge into Pinecone.

Splits structured knowledge into chunks by section (one chunk per topic).
Uses metadata: source=mobiletrade_guide, bot=alex_avtd

Usage:
    cd backend
    DATABASE_URL=... python scripts/load_alex_knowledge.py

Paste the full Oleksandr document into KNOWLEDGE_SECTIONS below,
adding new dicts with 'title' and 'content' per section.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KNOWLEDGE_SECTIONS = [
    {
        "title": "Mobiletrade — Довідник Контрагенти",
        "content": (
            "Розділ Довідник → Контрагенти на сайті mobiletrade.tdav.net.ua/buyers містить:\n"
            "- Основна інформація по клієнту\n"
            "- Торгові точки клієнта\n"
            "- Угоди та умови співпраці\n"
            "- Маркетингові виплати\n"
            "- Замовлення та відвантаження\n"
            "- Оплати\n"
            "- Мерчендайзинг та Фотозвіти\n"
            "- Дебіторська заборгованість з деталізацією до накладної\n\n"
            "Також умови співпраці доступні в Blitz Trade → Маршрут → Торгова точка → Картка клієнта.\n"
            "URL: mobiletrade.tdav.net.ua/buyers"
        ),
    },
    {
        "title": "Mobiletrade — Фотозвіти та мерчендайзинг",
        "content": (
            "Фотозвіти в mobiletrade.tdav.net.ua/doc-jrn/photo-reports\n\n"
            "Чому не зарахувався фотозвіт?\n"
            "Для МЧ, ДП, ДПХ:\n"
            "- ФЗ не синхронізовано в базу\n"
            "- Невірно вибрано результат візиту\n"
            "- Результат візиту не відповідає типу ТРТ (МЧ на HoReCa — не зараховується)\n"
            "- МЧ2 — між візитами пройшло менше 5 днів\n\n"
            "Для СЦ, АКБ, ОА:\n"
            "- Випадіння товару при проведенні замовлення\n"
            "- Повернення/вичерки за попередні накладні\n"
            "- Самовивіз не враховується для СЦ\n\n"
            "Виправити результат візиту: mobiletrade → Документи → Фотозвіти (протягом 3 робочих днів)\n"
            "URL: mobiletrade.tdav.net.ua/doc-jrn/photo-reports"
        ),
    },
    {
        "title": "Mobiletrade — Головна та KPI дашборд",
        "content": (
            "Де дивитися показники KPI:\n"
            "- Blitz Trade → Головна → Інфо — загальне виконання\n"
            "- Blitz Trade → Маршрут → Торгова точка → Показники — по точці\n"
            "- Сайт mobiletrade → Головна → Дашборд\n"
            "- Звіт Аналітика — всі показники\n"
            "- Звіт ПП — по агентах і маршрутах\n"
            "- Звіт Виконання СЦ — по агент/ТРТ/товар\n\n"
            "KPI показники: СЦ (спецціль), АКБ (активна клієнтська база), "
            "ОА (обсяг активності), МЧ (мерчендайзингова частота), ДП, ДПХ\n"
            "URL: mobiletrade.tdav.net.ua/home"
        ),
    },
    {
        "title": "Mobiletrade — Замовлення та статуси",
        "content": (
            "Замовлення в mobiletrade.tdav.net.ua/doc-jrn/products-order\n\n"
            "Статуси замовлень:\n"
            "- R* — Резерв (замовлення прийнято)\n"
            "- ND* — Немає даних / не оброблено\n"
            "- CRE* — Кредитне замовлення\n"
            "- А* — Архів\n"
            "- АЕ* — Архів з помилкою\n\n"
            "Типові помилки синхронізації:\n"
            "- Всі поля заповнені (н/д або ціна 0 → помилка) → видалити, повна синхронізація, набити заново\n"
            "- Немає пустих замовлень → видалити і синхронізувати\n\n"
            "Акція не спрацювала — причини:\n"
            "- Випадіння товару при замовленні\n"
            "- Повернення/вичерки за попередні накладні\n"
            "- Акція закінчилась на філіалі\n"
            "- Перевищено ліміт акцій по ТРТ\n"
            "- Основне замовлення в СТОПАХ\n"
            "URL: mobiletrade.tdav.net.ua/doc-jrn/products-order"
        ),
    },
    {
        "title": "Mobiletrade — Залишки товарів на складі",
        "content": (
            "Залишки товарів: mobiletrade.tdav.net.ua/rest-of-goods\n\n"
            "Де дивитися залишки:\n"
            "- При створенні замовлення — залишки відображаються автоматично\n"
            "- Blitz Trade → Головна → Звіти → Залишки\n"
            "- Сайт МТ → Звіти → Залишки товарів на складі\n\n"
            "Товар відображається згідно вибраної фірми в замовленні.\n"
            "Якщо товар не відображається в КПК → його немає на залишках.\n"
            "Немає потрібної фірми → відсутній або закінчився договір → старший оператор.\n"
            "URL: mobiletrade.tdav.net.ua/rest-of-goods"
        ),
    },
    {
        "title": "Blitz Trade — інструкція та портал АВТД",
        "content": (
            "Портал підтримки: tdav.atlassian.net\n\n"
            "Повна інструкція Blitz Trade:\n"
            "tdav.atlassian.net → Центр підтримки → IT AV Helpdesk → Мобільна торгівля → "
            "Інструкція з роботи з Blitz Trade\n\n"
            "Там же: перелік можливих помилок при синхронізації, розшифровка статусів замовлень.\n\n"
            "Маршрути та торгові точки:\n"
            "- Додати нову ТРТ → старший оператор\n"
            "- Перемістити ТРТ → старший оператор\n"
            "- Перемаршрутизація → шаблон Регіональному аналітику\n"
            "- Пропала ТРТ → уточнити стан точки у старшого оператора\n"
            "URL: tdav.atlassian.net"
        ),
    },
]


async def main():
    from routes.hr_routes import hr_pinecone_index
    from services.hr_rag_service import HRRagService
    from models import get_db

    db = next(get_db())

    try:
        service = HRRagService(pinecone_index=hr_pinecone_index, db_session=db)

        for i, section in enumerate(KNOWLEDGE_SECTIONS, 1):
            print(f"\n[{i}/{len(KNOWLEDGE_SECTIONS)}] Loading: {section['title']}")
            result = await service.add_document(
                title=section["title"],
                content=section["content"],
                category="mobiletrade_guide",
                subcategory="alex_avtd",
                content_type="guide",
                keywords=["mobiletrade", "alex_avtd", "АВТД", "торговий агент"],
            )
            status = result.get("status", "unknown")
            cid = result.get("content_id", "?")
            print(f"  → {status} | id: {cid}")

        print(f"\nDone. {len(KNOWLEDGE_SECTIONS)} sections loaded.")
        print("Alex AVTD RAG will now find mobiletrade URLs and procedures in free-text queries.")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
