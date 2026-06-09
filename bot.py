import logging
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config.settings import TELEGRAM_TOKEN
from handlers.bet_handler import handle_bet_image, cmd_start, cmd_help
from handlers.update_handler import cmd_update
from handlers.stats_handler import cmd_stats
from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot funcionando al 100%"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("actualizar", cmd_update))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.PHOTO, handle_bet_image))
    
    threading.Thread(target=run_server).start()

    print("🤖 Bot iniciado. Esperando capturas...")
    app.run_polling()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

if __name__ == "__main__":
    main()
