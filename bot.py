import os
import threading
from flask import Flask
from telegram.ext import Application, CommandHandler

# Flask KeepAlive
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

def run_keepalive():
    app.run(host="0.0.0.0", port=8080)

# Бот-токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Команда /start
async def start(update, context):
    await update.message.reply_text("Привет! Я бот по приему заказов.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    # Flask запускаем в отдельном потоке
    threading.Thread(target=run_keepalive).start()

    # Запуск бота (асинхронно внутри)
    application.run_polling()

if __name__ == "__main__":
    main()
