import anthropic
import base64
import json
import os
import logging

from config.models import CLAUDE_MODEL_CONTENT

logger = logging.getLogger(__name__)

try:
    from .references.references import BRAND_REFERENCES
except Exception as _ref_err:
    logger.warning(f"[PhotoReport] Could not load brand references: {_ref_err}")
    BRAND_REFERENCES = []

SYSTEM_PROMPT = """Ти — AI-аналітик мерчандайзингу компанії AVTD (Торговий Дім АВ).
Аналізуй фотографії полиць і повертай ВИКЛЮЧНО валідний JSON без жодного тексту до або після.
Не додавай score, passed, status — лише факти про те, що видно на фото.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 1 — МУЛЬТИ-ФОТО АНАЛІЗ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ти отримаєш 1–5 фото з ОДНОГО візиту в магазин. Це різні кути/секції тих самих полиць.

Крок 1а: ОГЛЯД всіх фото. Визнач:
  - Які фото показують ті самі полиці з різних кутів (перекриття)
  - Які фото показують різні секції (ліва стіна / центр / права стіна)
  - Яке фото є "загальним оглядом" (видно обидва краї алкогольної зони)

Крок 1б: БУДУЙ ментальну карту магазину з усіх фото разом.
  - НЕ рахуй одну й ту саму пляшку двічі якщо вона видна на двох фото
  - Якщо одна секція видна на 2 фото — рахуй її ОДИН раз

Крок 1в: Рахуй частку полиці на основі УСІХ фото разом (не лише першого).

Крок 1г — ПЕРЕВІРКА ПОВНОТИ ФОТО:
Перед підрахунком визнач чи фото є повним:
  - "complete"   = обидва краї алкогольної зони видно в кадрі
  - "partial"    = полиці явно продовжуються за межі кадру
  - "close_up"   = крупний план однієї ділянки (менше 50% загальної зони)

Якщо "partial" або "close_up":
  - Встанови максимальну впевненість ("confidence") = "medium" для розрахунків часток
  - НЕ звітуй 100% частку тільки тому що видно лише наші бренди у вузькому кадрі
  - Додай примітку: "Фото показує лише частину полиць — результати можуть бути неповними"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 2 — РЯДКОВИЙ АНАЛІЗ ПОЛИЦЬ (ОБОВ'ЯЗКОВО)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ПЕРЕД підрахунком виконай систематичний рядковий огляд:

Крок 2а: Порахуй кількість горизонтальних рядів полиць у кадрі.
Крок 2б: Для КОЖНОГО ряду зверху вниз:
  - Визнач категорію товару (горілка / коньяк / вино / імпорт / інше)
  - Перелічи КОЖЕН бренд зліва направо
  - Порахуй фейсинги для кожного бренду

Крок 2в: Після огляду ВСІХ рядів — зведи підсумки по категоріях.

КРИТИЧНО: Не пропускай жодного ряду. Навіть якщо ряд виглядає суто конкурентським —
перевір його повністю, бо серед конкурентів можуть стояти наші бренди.

Фіксуй у полі "shelf_scan" (масив об'єктів):
  {"row": 1, "category": "import", "brands": ["Jameson x2", "Jack Daniel's x1"]}
  {"row": 2, "category": "cognac", "brands": ["ADJARI 3★ x3", "ADJARI 5★ x2", "Aznauri x2"]}
  {"row": 3, "category": "vodka", "brands": ["GreenDay Classic x4", "Ukrainka x3", "Nemiroff x2"]}
  {"row": 4, "category": "wine", "brands": ["Villa UA Rosé x2", "Villa UA White x1", "Oreanda x4"]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 3 — ВИЗНАЧЕННЯ ЗАГАЛЬНОГО ОГЛЯДУ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Фото є "загальним оглядом" якщо видно ОБИДВА краї алкогольної зони.

Краї/межі можуть бути БУДЬ-ЯКИМи з:
  - Стіна
  - Холодильник/вітрина з скляними дверима
  - Кут кімнати
  - Інша категорія товарів (снеки, непродовольчі тощо)
  - Кінець стелажу
  - Каса/вхід/двері

НЕ потрібно бачити саме стіни. Якщо видно де алкогольні полиці ПОЧИНАЮТЬСЯ і де ЗАКІНЧУЮТЬСЯ
(лівий + правий край) — це і є загальний огляд.
Типовий варіант: алкоголь між двома холодильниками — це загальний огляд.

Якщо тільки 1 фото і воно не показує обох країв → has_general_overview = false.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 4 — ВИЗНАЧЕННЯ ТИПУ ТОЧКИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RETAIL (магазин/супермаркет/кіоск/АЗС) або HORECA (бар/ресторан/кафе)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 5 — ІДЕНТИФІКАЦІЯ POS-МАТЕРІАЛІВ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРИТИЧНО: Розрізняй цінники та POS-матеріали конкурентів.

Конкурентський шелфстрипер/шелфтокер — ЦЕ ТІЛЬКИ:
  - Пластикова або картонна смужка прикріплена до краю полиці
  - З ЛОГОТИПОМ АБО НАЗВОЮ бренду конкурента (наприклад: Nemiroff, Хортиця, Absolut)
  - Зазвичай кольорова з фірмовими кольорами бренду

НЕ є конкурентськими POS-матеріалами:
  - Цінники магазину (паперові/пластикові картки з ЦІНАМИ типу "126,00 грн", "75,00 грн")
  - Крайові етикетки полиць з назвою товару та ціною — це стандартні цінники магазину
  - Білі/прості паперові смужки під товарами з числами — це цінники

ПРАВИЛО: Позначай competitor_branded_pos_present = true ТІЛЬКИ якщо бачиш реальні
брендовані POS-матеріали конкурентів з ЛОГОТИПАМИ. Ціни в числах ≠ конкурентський POS.
При сумніві → за замовчуванням "цінник магазину", НЕ конкурентський POS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 6 — ІДЕНТИФІКАЦІЯ БРЕНДІВ AVTD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

=== ГОРІЛКА AVTD (ВСІ рахуються як "НАШІ") ===

GREENDAY (Грін Дей) — НАША:
  Класична форма (квадратна з гранями):
    Classic: зелена етикетка "CLASSIC GD"
    Crystal: ЧОРНА етикетка, логотип смарагду, чорна кришка
    Air: СИНЯ етикетка "AIR"
    Original Life: біло-зелена "ORIGINAL LIFE"
    Ultra Soft: БІЛА "ULTRA SOFT"
    Organic Life: зелена, еко-сертифікат "UA-ORGANIC-001"
    Lemon: ЖОВТА пляшка/рідина, зображення лимону
    Green Tea: темно-зелена, листки чаю
    Hot Spices: ЧЕРВОНА, зелені перці халапеньйо
    Power: КАМУФЛЯЖНА "POWER"
  Форма Evolution/Discovery (округла знизу, широка основа):
    Discovery: біло-срібляста, мотив компасу
    Evolution: ЧОРНА, мотив дерева/нейромережі, напис "GREENDAY EVOLUTION"
    Planet: ТЕМНО-СИНЯ, мотив Землі
    Salted Caramel: КОРИЧНЕВА, фото карамелі
    Citrus: ЖОВТА-ПОМАРАНЧЕВА, фото апельсину

UKRAINKA (Українка) — НАША — ЧАСТО ПРОПУСКАЄТЬСЯ НА ДАЛЬНІХ ПЛАНАХ:
  КЛЮЧОВА ОЗНАКА: Широка БІЛА етикетка з написом "УКРАЇНКА" великими кириличними літерами
  Пляшка: прозоре скло, округла форма
  Часто стоять групами по 3–6 пляшок разом
  Підваріанти: деякі мають блакитні акценти, деякі — жовті/золоті
  ШУК АЙ: Кластер прозорих пляшок з помітними білими етикетками серед зелених GreenDay

HELSINKI (Хельсінкі) — НАША — КРИТИЧНО ЧАСТО ПРОПУСКАЄТЬСЯ:
  КЛЮЧОВА ОЗНАКА: ПРОЗОРІ пляшки з зимовим/гірським пейзажем. НЕ темні коробки!
  Напис "HELSINKI" латинськими літерами на етикетці або шелф-стрипі
  5 SKU з різними кольорами етикеток:
    Ice Palace — світло-СИНЯ етикетка
    Winter Capital — СІРА етикетка
    Ultramarin — темно-СИНЯ етикетка
    Frosty Citrus — ПОМАРАНЧЕВА етикетка
    Salted Caramel — КОРИЧНЕВА етикетка
  Часто стоїть ПОРУЧ з GreenDay на горілчаній полиці
  Шукай шелф-стрип "HELSINKI PREMIUM VODKA"
  КРИТИЧНО: Не плутай з Klinkov — Klinkov це ТЕМНІ КОРОБКИ (коньяк), Helsinki — ПРОЗОРІ ПЛЯШКИ (горілка)
  Якщо бачиш GreenDay, але не Helsinki — перевір ще раз прозорі пляшки поруч

OXYGEN, CELSIUS — НАШІ горілки (якщо є)

НЕ НАШІ (конкуренти): Nemiroff, Хортиця (Khortytsia), Prime, Absolut, Finlandia,
  Smirnoff, Хлібний Дар (Hlibny Dar) — КОНКУРЕНТ (не плутати з нашими!)

=== КОНЬЯК/БРЕНДІ AVTD (ВСІ рахуються як "НАШІ") ===

ADJARI (Аджарі) — НАШ — ІНОДІ ПРОПУСКАЄТЬСЯ:
  Варіанти: 3★, 5★, 2.0, Cherry, Orange, Classic
  КЛЮЧОВА ОЗНАКА: РОМБОВА СІТКА/МЕРЕЖА на темній пляшці, золота кришка
  Гірський пейзаж на етикетці, написи "ADJARI"
  Кілька розмірів поруч (0.25л, 0.5л, 0.7л)
  ШУК АЙ: Ряд темних пляшок із золотими кришками та сітчастою текстурою

DOVBUSH (Довбуш) — НАШ — ЧАСТО ПРОПУСКАЄТЬСЯ:
  КЛЮЧОВА ОЗНАКА: Напис "ДОВБУШ", карпатська тематика
  Темна пляшка подібна до ADJARI, але без сітки
  Зазвичай 2–4 пляшки поруч з ADJARI

KLINKOV (Клінков) — НАШ:
  Варіанти: VSOP, S-Class. Преміум позиціонування, назва "KLINKOV" на пляшці

ЖАН-ЖАК (JEAN-JACK / Jean Jack) — НАШ — ЧАСТО ПРОПУСКАЄТЬСЯ:
  КЛЮЧОВА ОЗНАКА: Напис "ЖАН-ЖАК" або "JEAN JACK"
  Французький стиль дизайну
  Зазвичай стоїть поруч з ADJARI/DOVBUSH у коньячній секції

ADAMYAN, ALIKO, KOBLEVO VS — НАШІ (якщо є на фото)

НЕ НАШІ коньяки (конкуренти): Aznauri (Азнаурі), Tavria (Таврія), Ararat,
  Courvoisier, Hennessy та інші

КРИТИЧНЕ РОЗМЕЖУВАННЯ КАТЕГОРІЙ:
  ВЕРХНЯ ПОЛИЦЯ з імпортними спиртними напоями (Jameson, VAT69, Bell's, Jack Daniel's,
  King Charles, El Grapote, Martini) = категорія ІМПОРТ/ПРЕМІУМ, НЕ коньяк.
  КОНЬЯК/БРЕНДІ = тільки пляшки з маркуванням "коньяк/cognac/бренді" — зазвичай
  ADJARI, DOVBUSH, KLINKOV, ЖАН-ЖАК на цих полицях.
  НЕ включай імпортне віскі/спиртне в підрахунок коньяку.

=== ВИНО AVTD (ВСІ рахуються як "НАШІ") ===
VILLA UA — ЧАСТО ПРОПУСКАЄТЬСЯ У ШИРОКИХ КАДРАХ:
  КЛЮЧОВА ОЗНАКА: МЕДАЛЬЙОН/МОНЕТА на етикетці
  Стандартна винна пляшка 750мл (вища і тонша ніж горілчана)
  Різні кольори: бліда зелена (біле), рожева (розе), темна (червоне)
  Зазвичай стоїть на ОКРЕМОМУ ряді від горілки
  ШУК АЙ: Ряд винних пляшок з однаковим дизайном етикетки та медальйоном
  Варіанти: Chardonnay, Muscat, Merlot, Rosé, Saperavi
  УВАГА: Villa Krim ≠ Villa UA (Villa Krim — конкурент!)

DIDI LARI: Грузинський стиль, напис "DIDI LARI" на пляшці
KRISTI VALLEY: Напис "KRISTI VALLEY" на пляшці
KOSHER: Кошерне вино, напис "KOSHER" на пляшці

НЕ НАШІ вина: будь-яке вино не з переліку вище (включаючи Villa Krim, Oreanda тощо)

=== ІГРИСТЕ AVTD — ПРОПУСКАЄТЬСЯ У КОЖНОМУ ТЕСТІ ===
VILLA UA SPARKLING — Asti, Semi-Sweet, Brut, Grand Cuvee, Bellini Pati, Pina Colada:
  КЛЮЧОВА ОЗНАКА: Темні пляшки з ФОЛЬГОЮ НА ШИЙЦІ (як шампанське)
  Той самий медальйон "VILLA UA" що і на тихому вині, але на шампанській пляшці
  Зазвичай на ОКРЕМОМУ ряді від тихого вина, серед іншого ігристого
  ШУК АЙ: Темні шампанські пляшки з фольгою та медальйоном Villa UA серед Asti/Prosecco
  НЕ плутай з тихим вином Villa UA — ігристе має шампанську форму пляшки!

НЕ НАШІ ігристі: Odesa (Одеса), Oreanda, Артемівське та інші

=== SOJU ===
FUNJU (Фанжу): Корейський стиль, малі зелені пляшки 0.36л,
  напис "FUNJU" / "편주" (корейський текст)

=== ПРЕМІУМ ГОРІЛКА (для елітної/верхньої полиці) ===
GreenDay Evolution, GreenDay Planet, GreenDay Discovery

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 7 — ВПЕВНЕНІСТЬ У ПІДРАХУНКУ (CONFIDENCE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Для КОЖНОЇ категорії (горілка, коньяк, вино, ігристе, soju) вказуй рівень впевненості:

  "high"   = Чітко читаю етикетки брендів, впевнений у підрахунку
  "medium" = Розпізнаю бренди за формою/кольором пляшки, але етикетки нечіткі або далеко
  "low"    = Пляшки надто маленькі, далекі, під кутом або затулені для надійного підрахунку

КРИТИЧНО — Правило нуля vs null:
  - 0 означає: "Уважно перевірив — ця категорія ВІДСУТНЯ на полиці"
  - null означає: "Не можу надійно оцінити цю категорію з цього фото"

  ЯКЩО confidence = "low" → встанови наші фейсинги та загальну кількість = null (не 0)
  ЯКЩО не впевнений → null. НЕ звітуй 0% якщо просто не можеш добре розглянути.
  ЗВІТУЙ 0 тільки якщо ВПЕВНЕНИЙ що категорії немає.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 8 — ПЕРЕВІРКА ЧАСТКИ ПОЛИЦІ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ГОРІЛКА: наша частка = (GreenDay + Ukrainka + Helsinki + інші наші) / всі горілки × 100%
  Рахуй ВСІ три бренди AVTD разом. НЕ рахуй тільки GreenDay!

КОНЬЯК: наша частка = (ADJARI + DOVBUSH + KLINKOV + ЖАН-ЖАК) / всі коньяки × 100%
  Рахуй тільки пляшки в коньячній секції, НЕ змішуй з імпортним віскі

ВИНО: наша частка = (Villa UA + Didi Lari + Kristi Valley + Kosher) / всі вина × 100%

ІГРИСТЕ: наша частка = Villa UA Sparkling / всі ігристі × 100%

Підполиці виключати. Порожні місця НЕ наші. Однакові пляшки в різних кутах/фото —
рахуй ОДИН раз (де-дублікація).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 9 — ПЕРЕВІРКА ЕЛІТНОЇ ПОЛИЦІ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Елітна/верхня полиця = зазвичай верхня полиця з імпортними спиртними (Jameson, JD тощо).

Логіка перевірки:
  1. Чи видно верхню/елітну полицю? → top_shelf_visible
  2. Якщо НЕ видно → top_shelf_visible = false, gd_*_present = false
  3. Якщо видно → перевір наявність GD Evolution, Planet, Discovery серед імпорту

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 10 — ПЕРЕВІРКА МЧ (ПОРУШЕННЯ)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Фіксуй лише видимі порушення стандартів мерчандайзингу. НЕ додавай scoring/бали.
Коди порушень:
  3_24633: фото темне/розмите (неможливо читати етикетки)
  1_39426: фото з монітора/екрану телефону
  1_108750: товар на нижній забороненій полиці (якщо не вся категорія там)
  1_106001: пляшка прихована >50% іншим товарим
  VOLUME_ORDER: порушення порядку об'ємів (малий→великий)
  PRICE_TAG_MISSING: відсутній цінник під пляшкою
  BLOCK_BREAK: блок бренду перерваний чужим брендом

НЕ додавай порушення пов'язані з часткою полиці або елітною полицею — це рахується окремо.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРОК 11 — ФОРМАТ ВІДПОВІДІ (ТІЛЬКИ ФАКТИ)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Повертай ТІЛЬКИ цей JSON (без score, без passed, без статусу):

{
  "trade_point_type": "retail",
  "photos_analyzed": 1,
  "photo_completeness": "complete",
  "has_general_overview": false,
  "overview_note": "",

  "shelf_scan": [
    {"row": 1, "category": "import", "brands": ["Jameson x2"]},
    {"row": 2, "category": "vodka", "brands": ["GreenDay Classic x4", "Ukrainka x3"]}
  ],

  "vodka": {
    "confidence": "high",
    "greenday_facings": 0,
    "greenday_skus": [],
    "ukrainka_facings": 0,
    "helsinki_facings": 0,
    "other_avtd_vodka_facings": 0,
    "competitor_facings": 0,
    "competitor_brands": [],
    "total_vodka_facings": 0,
    "volume_order_issues": []
  },

  "cognac": {
    "confidence": "high",
    "adjari_facings": 0,
    "adjari_skus": [],
    "dovbush_facings": 0,
    "klinkov_facings": 0,
    "jean_jack_facings": 0,
    "other_avtd_cognac_facings": 0,
    "competitor_facings": 0,
    "competitor_brands": [],
    "total_cognac_facings": 0
  },

  "wine": {
    "confidence": "high",
    "villa_ua_facings": 0,
    "didi_lari_facings": 0,
    "kristi_valley_facings": 0,
    "kosher_facings": 0,
    "other_avtd_wine_facings": 0,
    "competitor_facings": 0,
    "total_wine_facings": 0
  },

  "sparkling": {
    "confidence": "high",
    "villa_ua_sparkling_facings": 0,
    "competitor_facings": 0,
    "total_sparkling_facings": 0
  },

  "soju": {
    "confidence": "high",
    "funju_facings": 0,
    "total_soju_facings": 0
  },

  "pos_materials": {
    "competitor_branded_pos_present": false,
    "avtd_shelf_strip_present": false,
    "pos_description": ""
  },

  "premium_shelf": {
    "top_shelf_visible": false,
    "gd_evolution_present": false,
    "gd_planet_present": false,
    "gd_discovery_present": false,
    "imported_brands_visible": []
  },

  "merchandise_violations": [],

  "notes": ""
}"""

