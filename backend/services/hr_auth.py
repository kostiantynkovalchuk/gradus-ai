import re
import os
import httpx
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from models.hr_auth_models import HRUser, HRWhitelist, VerificationLog
from services.hr_sed_service import sed_service
from utils.phone_normalizer import normalize_phone, format_for_display

logger = logging.getLogger(__name__)

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")

PENDING_VERIFICATIONS = {}


def is_valid_phone(phone: str) -> bool:
    if not phone or not isinstance(phone, str):
        return False
    digits = re.sub(r'\D', '', phone.strip())
    return 10 <= len(digits) <= 15


def get_user_by_telegram_id(db: Session, telegram_id: int):
    try:
        user = db.query(HRUser).filter(
            HRUser.telegram_id == telegram_id
        ).first()
        
        if not user:
            logger.info(f"AUTH_CHECK: telegram_id={telegram_id} -> NOT_FOUND")
            return None
        
        if not user.is_active:
            logger.warning(
                f"AUTH_CHECK: telegram_id={telegram_id} -> INACTIVE "
                f"(name={user.full_name})"
            )
            return None
        
        logger.info(
            f"AUTH_CHECK: telegram_id={telegram_id} -> OK "
            f"(name={user.full_name}, access={user.access_level})"
        )
        return user
        
    except Exception as e:
        logger.error(
            f"AUTH_CHECK: telegram_id={telegram_id} -> DB_ERROR "
            f"({type(e).__name__}: {str(e)[:200]})",
            exc_info=True
        )
        return None


def get_access_level(db: Session, telegram_id: int) -> str:
    user = get_user_by_telegram_id(db, telegram_id)
    return user.access_level if user else None


def is_awaiting_phone(telegram_id: int) -> bool:
    entry = PENDING_VERIFICATIONS.get(telegram_id)
    if entry == 'awaiting_phone':
        return True
    if isinstance(entry, dict) and entry.get('state') == 'confirming_phone':
        return True
    return False


def set_awaiting_phone(telegram_id: int, state: bool):
    if state:
        PENDING_VERIFICATIONS[telegram_id] = 'awaiting_phone'
    else:
        PENDING_VERIFICATIONS.pop(telegram_id, None)


def set_pending_phone(telegram_id: int, phone: str):
    PENDING_VERIFICATIONS[telegram_id] = {'state': 'confirming_phone', 'phone': phone}


def get_pending_phone(telegram_id: int) -> str:
    entry = PENDING_VERIFICATIONS.get(telegram_id)
    if isinstance(entry, dict) and entry.get('state') == 'confirming_phone':
        return entry.get('phone')
    return None


def clear_pending_state(telegram_id: int):
    PENDING_VERIFICATIONS.pop(telegram_id, None)


