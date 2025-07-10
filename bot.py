import os
import threading
import aiosqlite
from flask import Flask
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

CHOOSE_ROLE, SELECT_USER, PASSWORD, MAIN_MENU = range(4)

user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[“Менеджер”, “Администратор”]]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Кто вы?", reply_markup=markup)
    return CHOOSE_ROLE

async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text.lower()
    context.user_data['role'] = role

    if role == "менеджер":
        keyboard = [["manager1"], ["manager2"], ["manager3"]]
    else:
        keyboard = [["admin"]]

    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Выберите пользователя:", reply_markup=markup)
    return SELECT_USER

async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['username'] = update.message.text.strip()
    await update.message.reply_text("Введите цифровой пароль:")
    return PASSWORD

async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if not password.isdigit():
        await update.message.reply_text("Пароль должен содержать только цифры. Попробуйте снова.")
        return PASSWORD

    username = context.user_data['username']
    role = context.user_data['role']
    role = "manager" if role == "менеджер" else "admin"

    async with aiosqlite.connect("orders.db") as db:
        async with db.execute(
            "SELECT id FROM users WHERE username = ? AND password = ? AND role = ?",
            (username, password, role)
        ) as cursor:
            user = await cursor.fetchone()
            if user:
                user_id = user[0]
                user_sessions[update.effective_chat.id] = (user_id, role)
                await update.message.reply_text(f"✅ Успешный вход как {role.title()}", reply_markup=ReplyKeyboardMarkup([["Мои заказы", "Сделать заказ"]] if role == "manager" else [["Статистика", "Все заказы"], ["Смена пароля", "Изменить цену"]], resize_keyboard=True))
                return MAIN_MENU
            else:
                await update.message.reply_text("❌ Неверные данные. Попробуйте снова: /start")
                return ConversationHandler.END

async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
            SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_user)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    threading.Thread(target=run_keepalive).start()
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