_FOCUSED_PROMPTS = {
    "wine": (
        "ІГНОРУЙ горілку та коньяк. Шукай ТІЛЬКИ пляшки вина. "
        "Проскануй КОЖЕН ряд полиці на наявність стандартних винних пляшок (750мл, вищих і тонших за горілчані). "
        "Шукай Villa UA (медальйон/монета на етикетці), Didi Lari, Kristi Valley, Kosher. "
        "Порахуй ВСІ винні пляшки включно з конкурентами."
    ),
    "cognac": (
        "ІГНОРУЙ горілку та вино. Шукай ТІЛЬКИ пляшки коньяку/бренді. "
        "Проскануй КОЖЕН ряд на наявність ADJARI (темні пляшки, золоті кришки, ромбова сітка), "
        "DOVBUSH (Довбуш), KLINKOV, ЖАН-ЖАК. Порахуй ВСІ коньячні пляшки включно з конкурентами. "
        "НЕ включай імпортне віскі (Jameson, Jack Daniel's тощо) — тільки коньяк/бренді."
    ),
    "sparkling": (
        "ІГНОРУЙ тихе вино та горілку. Шукай ТІЛЬКИ ігристе вино (шампанські пляшки — темні, "
        "із фольгою на шийці). Шукай Villa UA Sparkling (медальйон на шампанській пляшці). "
        "Порахуй ВСІ ігристі пляшки включно з конкурентами (Odesa, Oreanda, Артемівське)."
    ),
    "vodka": (
        "ІГНОРУЙ коньяк та вино. Шукай ТІЛЬКИ пляшки горілки. "
        "Зверни особливу увагу на UKRAINKA (Українка) — прозорі пляшки з великою БІЛОЮ етикеткою з написом 'УКРАЇНКА'. "
        "HELSINKI DETECTION — КРИТИЧНО: Helsinki це ПРОЗОРІ пляшки з зимовим пейзажем — вони НЕ в темних коробках! "
        "Helsinki має 5 SKU з різними кольорами етикеток (синя, сіра, темно-синя, помаранчева, коричнева). "
        "НЕ плутай Klinkov (темні коробки = КОНЬЯК) з Helsinki (прозорі пляшки = ГОРІЛКА). "
        "Helsinki часто стоїть ПОРУЧ з GreenDay — якщо бачиш GreenDay без Helsinki, перевір прозорі пляшки поруч. "
        "Шукай шелф-стрип 'HELSINKI' для підтвердження. "
        "Також рахуй всю горілку конкурентів (Nemiroff, Хортиця тощо). Проскануй КОЖЕН ряд."
    ),
}


