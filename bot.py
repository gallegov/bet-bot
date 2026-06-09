import logging
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config.settings import TELEGRAM_TOKEN
from handlers.bet_handler import handle_bet_image, cmd_start, cmd_help
from handlers.update_handler import cmd_update, callback_resolver
from handlers.stats_handler import cmd_stats
from handlers.surebets_handler import cmd_resolver_surebets, callback_surebet_resolver
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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

    # ── Comandos ────────────────────────────────────────────────────────────
    bot_app.add_handler(CommandHandler("start",             cmd_start))
    bot_app.add_handler(CommandHandler("help",              cmd_help))
    bot_app.add_handler(CommandHandler("actualizar",        cmd_update))
    bot_app.add_handler(CommandHandler("stats",             cmd_stats))
    bot_app.add_handler(CommandHandler("resolver_surebets", cmd_resolver_surebets))

    # ── Mensajes con foto (enrutado internamente por tema) ──────────────────
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_bet_image))

    # ── Callbacks de botones inline ─────────────────────────────────────────
    bot_app.add_handler(CallbackQueryHandler(callback_resolver,        pattern="^res_"))
    bot_app.add_handler(CallbackQueryHandler(callback_surebet_resolver, pattern="^sb_WIN_"))

    threading.Thread(target=run_server).start()

    print("🤖 Bot iniciado. Esperando capturas...")
    bot_app.run_polling()

if __name__ == "__main__":
    main()
