import os
import asyncio
import aiosqlite
import threading
from flask import Flask
from telegram.ext import Application  # ✅ новый код
from telegram.ext import Application, CommandHandler, ContextTypes

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Бот работает!"

def run_keepalive():
    app_flask.run(host="0.0.0.0", port=8080)

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот по приему заказов.")

async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    threading.Thread(target=run_keepalive).start()
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