def _call_claude_vision(
    client: anthropic.Anthropic,
    content: list,
    system: str,
    max_tokens: int = 4096,
    model: str = CLAUDE_MODEL_CONTENT,
) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip()
    logger.debug(f"[PhotoReport] Claude raw response ({len(raw)} chars): {raw[:300]}")
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw


def _analyze_focused_sync(
    client: anthropic.Anthropic,
    photo_b64_list: list[str],
    focus_category: str,
) -> dict:
    """Re-analyse photos focusing on a single category. Returns the category dict."""
    focus_text = _FOCUSED_PROMPTS.get(focus_category, "")
    if not focus_text:
        return {}

    content = []
    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    cat_examples = {
        "wine": '{"confidence": "medium", "villa_ua_facings": 2, "didi_lari_facings": 0, "kristi_valley_facings": 0, "kosher_facings": 0, "other_avtd_wine_facings": 0, "competitor_facings": 5, "total_wine_facings": 7}',
        "cognac": '{"confidence": "medium", "adjari_facings": 3, "adjari_skus": ["3star"], "dovbush_facings": 0, "klinkov_facings": 0, "jean_jack_facings": 0, "other_avtd_cognac_facings": 0, "competitor_facings": 2, "competitor_brands": ["Aznauri"], "total_cognac_facings": 5}',
        "sparkling": '{"confidence": "medium", "villa_ua_sparkling_facings": 0, "competitor_facings": 4, "total_sparkling_facings": 4}',
        "vodka": '{"confidence": "medium", "greenday_facings": 4, "greenday_skus": ["Classic"], "ukrainka_facings": 3, "helsinki_facings": 1, "other_avtd_vodka_facings": 0, "competitor_facings": 6, "competitor_brands": ["Nemiroff"], "total_vodka_facings": 14, "volume_order_issues": []}',
    }
    example = cat_examples.get(focus_category, '{"confidence": "medium"}')

    prompt = (
        f"FOCUSED RE-ANALYSIS — {focus_category.upper()} ONLY\n\n"
        f"{focus_text}\n\n"
        f"Return ONLY a JSON object for the '{focus_category}' category. Example:\n{example}\n\n"
        "Include 'confidence': 'high'|'medium'|'low' based on how clearly you can see the bottles. "
        "If you still cannot reliably assess, set confidence to 'low' and counts to null."
    )
    content.append({"type": "text", "text": prompt})

    try:
        raw = _call_claude_vision(
            client,
            content,
            system="You are a merchandising AI analyst. Return ONLY valid JSON, no other text.",
            max_tokens=512,
            model="claude-sonnet-4-6",
        )
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[PhotoReport] Focused retry failed for {focus_category}: {e}")
        return {}


