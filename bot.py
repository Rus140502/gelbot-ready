import os
import threading
import aiosqlite
import csv
from io import StringIO
from flask import Flask
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
)
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
    await update.message.reply_text("✅ Авторизация успешна", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Новый заказ
async def new_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT code FROM managers WHERE is_authenticated = 1") as cursor:
            user = await cursor.fetchone()
            if not user:
                await update.message.reply_text("❌ Вы не авторизованы. Введите /auth")
                return ConversationHandler.END
            context.user_data["manager_code"] = user[0]

    await update.message.reply_text("📅 Введите дату заявки:")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    await update.message.reply_text("📍 Введите адрес магазина:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    await update.message.reply_text("🏪 Введите название магазина:")
    return SHOP

async def get_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["shop"] = update.message.text
    await update.message.reply_text("📦 Введите количество товара:")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quantity"] = update.message.text
    await update.message.reply_text("💰 Введите сумму товара:")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["amount"] = update.message.text
    await update.message.reply_text("🚚 Введите дату поставки:")
    return DELIVERY_DATE

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["delivery"] = update.message.text
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            INSERT INTO orders (manager_code, date, address, shop, quantity, amount, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            context.user_data["manager_code"],
            context.user_data["date"],
            context.user_data["address"],
            context.user_data["shop"],
            context.user_data["quantity"],
            context.user_data["amount"],
            context.user_data["delivery"]
        ))
        await db.commit()
    await update.message.reply_text("✅ Заявка сохранена!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Просмотр заявок
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT code FROM managers WHERE is_authenticated = 1") as cursor:
            row = await cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ Вы не авторизованы.")
                return
            manager_code = row[0]

        async with db.execute("""
            SELECT date, address, shop, quantity, amount, delivery
            FROM orders WHERE manager_code = ?
        """, (manager_code,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("У вас пока нет заявок.")
        return

    buttons = [["↩️ В меню"]]
    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    text = "\n\n".join([
        f"📅 {r[0]}\n📍 {r[1]}\n🏪 {r[2]}\n📦 {r[3]} шт\n💰 {r[4]} тг\n🚚 {r[5]}"
        for r in rows
    ])
    await update.message.reply_text(f"Ваши заявки:\n\n{text}", reply_markup=markup)

# Экспорт в CSV
async def export_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT * FROM orders") as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("Нет данных для экспорта.")
        return

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Manager", "Date", "Address", "Shop", "Quantity", "Amount", "Delivery"])
    writer.writerows(rows)
    output.seek(0)

    await update.message.reply_document(InputFile(output, filename="orders.csv"))

# Старт
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [["/auth", "/neworder"], ["/myorders", "/export"]]
    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("Добро пожаловать!\nВыберите действие:", reply_markup=markup)

# Инициализация БД
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
    application.add_handler(CommandHandler("myorders", my_orders))
    application.add_handler(CommandHandler("export", export_orders))
    application.add_handler(auth_conv)
    application.add_handler(neworder_conv)

    threading.Thread(target=run_keepalive).start()
    application.run_polling()

if __name__ == "__main__":
    main()
