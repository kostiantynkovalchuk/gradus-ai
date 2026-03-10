from telegram import ReplyKeyboardMarkup, KeyboardButton

MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📸 Новий звіт")], [KeyboardButton("📊 Моя статистика")]],
    resize_keyboard=True
)

PHOTO_ACTIONS = ReplyKeyboardMarkup(
    [["✅ Готово", "❌ Скасувати"]],
    resize_keyboard=True
)
