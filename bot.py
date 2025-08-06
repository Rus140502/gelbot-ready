import os
import logging
import aiosqlite
import xlsxwriter
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          ContextTypes, ConversationHandler)

# Состояния
ADDRESS, PHONE, SHOP, PRODUCT_QTY, DELIVERY_DATE = range(5)

# Продукты
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

# Пользователи
user_sessions = {}

# Логгирование
logging.basicConfig(level=logging.INFO)

# Главное меню
MAIN_MENU = "MAIN_MENU"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добро пожаловать! Введите адрес доставки:")
    return ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text.strip()
    await update.message.reply_text("Введите номер телефона:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.replace("+", "").replace("-", "").isdigit():
        await update.message.reply_text("Введите корректный номер телефона.")
        return PHONE
    context.user_data['phone'] = phone
    await update.message.reply_text("Введите название магазина:")
    return SHOP

async def get_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop'] = update.message.text.strip()
    context.user_data['items'] = []
    context.user_data['quantity'] = 0
    context.user_data['amount'] = 0
    context.user_data['product_index'] = 0
    return await ask_product(update, context)

async def ask_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    index = context.user_data['product_index']
    if index >= len(PRODUCTS):
        return await ask_delivery_date(update, context)
    name, price = PRODUCTS[index]
    await update.message.reply_text(f"{name} — {price} тг\nСколько бутылок? (0 — пропустить)")
    return PRODUCT_QTY

async def handle_product_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_text = update.message.text.strip()
    if not qty_text.isdigit():
        await update.message.reply_text("Введите число бутылок.")
        return PRODUCT_QTY

    qty = int(qty_text)
    index = context.user_data['product_index']
    name, price = PRODUCTS[index]
    if qty > 0:
        context.user_data['items'].append((name, price, qty))
        context.user_data['quantity'] += qty
        context.user_data['amount'] += price * qty

    context.user_data['product_index'] += 1
    return await ask_product(update, context)

async def ask_delivery_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Сегодня", "Завтра", "Послезавтра"]]
    await update.message.reply_text("Выберите дату доставки:",
                                    reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return DELIVERY_DATE

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    today = datetime.now().date()
    if choice == "Сегодня":
        delivery_date = today
    elif choice == "Завтра":
        delivery_date = today + timedelta(days=1)
    elif choice == "Послезавтра":
        delivery_date = today + timedelta(days=2)
    else:
        await update.message.reply_text("Пожалуйста, выберите из предложенных вариантов.")
        return DELIVERY_DATE

    context.user_data['delivery'] = str(delivery_date)
    user_id = update.effective_chat.id

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                address TEXT,
                phone TEXT,
                shop TEXT,
                quantity INTEGER,
                amount INTEGER,
                delivery TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                name TEXT,
                price INTEGER,
                quantity INTEGER
            )
        """)
        await db.commit()

        cursor = await db.execute("""
            INSERT INTO orders (user_id, date, address, phone, shop, quantity, amount, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            str(today),
            context.user_data['address'],
            context.user_data['phone'],
            context.user_data['shop'],
            context.user_data['quantity'],
            context.user_data['amount'],
            context.user_data['delivery']
        ))
        order_id = cursor.lastrowid

        for name, price, qty in context.user_data['items']:
            await db.execute("""
                INSERT INTO order_items (order_id, name, price, quantity)
                VALUES (?, ?, ?, ?)
            """, (order_id, name, price, qty))
        await db.commit()

    await update.message.reply_text("✅ Заказ успешно оформлен!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def export_orders_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    role = "admin"  # Упростим для примера

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
        ws.write_row(0, 0, [
            "ID заказа", "Менеджер", "Дата", "Адрес", "Телефон", "Магазин",
            "Товар", "Кол-во", "Цена", "Сумма", "Доставка"
        ])

        row = 1
        for order in orders:
            order_id, user_id, date, address, phone, shop, qty, amt, delivery = order
            async with db.execute("SELECT name, price, quantity FROM order_items WHERE order_id = ?", (order_id,)) as item_cursor:
                items = await item_cursor.fetchall()
            for name, price, quantity in items:
                ws.write_row(row, 0, [
                    order_id, user_id, date, address, phone, shop,
                    name, quantity, price, quantity * price, delivery
                ])
                row += 1
        wb.close()

    with open("orders.xlsx", "rb") as f:
        await update.message.reply_document(InputFile(f, filename="orders.xlsx"), caption="📄 Все заказы (Excel)")
    return MAIN_MENU

def main():
    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            SHOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_shop)],
            PRODUCT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_product_qty)],
            DELIVERY_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("export", export_orders_excel))

    app.run_polling()

if __name__ == '__main__':
    main()
