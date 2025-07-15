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

app = Flask(__name__)
@app.route('/')
def home():
    return "Бот работает!"

def run_keepalive():
    app.run(host="0.0.0.0", port=8080)

(
    CHOOSE_ROLE, SELECT_USER, PASSWORD, MAIN_MENU,
    ADDRESS, SHOP, PRODUCT_QTY, DELIVERY_DATE,
    CHANGE_PASS_LOGIN, CHANGE_PASS_NEW
) = range(10)

user_sessions = {}
BOT_TOKEN = os.getenv("BOT_TOKEN")

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

def main_menu(role):
    if role == "manager":
        keyboard = [["📋 Мои заказы", "🛒 Сделать заказ"], ["🚪 Выйти"]]
    else:
        keyboard = [["📈 Статистика", "📄 Заказы"],
                    ["🔑 Сменить пароль", "💰 Изменить цену"],
                    ["🚪 Выйти"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def export_orders_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, role = user_sessions.get(update.effective_chat.id, (None, None))
    if role != "admin":
        await update.message.reply_text("⛔ Только администратор может выгружать заказы.")
        return MAIN_MENU

    async with aiosqlite.connect("orders.db") as db:
        orders = await db.execute_fetchall("SELECT * FROM orders")
        if not orders:
            await update.message.reply_text("❗ Нет заказов для экспорта.")
            return MAIN_MENU

        wb = xlsxwriter.Workbook("orders.xlsx")
        ws = wb.add_worksheet("Заказы")
        ws.write_row(0, 0, ["ID заказа", "Менеджер", "Дата", "Адрес", "Магазин", "Товар", "Кол-во", "Цена", "Сумма", "Доставка"])

        row = 1
        for order in orders:
            order_id, user_id, date, address, shop, qty, amt, delivery = order
            async with db.execute("SELECT name, price, quantity FROM order_items WHERE order_id = ?", (order_id,)) as item_cursor:
                items = await item_cursor.fetchall()
            for name, price, quantity in items:
                ws.write_row(row, 0, [order_id, user_id, date, address, shop, name, quantity, price, quantity * price, delivery])
                row += 1

        wb.close()

    with open("orders.xlsx", "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename="orders.xlsx"),
            caption="📄 Все заказы (Excel)"
        )
    return MAIN_MENU
    await update.message.reply_text("❌ Неверные данные. Попробуйте снова: /start")
    return ConversationHandler.END

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions:
        await update.message.reply_text("Сначала авторизуйтесь через /start")
        return ConversationHandler.END
    user_id, role = user_sessions[chat_id]
    if text == "🚪 Выйти":
        del user_sessions[chat_id]
        await update.message.reply_text("Вы вышли. Введите /start", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if role == "manager":
        if text == "🛒 Сделать заказ":
            context.user_data['order_items'] = []
            context.user_data['product_index'] = 0
            await update.message.reply_text("Введите адрес:")
            return ADDRESS
        elif text == "📋 Мои заказы":
            return await show_my_orders(update, user_id)
    if role == "admin":
        if text == "🔑 Сменить пароль":
            await update.message.reply_text("Введите логин менеджера:")
            return CHANGE_PASS_LOGIN
        elif text == "📄 Заказы":
            return await export_orders_excel(update, context)
        elif text == "📈 Статистика":
            await update.message.reply_text("Функция статистики в разработке.")
        else:
            await update.message.reply_text("Выберите действие.")
    return MAIN_MENU

async def get_address(update, context):
    context.user_data['address'] = update.message.text.strip()
    await update.message.reply_text("Введите название магазина:")
    return SHOP

async def get_shop(update, context):
    context.user_data['shop'] = update.message.text.strip()
    return await ask_product(update, context)

async def ask_product(update, context):
    index = context.user_data['product_index']
    if index >= len(PRODUCTS):
        return await finalize_order(update, context)
    name, price = PRODUCTS[index]
    await update.message.reply_text(f"{name} — {price} тг\nСколько коробок? (0 — пропустить)")
    return PRODUCT_QTY

async def get_product_qty(update, context):
    qty = update.message.text.strip()
    if not qty.isdigit():
        await update.message.reply_text("Введите число")
        return PRODUCT_QTY
    qty = int(qty)
    index = context.user_data['product_index']
    if qty > 0:
        context.user_data['order_items'].append((PRODUCTS[index][0], PRODUCTS[index][1], qty))
    context.user_data['product_index'] += 1
    return await ask_product(update, context)

async def finalize_order(update, context):
    items = context.user_data['order_items']
    lines = []
    total = 0
    for name, price, qty in items:
        sum_ = qty * price
        total += sum_
        lines.append(f"• {name} — {qty} x {price} = {sum_} тг")
    context.user_data['amount'] = str(total)
    context.user_data['quantity'] = str(sum(q for _, _, q in items))
    await update.message.reply_text("\n".join(["🧼 Заказ:"] + lines + [f"💰 Итого: {total} тг"]))
    keyboard = [["Сегодня"], ["Завтра"], ["Послезавтра"]]
    await update.message.reply_text("Выберите дату доставки:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
    return DELIVERY_DATE

async def get_delivery(update, context):
    text = update.message.text.strip().lower()
    delta = {"сегодня": 0, "завтра": 1, "послезавтра": 2}.get(text)
    if delta is None:
        await update.message.reply_text("Выберите из вариантов.")
        return DELIVERY_DATE
    delivery = datetime.today() + timedelta(days=delta)
    context.user_data['delivery'] = delivery.strftime("%Y-%m-%d")
    user_id, _ = user_sessions[update.effective_chat.id]
    async with aiosqlite.connect("orders.db") as db:
        cursor = await db.execute("""INSERT INTO orders (user_id, date, address, shop, quantity, amount, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", (
            user_id,
            context.user_data['date'],
            context.user_data['address'],
            context.user_data['shop'],
            context.user_data['quantity'],
            context.user_data['amount'],
            context.user_data['delivery']
        ))
        order_id = cursor.lastrowid
        for name, price, qty in context.user_data['order_items']:
            await db.execute("INSERT INTO order_items (order_id, name, price, quantity) VALUES (?, ?, ?, ?)", (order_id, name, price, qty))
        await db.commit()
    await update.message.reply_text("✅ Заказ сохранён!", reply_markup=main_menu("manager"))
    return MAIN_MENU

async def show_my_orders(update, user_id):
    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT id, date, shop, quantity, amount FROM orders WHERE user_id = ?", (user_id,)) as cursor:
            orders = await cursor.fetchall()
        if not orders:
            await update.message.reply_text("Нет заказов.")
            return MAIN_MENU
        result = []
        for order in orders:
            order_id, date, shop, qty, amt = order
            result.append(f"📅 {date} | 🏪 {shop} | 📦 {qty} | 💰 {amt} тг")
            async with db.execute("SELECT name, quantity, price FROM order_items WHERE order_id = ?", (order_id,)) as items:
                for name, q, p in await items.fetchall():
                    result.append(f"  • {name} — {q} x {p}")
    await update.message.reply_text("\n".join(result))
    return MAIN_MENU

async def export_orders_excel(update, context):
    user_id, role = user_sessions.get(update.effective_chat.id, (None, None))
    if role != "admin":
        await update.message.reply_text("⛔ Только администратор может выгружать заказы.")
        return MAIN_MENU

    async with aiosqlite.connect("orders.db") as db:
        orders = await db.execute_fetchall("SELECT * FROM orders")
        if not orders:
            await update.message.reply_text("❗ Нет заказов для экспорта.")
            return MAIN_MENU

        wb = xlsxwriter.Workbook("orders.xlsx")
        ws = wb.add_worksheet("Заказы")
        headers = ["ID", "UserID", "Дата", "Адрес", "Магазин", "Кол-во", "Сумма", "Доставка"]
        for col, h in enumerate(headers):
            ws.write(0, col, h)

        for row, order in enumerate(orders, start=1):
            for col, cell in enumerate(order):
                ws.write(row, col, cell)

        wb.close()

    with open("orders.xlsx", "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename="orders.xlsx"),
            caption="📄 Все заказы (Excel)"
        )
    return MAIN_MENU

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

def init_db():
    import sqlite3
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT,
        address TEXT, shop TEXT, quantity TEXT, amount TEXT, delivery TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY, order_id INTEGER,
        name TEXT, price INTEGER, quantity INTEGER
    )""")
    users = [("manager1", "1111", "manager"), ("manager2", "2222", "manager"), ("manager3", "3333", "manager"), ("admin", "0000", "admin")]
    for u in users:
        c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", u)
    conn.commit()
    conn.close()

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
            ADDRESS: [MessageHandler(filters.TEXT, get_address)],
            SHOP: [MessageHandler(filters.TEXT, get_shop)],
            PRODUCT_QTY: [MessageHandler(filters.TEXT, get_product_qty)],
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
