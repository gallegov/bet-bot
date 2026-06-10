import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from services.vision_service import extract_bet_from_image
from services.sheets_service import add_bet
from utils.topic_filter import check_topic, log_thread_id, TEMA_CAPTURAS
from utils.security import security_check
from config.settings import TOPIC_SUREBETS

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    await update.message.reply_text(
        "👋 *Bot de Apuestas activo*\n\n"
        "📸 Mándame una captura de pantalla de una apuesta y la registro automáticamente.\n\n"
        "Comandos:\n"
        "• /actualizar — comprueba resultados pendientes y actualiza el Excel\n"
        "• /stats — resumen de tu contabilidad\n"
        "• /help — ayuda",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    await update.message.reply_text(
        "ℹ️ *Cómo usar el bot:*\n\n"
        "1. Haz una captura de la apuesta en la app de tu casa de apuestas\n"
        "2. Envíamela como foto\n"
        "3. Yo extraigo los datos y los registro en Google Sheets\n\n"
        "Cuando quieras actualizar resultados:\n"
        "→ Escribe /actualizar\n\n"
        "Consulta tu saldo:\n"
        "→ Escribe /stats",
        parse_mode="Markdown"
    )

async def handle_bet_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    log_thread_id(update)

    # Enrutamiento: fotos en el tema de Surebets van a su propio handler
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    if TOPIC_SUREBETS and thread_id == TOPIC_SUREBETS:
        from handlers.surebets_handler import handle_surebet_image
        await handle_surebet_image(update, context)
        return

    if not await check_topic(update, TEMA_CAPTURAS):
        return

    msg = await update.message.reply_text("🔍 Analizando la captura...")

    # Descargar imagen
    photo = update.message.photo[-1]
    file  = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())

    await msg.edit_text("🧠 Extrayendo datos con IA...")

    # Claude Vision es síncrono — lo ejecutamos en un thread para no bloquear
    try:
        bet_data = await asyncio.to_thread(extract_bet_from_image, image_bytes)
    except Exception as e:
        await msg.edit_text(f"❌ Error al analizar la imagen: {e}")
        return

    if not bet_data:
        await msg.edit_text(
            "❌ No pude leer los datos de la captura.\n"
            "Asegúrate de que se vean claramente: evento, cuota e importe."
        )
        return

    bet_data.setdefault("casa", "Desconocida")
    bet_data.setdefault("deporte", "Fútbol")

    await msg.edit_text("📊 Guardando en Google Sheets...")

    # Sheets también es síncrono — mismo tratamiento
    try:
        bet_id = await asyncio.to_thread(add_bet, bet_data)
    except Exception as e:
        await msg.edit_text(f"❌ Error al guardar en Sheets: {e}")
        return

    cuota   = bet_data.get("cuota", "?")
    importe = bet_data.get("importe", "?")
    try:
        posible_ganancia = round(float(cuota) * float(importe), 2)
    except (TypeError, ValueError):
        posible_ganancia = "?"

    await msg.edit_text(
        f"✅ *Apuesta #{bet_id} registrada*\n\n"
        f"🏟 {bet_data.get('evento', '?')}\n"
        f"🎯 {bet_data.get('descripcion', '?')}\n"
        f"📅 {bet_data.get('fecha_partido', 'Fecha no detectada')}\n"
        f"🏠 {bet_data.get('casa', '?')} · {bet_data.get('deporte', '?')}\n"
        f"📈 Cuota: *{cuota}* · Importe: *{importe}€*\n"
        f"💰 Ganancia potencial: *{posible_ganancia}€*\n\n"
        f"Estado: ⏳ PENDIENTE",
        parse_mode="Markdown"
    )
