import os
import threading
import aiosqlite
import xlsxwriter
from flask import Flask
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

BOT_TOKEN = "8042271583:AAHNBkjbd4BtbqS_djLsmywgqS5Y6sONnVU"  # 🔁 ВСТАВЬ СЮДА СВОЙ ТОКЕН

USERS = {
    "admin": {"password": "adminpass", "role": "admin"},
    "manager": {"password": "managerpass", "role": "manager"},
}

user_sessions = {}  # user_id: (username, role)
user_passwords = USERS.copy()

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

LOGIN_USERNAME, LOGIN_PASSWORD, MAIN_MENU, SELECT_PRODUCT, SELECT_QUANTITY, SELECT_DATE, ENTER_PHONE, CHANGE_PASSWORD = range(8)

# --- Авторизация ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите логин:")
    return LOGIN_USERNAME

async def login_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text
    await update.message.reply_text("Введите пароль:")
    return LOGIN_PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data["username"]
    password = update.message.text
    user = USERS.get(username)
    if user and user["password"] == password:
        user_sessions[update.effective_chat.id] = (username, user["role"])
        await update.message.reply_text(f"Добро пожаловать в магазин Sa Soap, {username}!")
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text("Неверный логин или пароль. Попробуйте /start.")
        return ConversationHandler.END