# Главное меню
def main_menu(role):
    if role == "manager":
        keyboard = [["📋 Мои заказы", "🆕 Сделать заказ"], ["🚪 Выйти"]]
    else:
        keyboard = [["📈 Статистика", "📄 Заказы"], ["🔑 Сменить пароль", "💰 Изменить цену"], ["🚪 Выйти"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Меню обработка
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if chat_id not in user_sessions:
        await update.message.reply_text("Сначала авторизуйтесь через /start")
        return ConversationHandler.END

    user_id, role = user_sessions[chat_id]

    if text == "🚪 Выйти":
        del user_sessions[chat_id]
        await update.message.reply_text("Вы вышли. /start для входа.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if role == "manager":
        if text == "🆕 Сделать заказ":
            await update.message.reply_text("📅 Введите дату (ГГГГ-ММ-ДД):")
            return DATE
        elif text == "📋 Мои заказы":
            return await show_my_orders(update, user_id)

    elif role == "admin":
        if text == "📄 Заказы":
            return await export_orders(update)
        elif text == "📈 Статистика":
            return await manager_stats(update)
        elif text == "🔑 Сменить пароль":
            await update.message.reply_text("Введите логин менеджера:")
            return CHANGE_PASS_LOGIN
        elif text == "💰 Изменить цену":
            await update.message.reply_text("Пока не реализовано.")

    return MAIN_MENU

# --- Менеджер: Сделать заказ ---
async def validate_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except:
        return False

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.message.text.strip()
    if not await validate_date(date):
        await update.message.reply_text("❌ Формат даты неверный. Пример: 2025-07-10")
        return DATE
    context.user_data['date'] = date
    await update.message.reply_text("Введите адрес:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    await update.message.reply_text("Введите название магазина:")
    return SHOP

async def get_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop'] = update.message.text
    await update.message.reply_text("Введите количество:")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = update.message.text.strip()
    if not qty.isdigit():
        await update.message.reply_text("❌ Только цифры!")
        return QUANTITY
    context.user_data['quantity'] = qty
    await update.message.reply_text("Введите сумму:")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = update.message.text.strip()
    if not amt.replace('.', '', 1).isdigit():
        await update.message.reply_text("❌ Только число!")
        return AMOUNT
    context.user_data['amount'] = amt
    await update.message.reply_text("Введите дату поставки (ГГГГ-ММ-ДД):")
    return DELIVERY_DATE

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.message.text.strip()
    if not await validate_date(date):
        await update.message.reply_text("❌ Формат даты неверный. Пример: 2025-07-10")
        return DELIVERY_DATE

    context.user_data['delivery'] = date
    user_id, _ = user_sessions[update.effective_chat.id]
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            INSERT INTO orders (user_id, date, address, shop, quantity, amount, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            context.user_data['date'],
            context.user_data['address'],
            context.user_data['shop'],
            context.user_data['quantity'],
            context.user_data['amount'],
            context.user_data['delivery']
        ))
        await db.commit()

    await update.message.reply_text("✅ Заявка сохранена", reply_markup=main_menu("manager"))
    return MAIN_MENU

# --- Менеджер: Мои заказы ---
async def show_my_orders(update, user_id):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT date, shop, quantity, amount FROM orders WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await update.message.reply_text("У вас нет заказов.")
        return MAIN_MENU
    text = "\n\n".join([f"📅 {r[0]} | 🏪 {r[1]} | 📦 {r[2]} | 💰 {r[3]}" for r in rows])
    await update.message.reply_text(f"Ваши заказы:\n\n{text}")
    return MAIN_MENU

# --- Админ: Экспорт ---
async def export_orders(update):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT * FROM orders") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await update.message.reply_text("Нет заказов.")
        return MAIN_MENU
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User", "Date", "Address", "Shop", "Qty", "Amount", "Delivery"])
    writer.writerows(rows)
    output.seek(0)
    await update.message.reply_document(InputFile(output, filename="orders.csv"))
    return MAIN_MENU

# --- Админ: Статистика ---
async def manager_stats(update):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("""
            SELECT u.username, COUNT(o.id) FROM users u
            LEFT JOIN orders o ON o.user_id = u.id
            WHERE u.role = 'manager'
            GROUP BY u.id
        """) as cursor:
            rows = await cursor.fetchall()
    text = "\n".join([f"👤 {r[0]} — {r[1]} заказов" for r in rows])
    await update.message.reply_text(f"📈 Статистика:\n{text}")
    return MAIN_MENU

# --- Админ: Смена пароля ---
async def change_pass_login(update, context):
    context.user_data['change_login'] = update.message.text.strip()
    await update.message.reply_text("Введите новый пароль:")
    return CHANGE_PASS_NEW

async def change_pass_set(update, context):
    new_pass = update.message.text.strip()
    login = context.user_data['change_login']
    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE users SET password = ? WHERE username = ? AND role = 'manager'", (new_pass, login))
        await db.commit()
    await update.message.reply_text("✅ Пароль изменён", reply_markup=main_menu("admin"))
    return MAIN_MENU

# Инициализация БД
def init_db():
    import sqlite3
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            is_authenticated INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            address TEXT,
            shop TEXT,
            quantity TEXT,
            amount TEXT,
            delivery TEXT
        )
    """)
    for u, p in [("manager1", "pass1"), ("manager2", "pass2"), ("manager3", "pass3"), ("admin", "admin1")]:
        role = "manager" if "manager" in u else "admin"
        c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", (u, p, role))
    conn.commit()
    conn.close()

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ROLE: [MessageHandler(filters.TEXT, choose_role)],
            LOGIN: [MessageHandler(filters.TEXT, get_login)],
            PASSWORD: [MessageHandler(filters.TEXT, get_password)],
            MAIN_MENU: [MessageHandler(filters.TEXT, handle_main_menu)],
            DATE: [MessageHandler(filters.TEXT, get_date)],
            ADDRESS: [MessageHandler(filters.TEXT, get_address)],
            SHOP: [MessageHandler(filters.TEXT, get_shop)],
            QUANTITY: [MessageHandler(filters.TEXT, get_quantity)],
            AMOUNT: [MessageHandler(filters.TEXT, get_amount)],
            DELIVERY_DATE: [MessageHandler(filters.TEXT, get_delivery)],
            CHANGE_PASS_LOGIN: [MessageHandler(filters.TEXT, change_pass_login)],
            CHANGE_PASS_NEW: [MessageHandler(filters.TEXT, change_pass_set)],
        },
        fallbacks=[]
    )

    application.add_handler(conv)
    threading.Thread(target=run_keepalive).start()
    application.run_polling()

if __name__ == "__main__":
    main()