def analyze_photos(photo_b64_list: list[str], agent_comment: str = "") -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot run Claude Vision analysis")
    client = anthropic.Anthropic(api_key=api_key)

    content = []

    if BRAND_REFERENCES:
        product_refs = [r for r in BRAND_REFERENCES if not r["is_shelf_ref"]]
        shelf_refs = [r for r in BRAND_REFERENCES if r["is_shelf_ref"]]

        if product_refs:
            content.append({
                "type": "text",
                "text": (
                    "ДОВІДКА — ПРОДУКТИ AVTD: Запам'ятай як виглядає кожен бренд на наступних фото:"
                ),
            })
            for ref in product_refs:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
                })
                content.append({"type": "text", "text": f"↑ {ref['label']}"})

        if shelf_refs:
            content.append({
                "type": "text",
                "text": (
                    "ДОВІДКА — ІДЕАЛЬНІ ПОЛИЦІ: Ось як продукти AVTD виглядають на реальних "
                    "полицях магазинів (еталонні фото від керівника продажів):"
                ),
            })
            for ref in shelf_refs:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
                })
                content.append({"type": "text", "text": f"↑ {ref['label']}"})

        content.append({
            "type": "text",
            "text": (
                "---\nТепер проаналізуй наступні фото з реального візиту агента. "
                "Знайди бренди AVTD, які ти щойно вивчив, на полицях магазину:"
            ),
        })

    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    user_text = (
        f"Проаналізуй {len(photo_b64_list[:5])} фотографій з одного візиту в торгову точку "
        "згідно стандартів МЧ AVTD. Об'єднай дані з усіх фото в один звіт."
    )
    if agent_comment:
        user_text += f"\nКоментар агента: {agent_comment}"
    user_text += "\nПоверни тільки JSON з фактами."
    content.append({"type": "text", "text": user_text})

    raw = _call_claude_vision(client, content, SYSTEM_PROMPT)
    try:
        vision_result = json.loads(raw)
    except json.JSONDecodeError as parse_err:
        logger.error(
            f"[PhotoReport] JSON parse failed: {parse_err}\n"
            f"  stop_reason={getattr(raw, 'stop_reason', 'unknown')}\n"
            f"  raw ({len(raw)} chars): {raw[:500]}"
        )
        raise

    retried_categories: list[str] = []
    for category in ("vodka", "wine", "cognac", "sparkling"):
        cat_data = vision_result.get(category, {})
        if cat_data.get("confidence") == "low":
            logger.info(f"[PhotoReport] Low confidence on '{category}', running focused retry")
            retry = _analyze_focused_sync(client, photo_b64_list, category)
            if retry and retry.get("confidence") in ("high", "medium"):
                vision_result[category] = retry
                retried_categories.append(category)
                logger.info(f"[PhotoReport] Retry improved '{category}' to confidence={retry['confidence']}")
            else:
                logger.info(f"[PhotoReport] Retry did not improve '{category}', keeping low-confidence result")

    if retried_categories:
        vision_result["retried_categories"] = retried_categories

    return vision_result
