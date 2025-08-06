import logging
import os
import aiosqlite
from telegram import (Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile)
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler)
from datetime import datetime, timedelta
import xlsxwriter
import asyncio

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Токен бота ---
BOT_TOKEN = "8042271583:AAHNBkjbd4BtbqS_djLsmywgqS5Y6sONnVU"

# --- Состояния для ConversationHandler ---
LOGIN, PASSWORD, MENU, ORDER, QUANTITY, DELIVERY_DATE, PHONE, SHOP_NAME, CONFIRM = range(9)

# --- Продукты ---
PRODUCTS = [
    ("Гель Sa 5л (Super)", 1350),
    ("Гель Sa 5л (Bablegum)", 1350),
    ("Гель Sa 5л (Лимон)", 1350),
    ("Гель Sa 5л (Белый)", 1350),
    ("Гель Sa 5л (Голубой)", 1350),
    ("Гель Sa 3л (Голубой)", 1200),
    ("Гель Sa 3л (Белый)", 1200),
    ("Средство для посуды 1л (Лимон)", 550),
]

# --- Пользователи ---
USERS = {
    "admin": {"password": "adminpass", "role": "admin"},
    "manager": {"password": "managerpass", "role": "manager"},
}

# --- Сессии пользователей ---
user_sessions = {}

# --- Хендлер /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите логин:")
    return LOGIN

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login'] = update.message.text
    await update.message.reply_text("Введите пароль:")
    return PASSWORD

async def password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login = context.user_data['login']
    password = update.message.text

    if login in USERS and USERS[login]['password'] == password:
        context.user_data['role'] = USERS[login]['role']
        user_sessions[update.effective_user.id] = {
            "login": login,
            "role": USERS[login]['role']
        }
        await show_menu(update, context)
        return MENU
    else:
        await update.message.reply_text("Неверный логин или пароль. Попробуйте снова: /start")
        return ConversationHandler.END

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = context.user_data['role']
    if role == "admin":
        keyboard = [["📄 Выгрузить в Excel"], ["📋 Показать заказы"], ["🔑 Сменить пароль"]]
    else:
        keyboard = [["🛒 Новый заказ"], ["📋 Мои заказы"]]
    await update.message.reply_text("Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    role = context.user_data.get('role')

    if role == 'admin':
        if text == "📄 Выгрузить в Excel":
            await export_excel(update)
        elif text == "📋 Показать заказы":
            await show_orders(update)
        elif text == "🔑 Сменить пароль":
            await update.message.reply_text("Функция смены пароля пока не реализована.")
    else:
        if text == "🛒 Новый заказ":
            context.user_data['order'] = {}
            return await show_products(update, context)
        elif text == "📋 Мои заказы":
            await show_orders(update)
    return MENU

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[product[0]] for product in PRODUCTS] + [["Готово"]]
    await update.message.reply_text("Выберите товар:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return ORDER

async def order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_name = update.message.text
    if product_name == "Готово":
        return await ask_delivery_date(update, context)

    context.user_data['current_product'] = product_name
    await update.message.reply_text(f"Введите количество бутылок для товара: {product_name}")
    return QUANTITY

async def quantity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity = int(update.message.text)
    product_name = context.user_data['current_product']

    if 'order' not in context.user_data:
        context.user_data['order'] = {}
    context.user_data['order'][product_name] = context.user_data['order'].get(product_name, 0) + quantity

    return await show_products(update, context)

async def ask_delivery_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Сегодня"], ["Завтра"], ["Послезавтра"]]
    await update.message.reply_text("Выберите дату доставки:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return DELIVERY_DATE

async def delivery_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = update.message.text
    today = datetime.today()
    if date_str == "Сегодня":
        delivery_date = today
    elif date_str == "Завтра":
        delivery_date = today + timedelta(days=1)
    else:
        delivery_date = today + timedelta(days=2)

    context.user_data['delivery_date'] = delivery_date.strftime("%Y-%m-%d")
    await update.message.reply_text("Введите номер телефона:", reply_markup=ReplyKeyboardRemove())
    return PHONE

async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("Введите название магазина:")
    return SHOP_NAME

async def shop_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop'] = update.message.text

    # Сохраняем заказ
    await save_order(update, context)

    await update.message.reply_text("Заказ успешно сохранён!", reply_markup=ReplyKeyboardMarkup([["🛒 Новый заказ"], ["📋 Мои заказы"]], resize_keyboard=True))
    return MENU

async def save_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = context.user_data['order']
    phone = context.user_data['phone']
    shop = context.user_data['shop']
    delivery_date = context.user_data['delivery_date']
    total = 0
    for name, qty in items.items():
        price = dict(PRODUCTS).get(name, 0)
        total += price * qty

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product TEXT,
                quantity INTEGER,
                price INTEGER,
                phone TEXT,
                shop TEXT,
                delivery_date TEXT,
                timestamp TEXT
            )
        """)
        for name, qty in items.items():
            price = dict(PRODUCTS).get(name, 0)
            await db.execute("""
                INSERT INTO orders (user_id, product, quantity, price, phone, shop, delivery_date, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, name, qty, price, phone, shop, delivery_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()

async def show_orders(update: Update):
    user_id = update.effective_user.id
    is_admin = user_sessions.get(user_id, {}).get("role") == "admin"

    async with aiosqlite.connect("orders.db") as db:
        if is_admin:
            cursor = await db.execute("SELECT * FROM orders ORDER BY timestamp DESC LIMIT 10")
        else:
            cursor = await db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (user_id,))
        rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("Заказов не найдено.")
        return

    messages = []
    for row in rows:
        _, _, product, quantity, price, phone, shop, delivery, ts = row
        msg = f"🛍️ {product}\nКол-во: {quantity} бутылок\nЦена: {price} тг\nМагазин: {shop}\nТел: {phone}\nДата доставки: {delivery}\nСоздан: {ts}"
        messages.append(msg)

    for msg in messages:
        await update.message.reply_text(msg)

async def export_excel(update: Update):
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("SELECT * FROM orders")
        rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("Нет заказов для экспорта.")
        return

    file_path = "orders.xlsx"
    workbook = xlsxwriter.Workbook(file_path)
    sheet = workbook.add_worksheet()
    headers = ["ID", "User ID", "Товар", "Кол-во", "Цена", "Телефон", "Магазин", "Дата доставки", "Создан"]
    for col, header in enumerate(headers):
        sheet.write(0, col, header)
    for row_num, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            sheet.write(row_num, col, value)
    workbook.close()

    with open(file_path, "rb") as f:
        await update.message.reply_document(InputFile(f, filename=file_path))

# --- Основной запуск ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password)],
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler)],
            ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_handler)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_handler)],
            DELIVERY_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delivery_date_handler)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            SHOP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, shop_name_handler)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == '__main__':
    main()
