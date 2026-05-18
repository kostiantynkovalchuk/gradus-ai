"""
All Ukrainian user-facing text lives here.
NO hardcoded strings in handlers — import from this module only.
"""

# ── Tender notification ────────────────────────────────────────────────────────

TENDER_START = """🟢 <b>Новий тендер: {title}</b>

№ {number}
Стартова ціна: {price}
Закінчення: {ends_at}"""

TENDER_START_BUTTON_TEXT = "Відкрити тендер"
TENDER_START_BUTTON_URL = "https://tenderlot.net/tender/{tender_id}"

# ── /start — consent flow ──────────────────────────────────────────────────────

CONSENT_TEXT = """👋 Вітаємо у боті <b>tenderlot.net</b>!

Цей бот надсилатиме вам сповіщення про нові тендери на платформі AVTD.

Для підключення нам потрібно пов'язати ваш Telegram-акаунт з вашим профілем на tenderlot.net.

<b>Ви погоджуєтеся отримувати сповіщення про тендери через Telegram?</b>"""

CONSENT_AGREE_BUTTON = "✅ Згоден"
CONSENT_DECLINE_BUTTON = "❌ Не згоден"

CONSENT_DECLINED = """Зрозуміло. Якщо передумаєте — просто надішліть /start ще раз.

Успіхів! 👋"""

SHARE_CONTACT_PROMPT = """Чудово! Тепер натисніть кнопку нижче, щоб поділитися своїм номером телефону.

Ми перевіримо, чи є ваш номер у системі tenderlot.net."""

SHARE_CONTACT_BUTTON = "📱 Поділитись контактом"

ALREADY_LINKED = """✅ Ви вже підключені до tenderlot.net.

<b>Профіль:</b>
Ім'я: {full_name}
Роль: {role}

Команди:
/help — допомога
/status — ваш профіль і статистика
/unlink — відписатися від сповіщень"""

ALREADY_LINKED_INACTIVE = """Ваш акаунт було від'єднано раніше. Хочете підключитися знову?"""

RELINK_AGREE_BUTTON = "🔄 Підключити знову"
RELINK_DECLINE_BUTTON = "❌ Ні, дякую"

# ── Contact handler ────────────────────────────────────────────────────────────

PHONE_NOT_FOUND = """На жаль, ваш номер не знайдено в системі tenderlot.net.

Перевірте, що в профілі вказано актуальний номер, і спробуйте знову (/start)."""

PHONE_INVALID = """Не вдалося розпізнати номер телефону. Будь ласка, спробуйте знову (/start)."""

LINK_SUCCESS = """✅ <b>Прив'язку успішно завершено.</b>

<b>Профіль:</b>
Ім'я: {full_name}
Роль: {role}

Тепер ви отримуватимете сповіщення про тендери в Telegram.

<b>Команди:</b>
/help — допомога
/status — ваш профіль і статистика
/unlink — відписатися від сповіщень"""

# ── /unlink ────────────────────────────────────────────────────────────────────

UNLINK_SUCCESS = """✅ Ви успішно відписалися від сповіщень.

Якщо захочете підключитися знову — надішліть /start."""

UNLINK_NOT_LINKED = """Ви ще не підключені до tenderlot.net.
Надішліть /start, щоб розпочати."""

# ── /help ──────────────────────────────────────────────────────────────────────

HELP_TEXT = """<b>tenderlot.net — бот сповіщень</b>

<b>Команди:</b>
/start — підключитися до системи сповіщень
/status — переглянути ваш профіль і статистику
/unlink — відписатися від сповіщень
/help — ця довідка

<b>FAQ:</b>
❓ <i>Чому бот не надсилає сповіщення?</i>
Переконайтесь, що ви підключені (/status) і не заблокували бота.

❓ <i>Як змінити номер телефону?</i>
Виконайте /unlink, потім /start з новим номером.

❓ <i>Як зв'язатися з підтримкою?</i>
Напишіть на support@tenderlot.net"""

# ── /status ────────────────────────────────────────────────────────────────────

STATUS_TEXT = """<b>Ваш профіль tenderlot.net</b>

Ім'я: {full_name}
Роль: {role}
Телефон: {phone}
Статус: {status}
Підключено: {linked_at}

<b>Статистика за 7 днів:</b>
Отримано сповіщень: {week_count}"""

STATUS_NOT_LINKED = """Ви ще не підключені до tenderlot.net.
Надішліть /start, щоб розпочати."""

# ── Generic ────────────────────────────────────────────────────────────────────

UNEXPECTED_ERROR = "Виникла помилка. Спробуйте пізніше або зверніться до підтримки."


# ── Helpers ────────────────────────────────────────────────────────────────────

def role_to_ukrainian(role: str) -> str:
    """Convert role slug to Ukrainian label."""
    mapping = {
        "supplier": "Постачальник",
        "carrier": "Перевізник",
        "both": "Постачальник / Перевізник",
    }
    return mapping.get(role, role)


def format_price(price: float | None, currency: str) -> str:
    """Format a tender price for display."""
    if price is None:
        return "не вказано"
    formatted = f"{price:,.0f}".replace(",", "\u00a0")  # non-breaking space
    return f"{formatted} {currency}"


def status_label(is_active: bool) -> str:
    return "✅ Активний" if is_active else "❌ Неактивний"
