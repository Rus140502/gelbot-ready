
import os
import csv
import threading
import aiosqlite
from io import StringIO
from flask import Flask
from datetime import datetime
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# --- Flask Keepalive ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Бот работает!"

def run_keepalive():
    app.run(host="0.0.0.0", port=8080)

# --- Константы состояний ---
(
    CHOOSE_ROLE, SELECT_USER, PASSWORD, MAIN_MENU,
    DATE, ADDRESS, SHOP, QUANTITY, AMOUNT, DELIVERY_DATE,
    CHANGE_PASS_LOGIN, CHANGE_PASS_NEW
) = range(12)

user_sessions = {}
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Команда /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Менеджер", "Администратор"]]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Кто вы?", reply_markup=markup)
    return CHOOSE_ROLE

# --- Выбор роли ---
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

# --- Выбор пользователя ---
async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['username'] = update.message.text.strip()
    await update.message.reply_text("Введите цифровой пароль:")
    return PASSWORD

# --- Проверка пароля ---
async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if not password.isdigit():
        await update.message.reply_text("Пароль должен содержать только цифры. Попробуйте снова.")
        return PASSWORD
    username = context.user_data['username']
    role = "manager" if context.user_data['role'] == "менеджер" else "admin"
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute(
            "SELECT id FROM users WHERE username = ? AND password = ? AND role = ?",
            (username, password, role)
        ) as cursor:
            user = await cursor.fetchone()
            if user:
                user_sessions[update.effective_chat.id] = (user[0], role)
                await update.message.reply_text(
                    "Успешный вход!",
                    reply_markup=main_menu(role)
                )
                return MAIN_MENU
            else:
                await update.message.reply_text("Неверные данные. Попробуйте снова: /start")
                return ConversationHandler.END

# --- Главное меню ---
def main_menu(role):
    if role == "manager":
        keyboard = [["📋 Мои заказы", "🆕 Сделать заказ"], ["🚪 Выйти"]]
    else:
        keyboard = [["📈 Статистика", "📄 Заказы"], ["🔑 Сменить пароль", "💰 Изменить цену"], ["🚪 Выйти"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Обработка главного меню ---
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text("Сначала авторизуйтесь через /start")
        return ConversationHandler.END
    user_id, role = user_sessions[chat_id]
    if text == "🚪 Выйти":
        del user_sessions[chat_id]
        await update.message.reply_text("Вы вышли. /start для входа", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if role == "manager":
        if text == "🆕 Сделать заказ":
            await update.message.reply_text("Введите дату заказа (ГГГГ-ММ-ДД):")
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
            await update.message.reply_text("Функция в разработке.")
            return MAIN_MENU
    return MAIN_MENU

# --- Валидация даты ---
async def validate_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except:
        return False

# --- Менеджер: Сделать заказ ---
async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = update.message.text.strip()
    if not await validate_date(date):
        await update.message.reply_text("Неверный формат даты. Пример: 2025-07-10")
        return DATE
    context.user_data['date'] = date
    await update.message.reply_text("Введите адрес:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text.strip()
    await update.message.reply_text("Введите название магазина:")
    return SHOP

async def get_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop'] = update.message.text.strip()
    await update.message.reply_text("Введите количество:")
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = update.message.text.strip()
    if not qty.isdigit():
        await update.message.reply_text("Только цифры!")
        return QUANTITY
    context.user_data['quantity'] = qty
    await update.message.reply_text("Введите сумму:")
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = update.message.text.strip()
    if not amt.replace(".", "", 1).isdigit():
        await update.message.reply_text("Введите корректную сумму.")
        return AMOUNT
    context.user_data['amount'] = amt
    await update.message.reply_text("Введите дату поставки (ГГГГ-ММ-ДД):")
    return DELIVERY_DATE

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delivery = update.message.text.strip()
    if not await validate_date(delivery):
        await update.message.reply_text("Неверный формат даты.")
        return DELIVERY_DATE
    context.user_data['delivery'] = delivery
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
    await update.message.reply_text("✅ Заказ сохранён!", reply_markup=main_menu("manager"))
    return MAIN_MENU

# --- Менеджер: Мои заказы ---
async def show_my_orders(update, user_id):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT date, shop, quantity, amount FROM orders WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await update.message.reply_text("Нет заказов.")
        return MAIN_MENU
    text = "

".join([f"📅 {r[0]} | 🏪 {r[1]} | 📦 {r[2]} | 💰 {r[3]}" for r in rows])
    await update.message.reply_text(f"Ваши заказы:

{text}")
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
    text = "
".join([f"{r[0]} — {r[1]} заказов" for r in rows])
    await update.message.reply_text(f"📈 Статистика:
{text}")
    return MAIN_MENU

# --- Смена пароля ---
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
    await update.message.reply_text("Пароль обновлён!", reply_markup=main_menu("admin"))
    return MAIN_MENU

# --- Инициализация базы данных ---
def init_db():
    import sqlite3
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, address TEXT, shop TEXT, quantity TEXT, amount TEXT, delivery TEXT)")
    users = [("manager1", "1111", "manager"), ("manager2", "2222", "manager"), ("manager3", "3333", "manager"), ("admin", "0000", "admin")]
    for u in users:
        c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", u)
    conn.commit()
    conn.close()

# --- Запуск бота ---
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ROLE: [MessageHandler(filters.TEXT, choose_role)],
            SELECT_USER: [MessageHandler(filters.TEXT, select_user)],
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

    application.add_handler(conv_handler)
    threading.Thread(target=run_keepalive).start()
    application.run_polling()

if __name__ == "__main__":
    main()
