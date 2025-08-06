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

BOT_TOKEN = "8042271583:AAHNBkjbd4BtbqS_djLsmywgqS5Y6sONnVU"

# --- Пользователи и роли ---
USERS = {
    "admin": {"password": "adminpass", "role": "admin"},
    "manager": {"password": "managerpass", "role": "manager"},
}

user_sessions = {}  # user_id: (username, role)

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

LOGIN_USERNAME, LOGIN_PASSWORD, MAIN_MENU, SELECT_PRODUCTS, SELECT_DATE, ENTER_PHONE = range(6)

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
        await update.message.reply_text(f"Добро пожаловать, {username}!")
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text("Неверный логин или пароль. Попробуйте /start.")
        return ConversationHandler.END

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, role = user_sessions.get(update.effective_chat.id, (None, None))
    if role == "admin":
        keyboard = [["📦 Заказ", "📄 Выгрузить заказы (Excel)"]]
    else:
        keyboard = [["📦 Заказ"]]
    await update.message.reply_text("Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return MAIN_MENU

# --- Заказ ---
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📦 Заказ":
        context.user_data["cart"] = {}
        return await show_products(update, context)
    elif text == "📄 Выгрузить заказы (Excel)":
        username, role = user_sessions.get(update.effective_chat.id, (None, None))
        if role != "admin":
            await update.message.reply_text("У вас нет доступа к этой функции.")
            return MAIN_MENU
        return await export_orders(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите доступную опцию.")
        return MAIN_MENU

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_lines = [f"{i+1}. {name} - {price} тг" for i, (name, price) in enumerate(PRODUCTS)]
    message = "Выберите товар, отправив номер и количество через пробел (например: 1 3).\nНапишите 'Готово' для завершения выбора.\n\n" + "\n".join(product_lines)
    await update.message.reply_text(message)
    return SELECT_PRODUCTS

async def handle_product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "готово":
        if not context.user_data["cart"]:
            await update.message.reply_text("Корзина пуста. Пожалуйста, выберите хотя бы один товар.")
            return SELECT_PRODUCTS
        keyboard = [["Сегодня", "Завтра", "Послезавтра"]]
        await update.message.reply_text("Выберите дату доставки:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return SELECT_DATE
    try:
        index, qty = map(int, text.split())
        name, price = PRODUCTS[index - 1]
        context.user_data["cart"][name] = qty
        await update.message.reply_text(f"Добавлено: {qty} бутылки {name}")
    except:
        await update.message.reply_text("Неверный формат. Введите номер товара и количество через пробел.")
    return SELECT_PRODUCTS

async def handle_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_map = {"Сегодня": 0, "Завтра": 1, "Послезавтра": 2}
    choice = update.message.text.strip()
    if choice not in date_map:
        await update.message.reply_text("Выберите дату из предложенных.")
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

    await update.message.reply_text(f"Заказ сохранён. Сумма: {total} тг\nДата доставки: {delivery_date}")
    return await show_main_menu(update, context)

# --- Выгрузка заказов в Excel (только админ) ---
async def export_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_path = "orders_export.xlsx"
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT username, item, quantity, price, delivery_date, phone FROM orders") as cursor:
            rows = await cursor.fetchall()

    workbook = xlsxwriter.Workbook(file_path)
    worksheet = workbook.add_worksheet()
    headers = ["Пользователь", "Товар", "Кол-во бутылок", "Цена за шт.", "Дата доставки", "Телефон"]
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
            SELECT_PRODUCTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_selection)],
            SELECT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_date_selection)],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app_bot.add_handler(conv_handler)
    app_bot.run_polling()