async def handle_start_command(chat_id: int, telegram_id: int, user_first_name: str, db: Session):
    user = get_user_by_telegram_id(db, telegram_id)

    if user:
        if sed_service.should_sync_user(user.last_sed_sync) and user.verification_method == 'sed_api':
            await sync_user_with_sed(db, telegram_id, user.phone)
            db.refresh(user)

        keyboard = get_inline_menu_for_access_level(user.access_level)

        if user.access_level == "developer":
            greeting = (
                f"🔓 *Developer Mode Active*\n\n"
                f"Привіт, {user.first_name or user_first_name}! 👨‍💻\n\n"
                f"Чим можу допомогти?"
            )
        elif user.access_level == "admin_hr":
            greeting = (
                f"⚙️ *HR Admin Panel Available*\n\n"
                f"Привіт, {user.first_name or user_first_name}! 👋\n\n"
                f"Готова допомогти!"
            )
        else:
            greeting = (
                f"Привіт, {user.first_name or user_first_name}! 👋\n\n"
                f"Рада знову тебе бачити! Чим можу допомогти?"
            )

        await send_message_with_keyboard(chat_id, greeting, keyboard)
        return True

    welcome_text = (
        f"👋 Привіт, {user_first_name}! Я Maya — твій HR-асистент у Торговому Домі АВ.\n\n"
        f"🎯 Допоможу з:\n"
        f"• Відпустками та зарплатою 💰\n"
        f"• Техпідтримкою (Бліц, УРС, доступи) 🔧\n"
        f"• Документами та процедурами 📋\n"
        f"• Контактами спеціалістів 📞\n\n"
        f"Для початку роботи натисни кнопку нижче, щоб поділитися своїм номером телефону ⚡"
    )
    share_contact_keyboard = {
        "keyboard": [
            [{"text": "📱 Поділитися номером телефону", "request_contact": True}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }
    await send_message_with_keyboard(chat_id, welcome_text, share_contact_keyboard)
    return True


async def handle_phone_verification(chat_id: int, telegram_id: int, phone: str,
                                     user_info: dict, db: Session):
    logger.info(
        f"VERIFY_START: telegram_id={telegram_id}, "
        f"phone={phone[:4]}***{phone[-4:] if len(phone) > 4 else phone}"
    )
    
    if not is_valid_phone(phone):
        logger.info(f"VERIFY_INVALID_FORMAT: telegram_id={telegram_id}, phone={phone}")
        share_contact_keyboard = {
            "keyboard": [
                [{"text": "📱 Поділитися номером телефону", "request_contact": True}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
        await send_message_with_keyboard(
            chat_id,
            "❌ Не вдалося перевірити номер.\n\n"
            "Натисніть кнопку нижче, щоб поділитися номером телефону 👇",
            share_contact_keyboard
        )
        return

    phone_normalized = normalize_phone(phone)
    if not phone_normalized:
        phone_normalized = phone
    phone_display = format_for_display(phone_normalized)

    whitelist_entry = None
    formats_to_check = [phone, phone_normalized]
    if phone_normalized and len(phone_normalized) == 12:
        formats_to_check.append(f"+{phone_normalized}")
        formats_to_check.append(f"0{phone_normalized[3:]}")
    for fmt in formats_to_check:
        if fmt is None:
            continue
        entry = db.query(HRWhitelist).filter(
            HRWhitelist.phone == fmt,
            HRWhitelist.is_active == True
        ).first()
        if entry:
            whitelist_entry = entry
            break

    if whitelist_entry:
        logger.info(
            f"VERIFY_WHITELIST: telegram_id={telegram_id}, "
            f"phone={phone_display}, access={whitelist_entry.access_level}, "
            f"name={whitelist_entry.full_name}"
        )
        await create_whitelisted_user(db, chat_id, telegram_id, phone_normalized, whitelist_entry)
        set_awaiting_phone(telegram_id, False)
        return

    logger.info(f"VERIFY_SED_CALL: telegram_id={telegram_id}, phone={phone_display}")
    await send_message(chat_id, f"🔍 Перевіряю номер {phone_display} в базі співробітників...")

    result = await sed_service.verify_employee(phone_normalized)

    if result["verified"]:
        employee = result["employee"]
        logger.info(
            f"AUTH_SUCCESS | tg_id={telegram_id} | "
            f"input_phone={phone_display} | "
            f"matched_as={result.get('matched_phone', 'N/A')} | "
            f"employee={employee.get('full_name', 'N/A')}"
        )
        await create_sed_verified_user(db, chat_id, telegram_id, phone_normalized, employee)
        set_awaiting_phone(telegram_id, False)
    else:
        logger.warning(
            f"AUTH_FAIL | tg_id={telegram_id} | "
            f"input_phone={phone_display} | reason={result.get('error', 'unknown')}"
        )
        await handle_verification_failure(db, chat_id, telegram_id, phone_normalized, result, user_info)
        set_awaiting_phone(telegram_id, False)


async def create_whitelisted_user(db: Session, chat_id: int, telegram_id: int,
                                   phone: str, whitelist_entry):
    existing = db.query(HRUser).filter(HRUser.telegram_id == telegram_id).first()

    if existing:
        existing.phone = phone
        existing.full_name = whitelist_entry.full_name
        existing.first_name = whitelist_entry.full_name.split()[0] if whitelist_entry.full_name else ""
        existing.access_level = whitelist_entry.access_level
        existing.verification_method = 'whitelist'
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
    else:
        user = HRUser(
            telegram_id=telegram_id,
            phone=phone,
            full_name=whitelist_entry.full_name,
            first_name=whitelist_entry.full_name.split()[0] if whitelist_entry.full_name else "",
            access_level=whitelist_entry.access_level,
            verification_method='whitelist',
            last_sed_sync=datetime.utcnow(),
            sed_sync_status='whitelist',
            is_active=True
        )
        db.add(user)

    whitelist_entry.telegram_id = telegram_id

    log = VerificationLog(
        telegram_id=telegram_id, phone=phone,
        verification_type='whitelist', status='success'
    )
    db.add(log)
    db.commit()

    keyboard = get_inline_menu_for_access_level(whitelist_entry.access_level)

    if whitelist_entry.access_level == "developer":
        message = (
            f"🔓 *Developer Access Granted*\n\n"
            f"Привіт, {whitelist_entry.full_name}! 👨‍💻\n\n"
            f"✅ Повний доступ до всіх функцій\n"
            f"✅ /admin - Адмін-панель\n"
            f"✅ /adduser - Додати користувача\n"
            f"✅ /logs - Журнал верифікацій\n"
            f"✅ /stats - Статистика\n\n"
            f"Готова допомогти!"
        )
    elif whitelist_entry.access_level == "admin_hr":
        message = (
            f"⚙️ *HR Admin Access*\n\n"
            f"Привіт, {whitelist_entry.full_name}! 👋\n\n"
            f"✅ /admin - Адмін-панель\n"
            f"✅ /adduser - Додати користувача\n"
            f"✅ /stats - Статистика\n"
            f"✅ /logs - Журнал верифікацій\n\n"
            f"Готова допомогти!"
        )
    else:
        message = (
            f"✅ Підтверджено!\n\n"
            f"Привіт, {whitelist_entry.full_name}! 👋\n\n"
            f"Готова допомогти з питаннями про TD AV!"
        )

    await send_message_with_keyboard(chat_id, message, keyboard)


async def create_sed_verified_user(db: Session, chat_id: int, telegram_id: int,
                                    phone: str, employee: dict):
    existing = db.query(HRUser).filter(HRUser.telegram_id == telegram_id).first()

    if existing:
        existing.phone = phone
        existing.employee_id = employee.get("employee_id")
        existing.full_name = employee.get("full_name")
        existing.first_name = employee.get("first_name")
        existing.last_name = employee.get("last_name")
        existing.department = employee.get("department")
        existing.position = employee.get("position")
        existing.start_date = employee.get("start_date")
        existing.email = employee.get("email")
        existing.access_level = 'employee'
        existing.verification_method = 'sed_api'
        existing.last_sed_sync = datetime.utcnow()
        existing.sed_sync_status = 'active'
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
    else:
        user = HRUser(
            telegram_id=telegram_id,
            phone=phone,
            employee_id=employee.get("employee_id"),
            full_name=employee.get("full_name"),
            first_name=employee.get("first_name"),
            last_name=employee.get("last_name"),
            department=employee.get("department"),
            position=employee.get("position"),
            start_date=employee.get("start_date"),
            email=employee.get("email"),
            access_level='employee',
            verification_method='sed_api',
            last_sed_sync=datetime.utcnow(),
            sed_sync_status='active',
            is_active=True
        )
        db.add(user)

    log = VerificationLog(
        telegram_id=telegram_id, phone=phone,
        employee_id=employee.get("employee_id"),
        verification_type='sed_direct', status='success'
    )
    db.add(log)
    db.commit()

    first_name = employee.get("first_name", "")
    position = employee.get("position", "")
    department = employee.get("department", "")

    keyboard = get_inline_menu_for_access_level("employee")
    await send_message_with_keyboard(
        chat_id,
        f"✅ Підтверджено!\n\n"
        f"Привіт, {first_name}! 👋\n\n"
        f"Я бачу, що ти {position} у відділі {department}.\n\n"
        f"Готова допомогти з будь-якими питаннями про роботу в TD AV!",
        keyboard
    )


async def handle_verification_failure(db: Session, chat_id: int, telegram_id: int,
                                       phone: str, result: dict, user_info: dict):
    error = result.get("error", "unknown")

    log = VerificationLog(
        telegram_id=telegram_id, phone=phone,
        verification_type='sed_direct', status=error
    )
    db.add(log)
    db.commit()

    from utils.phone_normalizer import format_for_display
    phone_display = format_for_display(phone)

    if error == "not_found":
        user_message = (
            f"❌ Номер {phone_display} не знайдено в базі співробітників TD AV.\n\n"
            f"Перевірте:\n"
            f"• Ви ввели правильний номер?\n"
            f"• Ви вже в системі Бліц?\n"
            f"• Номер активний в компанії?\n\n"
            f"📞 Якщо впевнені, що номер вірний:\n"
            f"Зверніться до HR-відділу: hr@vinkom.net"
        )
    elif error == "timeout":
        user_message = (
            "⚠️ Не вдалося зв'язатися з сервером.\n\n"
            "Спробуй ще раз через хвилину. Напиши /start"
        )
    elif error == "http_401":
        user_message = (
            "⚠️ Помилка авторизації сервера верифікації.\n\n"
            "Адміністратори вже повідомлені. Спробуй пізніше або зверніся в HR-відділ: hr@vinkom.net"
        )
        logger.error(f"SED API 401 Unauthorized - API key may be invalid or expired")
    elif error == "not_configured":
        user_message = (
            "⚠️ Система верифікації тимчасово недоступна.\n\n"
            "Спробуй пізніше або зверніся в HR-відділ: hr@vinkom.net"
        )
    else:
        user_message = (
            "⚠️ Виникла технічна помилка.\n\n"
            "Спробуй ще раз або зверніся в HR-відділ: hr@vinkom.net"
        )

    await send_message(chat_id, user_message)

    await notify_hr_admins_about_failed_registration(db, telegram_id, phone, user_info)


async def notify_hr_admins_about_failed_registration(db: Session, telegram_id: int,
                                                      phone: str, user_info: dict):
    admins = db.query(HRUser).filter(
        HRUser.access_level.in_(['admin_hr', 'developer']),
        HRUser.is_active == True,
        HRUser.telegram_id != telegram_id
    ).all()

    if not admins:
        logger.warning("No HR admins found to notify about failed registration")
        return

    first_name = user_info.get("first_name", "")
    last_name = user_info.get("last_name", "")
    username = user_info.get("username")
    username_str = f"@{username}" if username else "немає username"

    notification = (
        f"🚨 *Спроба реєстрації (невдала)*\n\n"
        f"📱 Телефон: `{phone}`\n"
        f"👤 Telegram: {first_name} {last_name}\n"
        f"🆔 Username: {username_str}\n"
        f"🔢 Telegram ID: `{telegram_id}`\n\n"
        f"❌ Номер не знайдено в СЕД Бліц\n\n"
        f"*Дії:*\n"
        f"• Якщо це новий співробітник → додай в СЕД\n"
        f"• Якщо це підрядник → використай /adduser\n\n"
        f"Приклад:\n"
        f"`/adduser {phone} Ім'я Прізвище contractor Опис причини`"
    )

    for admin in admins:
        try:
            await send_message(admin.telegram_id, notification)
            logger.info(f"Notified HR admin {admin.full_name} about failed registration")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin.telegram_id}: {e}")


async def sync_user_with_sed(db: Session, telegram_id: int, phone: str):
    result = await sed_service.verify_employee(phone)
    user = db.query(HRUser).filter(HRUser.telegram_id == telegram_id).first()
    if not user:
        return

    if result["verified"]:
        emp = result["employee"]
        user.employee_id = emp.get("employee_id")
        user.full_name = emp.get("full_name")
        user.first_name = emp.get("first_name")
        user.last_name = emp.get("last_name")
        user.department = emp.get("department")
        user.position = emp.get("position")
        user.start_date = emp.get("start_date")
        user.last_sed_sync = datetime.utcnow()
        user.sed_sync_status = 'active'
        db.commit()
        logger.info(f"Synced user {telegram_id} with SED")
    else:
        user.sed_sync_status = 'not_found'
        user.last_sed_sync = datetime.utcnow()
        db.commit()
        logger.warning(f"User {telegram_id} not found in SED during sync")


async def handle_admin_command(chat_id: int, telegram_id: int, db: Session):
    access = get_access_level(db, telegram_id)
    if not access or access not in ["developer", "admin_hr", "admin_it"]:
        await send_message(chat_id, "❌ У тебе немає доступу до адмін-панелі")
        return

    from sqlalchemy import func as sqlfunc

    total = db.query(sqlfunc.count(HRUser.id)).scalar() or 0
    active = db.query(sqlfunc.count(HRUser.id)).filter(HRUser.is_active == True).scalar() or 0
    devs = db.query(sqlfunc.count(HRUser.id)).filter(HRUser.access_level == 'developer').scalar() or 0
    admins = db.query(sqlfunc.count(HRUser.id)).filter(HRUser.access_level.like('admin%')).scalar() or 0
    sed_verified = db.query(sqlfunc.count(HRUser.id)).filter(HRUser.verification_method == 'sed_api').scalar() or 0
    whitelisted = db.query(sqlfunc.count(HRUser.id)).filter(HRUser.verification_method == 'whitelist').scalar() or 0

    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_total = db.query(sqlfunc.count(VerificationLog.id)).filter(VerificationLog.created_at >= today_start).scalar() or 0
    today_success = db.query(sqlfunc.count(VerificationLog.id)).filter(
        VerificationLog.created_at >= today_start, VerificationLog.status == 'success'
    ).scalar() or 0
    today_failed = today_total - today_success

    message = (
        f"📊 *Maya HR Admin Panel*\n\n"
        f"*Користувачі:*\n"
        f"👥 Всього: {total}\n"
        f"✅ Активних: {active}\n"
        f"👨‍💻 Розробників: {devs}\n"
        f"⚙️ Адмін: {admins}\n"
        f"🔗 Верифіковано СЕД: {sed_verified}\n"
        f"📝 З whitelist: {whitelisted}\n\n"
        f"*Активність сьогодні:*\n"
        f"📈 Спроб входу: {today_total}\n"
        f"✅ Успішних: {today_success}\n"
        f"❌ Невдалих: {today_failed}\n\n"
        f"*Команди:*\n"
        f"/adduser - Додати користувача\n"
        f"/listusers - Список користувачів\n"
        f"/logs - Журнал верифікацій\n"
        f"/stats - Детальна статистика\n"
        f"/syncuser - Синхронізувати з СЕД"
    )

    await send_message(chat_id, message)


async def handle_adduser_command(chat_id: int, telegram_id: int, args_text: str, db: Session):
    access = get_access_level(db, telegram_id)
    if not access or access not in ["developer", "admin_hr"]:
        await send_message(chat_id, "❌ У тебе немає прав додавати користувачів")
        return

    admin = get_user_by_telegram_id(db, telegram_id)
    parts = args_text.strip().split() if args_text else []

    if len(parts) < 4:
        await send_message(
            chat_id,
            "➕ *Додати користувача вручну*\n\n"
            "*Формат:*\n"
            "`/adduser +380XXXXXXXXX Ім'я Прізвище рівень Причина`\n\n"
            "*Рівні доступу:*\n"
            "• `employee` - співробітник TD AV\n"
            "• `contractor` - підрядник\n"
            "• `admin_hr` - HR адміністратор\n"
            "• `admin_it` - IT адміністратор\n"
            "• `developer` - розробник системи\n\n"
            "*Приклади:*\n"
            "`/adduser +380671234567 Олег Петренко employee Торговий представник`\n"
            "`/adduser +380501234567 Марія Іванова contractor Зовнішній консультант`"
        )
        return

    phone_raw = parts[0]
    first_name = parts[1]
    last_name = parts[2]
    full_name = f"{first_name} {last_name}"
    access_level_new = parts[3]
    reason = " ".join(parts[4:]) if len(parts) > 4 else "Додано вручну"

    if not is_valid_phone(phone_raw):
        await send_message(
            chat_id,
            "❌ Невірний формат телефону.\n"
            "Підтримуються: +380XXXXXXXXX, 0XXXXXXXXX, 380XXXXXXXXX"
        )
        return

    phone = normalize_phone(phone_raw)
    if not phone:
        phone = phone_raw

    valid_levels = ["employee", "contractor", "admin_hr", "admin_it", "developer"]
    if access_level_new not in valid_levels:
        await send_message(
            chat_id,
            "❌ Невірний рівень доступу. Доступні:\n"
            "• `employee` - співробітник\n"
            "• `contractor` - підрядник\n"
            "• `admin_hr` - HR адміністратор\n"
            "• `admin_it` - IT адміністратор\n"
            "• `developer` - розробник\n\n"
            "Приклад:\n"
            "`/adduser +380671234567 Іван Іванов employee Співробітник відділу продажів`"
        )
        return

    try:
        existing = db.query(HRWhitelist).filter(HRWhitelist.phone == phone).first()
        if existing:
            existing.full_name = full_name
            existing.access_level = access_level_new
            existing.reason = reason
            existing.added_by = admin.full_name if admin else "Admin"
            existing.is_active = True
            existing.added_at = datetime.utcnow()
        else:
            entry = HRWhitelist(
                phone=phone, full_name=full_name, access_level=access_level_new,
                reason=reason, added_by=admin.full_name if admin else "Admin"
            )
            db.add(entry)

        db.commit()

        await send_message(
            chat_id,
            f"✅ *Користувача додано!*\n\n"
            f"📱 Телефон: `{phone}`\n"
            f"👤 Ім'я: {full_name}\n"
            f"🔑 Рівень доступу: `{access_level_new}`\n"
            f"📝 Причина: {reason}\n"
            f"➕ Додав: {admin.full_name if admin else 'Admin'}\n\n"
            f"Тепер цей користувач може увійти через /start"
        )
        logger.info(f"Admin added {full_name} ({phone}) to whitelist")

    except Exception as e:
        db.rollback()
        logger.error(f"Error adding user to whitelist: {e}")
        await send_message(chat_id, f"❌ Помилка при додаванні: {str(e)}")


async def handle_logs_command(chat_id: int, telegram_id: int, db: Session):
    access = get_access_level(db, telegram_id)
    if not access or access not in ["developer", "admin_hr", "admin_it"]:
        await send_message(chat_id, "❌ Немає доступу")
        return

    logs = db.query(VerificationLog).order_by(
        VerificationLog.created_at.desc()
    ).limit(15).all()

    if not logs:
        await send_message(chat_id, "📋 Журнал верифікацій порожній")
        return

    log_text = "📋 *Останні 15 спроб верифікації:*\n\n"

    for entry in logs:
        status_emoji = "✅" if entry.status == "success" else "❌"
        time_str = entry.created_at.strftime("%d.%m %H:%M") if entry.created_at else "?"

        user = db.query(HRUser).filter(HRUser.telegram_id == entry.telegram_id).first()
        name = user.full_name if user else "Невідомий"

        log_text += (
            f"{status_emoji} `{time_str}` | `{entry.phone}`\n"
            f"   {name} | {entry.verification_type} | {entry.status}\n\n"
        )

    await send_message(chat_id, log_text)


async def handle_stats_command(chat_id: int, telegram_id: int, db: Session):
    access = get_access_level(db, telegram_id)
    if not access or access not in ["developer", "admin_hr", "admin_it"]:
        await send_message(chat_id, "❌ Немає доступу")
        return

    from sqlalchemy import func as sqlfunc
    from datetime import timedelta

    now = datetime.utcnow()
    last_24h = db.query(sqlfunc.count(VerificationLog.id)).filter(
        VerificationLog.created_at > now - timedelta(hours=24)
    ).scalar() or 0
    last_7d = db.query(sqlfunc.count(VerificationLog.id)).filter(
        VerificationLog.created_at > now - timedelta(days=7)
    ).scalar() or 0
    last_30d = db.query(sqlfunc.count(VerificationLog.id)).filter(
        VerificationLog.created_at > now - timedelta(days=30)
    ).scalar() or 0

    dept_stats = db.query(
        HRUser.department, sqlfunc.count(HRUser.id)
    ).filter(
        HRUser.is_active == True,
        HRUser.department.isnot(None)
    ).group_by(HRUser.department).order_by(sqlfunc.count(HRUser.id).desc()).limit(10).all()

    message = "📊 *Детальна статистика Maya HR*\n\n"
    message += "*Верифікації:*\n"
    message += f"📅 За 24 години: {last_24h}\n"
    message += f"📅 За 7 днів: {last_7d}\n"
    message += f"📅 За 30 днів: {last_30d}\n\n"

    if dept_stats:
        message += "*Топ відділів (активні):*\n"
        for idx, (dept, count) in enumerate(dept_stats, 1):
            message += f"{idx}. {dept}: {count}\n"

    await send_message(chat_id, message)


async def handle_listusers_command(chat_id: int, telegram_id: int, db: Session):
    access = get_access_level(db, telegram_id)
    if access != "developer":
        await send_message(chat_id, "❌ Тільки для розробників")
        return

    users = db.query(HRUser).order_by(HRUser.access_level, HRUser.full_name).limit(50).all()

    message = f"👥 *Користувачі ({len(users)}):*\n\n"
    current_level = None

    for u in users:
        if u.access_level != current_level:
            current_level = u.access_level
            message += f"\n*{current_level.upper()}:*\n"
        status = "✅" if u.is_active else "❌"
        message += f"{status} {u.full_name} | `{u.phone}`\n"

    await send_message(chat_id, message)


def get_inline_menu_for_access_level(access_level: str) -> dict:
    from services.hr_keyboards import create_main_menu_keyboard
    base = create_main_menu_keyboard()
    buttons = list(base.get("inline_keyboard", []))

    if access_level == "developer":
        buttons.append([
            {"text": "👨‍💻 Admin", "callback_data": "admin_cmd:admin"},
            {"text": "📊 Stats", "callback_data": "admin_cmd:stats"},
            {"text": "🔍 Logs", "callback_data": "admin_cmd:logs"}
        ])
        buttons.append([
            {"text": "➕ Add User", "callback_data": "admin_cmd:adduser"},
            {"text": "👥 List Users", "callback_data": "admin_cmd:listusers"}
        ])
    elif access_level in ("admin_hr", "admin_it"):
        buttons.append([
            {"text": "⚙️ Admin", "callback_data": "admin_cmd:admin"},
            {"text": "➕ Add User", "callback_data": "admin_cmd:adduser"},
            {"text": "📊 Stats", "callback_data": "admin_cmd:stats"}
        ])

    return {"inline_keyboard": buttons}


async def send_message(chat_id: int, text: str):
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.warning("TELEGRAM_MAYA_BOT_TOKEN not set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")


async def send_message_with_keyboard(chat_id: int, text: str, keyboard: dict):
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.warning("TELEGRAM_MAYA_BOT_TOKEN not set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard
            })
    except Exception as e:
        logger.error(f"Error sending message with keyboard to {chat_id}: {e}")
