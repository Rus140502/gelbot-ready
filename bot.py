import os
import threading
import aiosqlite
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

def run_keepalive():
    app.run(host="0.0.0.0", port=8080)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Состояния диалога
AUTH, DATE, ADDRESS, SHOP, QUANTITY, AMOUNT, DELIVERY_DATE = range(7)

# Авторизация
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["1", "2", "3"]]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Выберите свой номер менеджера:", reply_markup=markup)
    return AUTH

async def auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE managers SET is_authenticated = 1 WHERE code = ?", (code,))
        await db.commit()
    await update.message.reply_text("Авторизация успешна ✅", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Проверка авторизации
async def is_user_authorized(user_id):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT is_authenticated FROM managers WHERE code = ?", (str(user_id),)) as cursor:
            row = await cursor.fetchone()
            return row and row[0] == 1

# Новый заказ
async def new_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT is_authenticated FROM managers WHERE is_authenticated = 1") as cursor:
            found = await cursor.fetchone()
            if not found:
                await update.message.reply_text("Вы не авторизованы. Введите /auth")
                return ConversationHandler.END
    await update.message.reply_text("Введите дату заявки (например, 2025-07-10):")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("Введите адрес магазина:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("Введите название магазина:")
    return SHOP

async def get_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["shop"] = update.message.text
    await update.message.reply_text("Введите количество товара:")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quantity"] = update.message.text
    await update.message.reply_text("Введите сумму товара:")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["amount"] = update.message.text
    await update.message.reply_text("Введите дату поставки:")
    return DELIVERY_DATE

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["delivery"] = update.message.text
    # Сохраняем в базу
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            INSERT INTO orders (manager_code, date, address, shop, quantity, amount, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "MANAGER",  # можно заменить на user_id или manager name
            context.user_data["date"],
            context.user_data["address"],
            context.user_data["shop"],
            context.user_data["quantity"],
            context.user_data["amount"],
            context.user_data["delivery"]
        ))
        await db.commit()
    await update.message.reply_text("Заявка сохранена ✅")
    return ConversationHandler.END

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот по приему заказов.\nВведи /auth для входа.")

def init_db():
    import sqlite3
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS managers (
        code TEXT PRIMARY KEY,
        is_authenticated INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manager_code TEXT,
        date TEXT,
        address TEXT,
        shop TEXT,
        quantity TEXT,
        amount TEXT,
        delivery TEXT
    )""")
    # Добавляем 3 менеджеров
    for code in ("1", "2", "3"):
        c.execute("INSERT OR IGNORE INTO managers (code) VALUES (?)", (code,))
    conn.commit()
    conn.close()

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", auth)],
        states={AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_code)]},
        fallbacks=[]
    )

    neworder_conv = ConversationHandler(
        entry_points=[CommandHandler("neworder", new_order)],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            SHOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_shop)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            DELIVERY_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery)],
        },
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(auth_conv)
    application.add_handler(neworder_conv)

    threading.Thread(target=run_keepalive).start()
    application.run_polling()

if __name__ == "__main__":
    main()