# --- Главное меню ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, role = user_sessions.get(update.effective_chat.id, (None, None))
    if role == "admin":
        keyboard = [
            ["📦 Заказ", "📄 Выгрузка Excel"],
            ["📋 Показать заказы", "🔑 Сменить пароль"],
            ["🚪 Выйти"]
        ]
    else:
        keyboard = [
            ["📦 Заказ", "📋 Мои заказы"],
            ["🚪 Выйти"]
        ]
    await update.message.reply_text("Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return MAIN_MENU

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    role = user_sessions.get(update.effective_chat.id, (None, None))[1]

    if text == "📦 Заказ":
        context.user_data["cart"] = {}
        return await show_product_buttons(update)

    elif text == "📄 Выгрузка Excel" and role == "admin":
        return await export_orders(update)

    elif text == "📋 Показать заказы" and role == "admin":
        return await show_orders(update)

    elif text == "📋 Мои заказы" and role == "manager":
        return await show_orders(update)

    elif text == "🔑 Сменить пароль" and role == "admin":
        await update.message.reply_text("Введите новый пароль:")
        return CHANGE_PASSWORD

    elif text == "🚪 Выйти":
        user_sessions.pop(update.effective_chat.id, None)
        await update.message.reply_text("Вы вышли из аккаунта. Введите логин: /start", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    else:
        await update.message.reply_text("Пожалуйста, выберите доступную опцию.")
        return MAIN_MENU

# --- Смена пароля (только админ) ---
async def change_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_pass = update.message.text.strip()
    USERS["admin"]["password"] = new_pass
    await update.message.reply_text("Пароль успешно изменён.")
    return await show_main_menu(update, context)

# --- Заказ ---
async def show_product_buttons(update: Update):
    keyboard = [[product[0]] for product in PRODUCTS]
    keyboard.append(["Готово"])
    await update.message.reply_text("Выберите товар:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return SELECT_PRODUCT

async def handle_product_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "Готово":
        if not context.user_data["cart"]:
            await update.message.reply_text("Корзина пуста. Выберите хотя бы один товар.")
            return SELECT_PRODUCT
        keyboard = [["Сегодня", "Завтра", "Послезавтра"]]
        await update.message.reply_text("Выберите дату доставки:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return SELECT_DATE

    product_names = [name for name, _ in PRODUCTS]
    if choice not in product_names:
        await update.message.reply_text("Выберите товар из списка.")
        return SELECT_PRODUCT

    context.user_data["selected_product"] = choice
    await update.message.reply_text("Введите количество (в бутылках):")
    return SELECT_QUANTITY

async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        product = context.user_data["selected_product"]
        context.user_data["cart"][product] = context.user_data["cart"].get(product, 0) + qty
        await update.message.reply_text(f"Добавлено: {qty} шт. {product}")
        return await show_product_buttons(update)
    except:
        await update.message.reply_text("Введите корректное число.")
        return SELECT_QUANTITY

async def handle_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_map = {"Сегодня": 0, "Завтра": 1, "Послезавтра": 2}
    choice = update.message.text.strip()
    if choice not in date_map:
        await update.message.reply_text("Выберите дату из списка.")
        return SELECT_DATE

    delivery_date = (datetime.now() + timedelta(days=date_map[choice])).strftime("%Y-%m-%d")
    context.user_data["delivery_date"] = delivery_date
    await update.message.reply_text("Введите номер телефона:", reply_markup=ReplyKeyboardRemove())
    return ENTER_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    username, _ = user_sessions.get(update.effective_chat.id, (None, None))
    delivery_date = context.user_data["delivery_date"]
    cart = context.user_data["cart"]
    total = 0

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                item TEXT,
                quantity INTEGER,
                price INTEGER,
                delivery_date TEXT,
                phone TEXT
            )
        """)
        for item, qty in cart.items():
            price = dict(PRODUCTS)[item]
            total += qty * price
            await db.execute(
                "INSERT INTO orders (username, item, quantity, price, delivery_date, phone) VALUES (?, ?, ?, ?, ?, ?)",
                (username, item, qty, price, delivery_date, phone)
            )
        await db.commit()

    await update.message.reply_text(f"✅ Заказ оформлен.\nСумма: {total} тг\nДата доставки: {delivery_date}")
    return await show_main_menu(update, context)

# --- Выгрузка в Excel (только админ) ---
async def export_orders(update: Update):
    file_path = "orders_export.xlsx"
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT username, item, quantity, price, delivery_date, phone FROM orders") as cursor:
            rows = await cursor.fetchall()

    workbook = xlsxwriter.Workbook(file_path)
    worksheet = workbook.add_worksheet()
    headers = ["Пользователь", "Товар", "Кол-во", "Цена", "Дата", "Телефон"]
    for col, header in enumerate(headers):
        worksheet.write(0, col, header)
    for row_idx, row in enumerate(rows, start=1):
        for col_idx, value in enumerate(row):
            worksheet.write(row_idx, col_idx, value)
    workbook.close()

    with open(file_path, "rb") as f:
        await update.message.reply_document(document=InputFile(f, file_path))
    os.remove(file_path)
    return MAIN_MENU

# --- Просмотр заказов сообщением ---
async def show_orders(update: Update):
    username, role = user_sessions.get(update.effective_chat.id, (None, None))
    async with aiosqlite.connect("orders.db") as db:
        if role == "admin":
            query = "SELECT username, item, quantity, price, delivery_date, phone FROM orders ORDER BY id DESC LIMIT 10"
            args = ()
        else:
            query = "SELECT item, quantity, price, delivery_date, phone FROM orders WHERE username = ? ORDER BY id DESC LIMIT 10"
            args = (username,)
        async with db.execute(query, args) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("Заказов пока нет.")
        return MAIN_MENU

    messages = []
    for row in rows:
        if role == "admin":
            u, item, qty, price, date, phone = row
            msg = f"👤 {u}\n📦 {item} x {qty} шт\n💰 {qty * price} тг\n📅 {date}\n📞 {phone}"
        else:
            item, qty, price, date, phone = row
            msg = f"📦 {item} x {qty} шт\n💰 {qty * price} тг\n📅 {date}\n📞 {phone}"
        messages.append(msg)

    await update.message.reply_text("\n\n".join(messages))
    return MAIN_MENU

# --- Flask Keepalive ---
app = Flask(__name__)
@app.route("/")
def home():
    return "Бот работает"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# --- Main ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_username)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu)],
            SELECT_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_choice)],
            SELECT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity)],
            SELECT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_date_selection)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            CHANGE_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_password)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app_bot.add_handler(conv_handler)
    app_bot.run_polling()
