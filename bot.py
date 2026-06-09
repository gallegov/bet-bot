import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config.settings import TELEGRAM_TOKEN
from handlers.bet_handler import handle_bet_image, cmd_start, cmd_help
from handlers.update_handler import cmd_update
from handlers.stats_handler import cmd_stats

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

    print("🤖 Bot iniciado. Esperando capturas...")
    app.run_polling()

if __name__ == "__main__":
    main()
