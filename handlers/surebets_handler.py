"""
Handler completo para Surebets.

Flujos:
  1. Foto(s) en TOPIC_SUREBETS  → extrae, valida, guarda dos filas vinculadas
  2. /resolver_surebets          → lista pendientes con botones inline
  3. Callback "sb_WIN_*"         → resuelve el par y edita el mensaje

Gestión de álbumes: Telegram envía cada foto del grupo como update separado
con el mismo media_group_id. Usamos JobQueue para esperar 3s y acumularlas.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.surebets_vision_service import extract_surebet_from_images, validate_surebet
from services.surebets_sheets_service import (
    add_surebet, get_pending_surebets, resolve_surebet, init_surebets_sheet
)
from utils.topic_filter import check_topic, log_thread_id, TEMA_SUREBETS
from utils.security import security_check
from config.settings import TOPIC_SUREBETS

logger = logging.getLogger(__name__)
ALBUM_WAIT = 3.0


# ── 1. Recepción de imágenes ─────────────────────────────────────────────────

async def handle_surebet_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe 1 o 2 fotos y lanza el flujo de extracción."""
    if not await security_check(update, context):
        return
    log_thread_id(update)
    if not await check_topic(update, TEMA_SUREBETS):
        return

    photo = update.message.photo[-1]
    media_group_id = update.message.media_group_id

    # ── Imagen suelta ──────────────────────────────────────────────────────
    if not media_group_id:
        await _process_images(update, context, [photo.file_id])
        return

    # ── Álbum: acumular con JobQueue ───────────────────────────────────────
    cache_key = f"surebet_album_{media_group_id}"
    chat_id   = update.effective_chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    if cache_key not in context.bot_data:
        context.bot_data[cache_key] = {
            "file_ids": [],
            "chat_id":  chat_id,
            "thread_id": thread_id,
        }
        # Job que disparará el procesamiento tras ALBUM_WAIT segundos
        context.job_queue.run_once(
            _flush_album_job,
            when=ALBUM_WAIT,
            data={"cache_key": cache_key},
            name=cache_key,
        )

    context.bot_data[cache_key]["file_ids"].append(photo.file_id)


async def _flush_album_job(context: ContextTypes.DEFAULT_TYPE):
    """Job que procesa el álbum acumulado."""
    data      = context.job.data
    cache_key = data["cache_key"]
    album     = context.bot_data.pop(cache_key, None)

    if not album or not album["file_ids"]:
        return

    file_ids  = album["file_ids"][:2]
    chat_id   = album["chat_id"]
    thread_id = album["thread_id"]

    # Descargar imágenes
    images_bytes = []
    for fid in file_ids:
        file = await context.bot.get_file(fid)
        raw  = await file.download_as_bytearray()
        images_bytes.append(bytes(raw))

    await _run_extraction(context, images_bytes, chat_id, thread_id)


async def _process_images(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           file_ids: list):
    """Para imagen suelta: descarga y procesa directamente."""
    images_bytes = []
    for fid in file_ids:
        file = await context.bot.get_file(fid)
        raw  = await file.download_as_bytearray()
        images_bytes.append(bytes(raw))

    chat_id   = update.effective_chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)
    await _run_extraction(context, images_bytes, chat_id, thread_id)


async def _run_extraction(context: ContextTypes.DEFAULT_TYPE,
                           images_bytes: list, chat_id: int, thread_id: int | None):
    """Núcleo: Claude Vision → validar → guardar → responder."""

    # Inicializar hoja si no existe (primera vez)
    try:
        init_surebets_sheet()
    except Exception as e:
        logger.warning(f"init_surebets_sheet: {e}")

    n = len(images_bytes)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=f"🔍 Analizando {'los boletos' if n > 1 else 'el boleto'}..."
    )

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg.message_id,
        text="🧠 Extrayendo datos con IA..."
    )

    data = extract_surebet_from_images(images_bytes)
    valid, motivo = validate_surebet(data)

    if not valid:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=(
                f"❌ No pude leer la surebet correctamente.\n"
                f"Motivo: {motivo}\n\n"
                f"Asegúrate de que se vean: casas, pronósticos, cuotas e importes."
            )
        )
        return

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg.message_id,
        text="📊 Guardando en Google Sheets..."
    )

    try:
        surebet_id = add_surebet(data)
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=f"❌ Error al guardar en Sheets: {e}"
        )
        return

    a1 = data["apuesta_1"]
    a2 = data["apuesta_2"]
    total  = float(a1["cantidad_apostada"]) + float(a2["cantidad_apostada"])
    ret1   = round(float(a1["cuota"]) * float(a1["cantidad_apostada"]), 2)
    ret2   = round(float(a2["cuota"]) * float(a2["cantidad_apostada"]), 2)
    bn_min = round(min(ret1, ret2) - total, 2)
    bn_max = round(max(ret1, ret2) - total, 2)

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg.message_id,
        parse_mode="Markdown",
        text=(
            f"✅ *Surebet registrada* `[{surebet_id}]`\n\n"
            f"🏟 *{data['partido']}*\n\n"
            f"🏠 *{a1['casa_de_apuestas']}* — {a1['pronostico']}\n"
            f"   Cuota {a1['cuota']} · {a1['cantidad_apostada']}€ → retorno {ret1:.2f}€\n\n"
            f"🏠 *{a2['casa_de_apuestas']}* — {a2['pronostico']}\n"
            f"   Cuota {a2['cuota']} · {a2['cantidad_apostada']}€ → retorno {ret2:.2f}€\n\n"
            f"💶 Total apostado: *{total:.2f}€*\n"
            f"💰 Beneficio garantizado: *{bn_min:+.2f}€ / {bn_max:+.2f}€*\n\n"
            f"Estado: ⏳ PENDIENTE — usa /resolver\\_surebets cuando acabe"
        )
    )


# ── 2. /resolver_surebets ────────────────────────────────────────────────────

async def cmd_resolver_surebets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista surebets pendientes con botones inline."""
    if not await security_check(update, context):
        return
    if not await check_topic(update, TEMA_SUREBETS):
        return

    msg = await update.message.reply_text("🔄 Buscando surebets pendientes...")

    try:
        pendientes = get_pending_surebets()
    except Exception as e:
        await msg.edit_text(f"❌ Error al leer Sheets: {e}")
        return

    if not pendientes:
        await msg.edit_text("✅ No hay surebets pendientes de resolver.")
        return

    await msg.edit_text(
        f"📋 *{len(pendientes)} surebet(s) pendiente(s):*",
        parse_mode="Markdown"
    )

    for sb in pendientes:
        a1    = sb["apuesta_1"]
        a2    = sb["apuesta_2"]
        sid   = sb["surebet_id"]
        # Las claves coinciden con los headers del sheet (get_all_records los usa)
        casa1 = str(a1.get("Casa", "Casa 1"))
        casa2 = str(a2.get("Casa", "Casa 2"))
        c1    = float(a1.get("Cuota", 1))
        c2    = float(a2.get("Cuota", 1))
        i1    = float(a1.get("Importe (€)", 0))
        i2    = float(a2.get("Importe (€)", 0))
        pron1 = str(a1.get("Pronóstico", "?"))
        pron2 = str(a2.get("Pronóstico", "?"))

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Ganó {casa1}", callback_data=f"sb_WIN_{sid}_1"),
            InlineKeyboardButton(f"✅ Ganó {casa2}", callback_data=f"sb_WIN_{sid}_2"),
        ]])

        await update.message.reply_text(
            f"🔒 *Resuelve la Surebet:* {sb['partido']}\n"
            f"ID: `{sid}`\n\n"
            f"🏠 {casa1} — {pron1} @ {c1} · {i1:.2f}€\n"
            f"🏠 {casa2} — {pron2} @ {c2} · {i2:.2f}€",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


# ── 3. Callback inline ───────────────────────────────────────────────────────

async def callback_surebet_resolver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pulsar botón → actualizar Sheets → editar mensaje."""
    if not await security_check(update, context):
        return

    query = update.callback_query
    await query.answer()

    # Formato: sb_WIN_{surebet_id}_{1|2}
    # split con maxsplit=3 para proteger el surebet_id (que puede contener _)
    parts = query.data.split("_", 3)
    if len(parts) < 4:
        await query.edit_message_text("❌ Datos del botón incorrectos.")
        return

    surebet_id  = parts[2]
    casa_index  = parts[3]   # "1" o "2"

    try:
        pendientes = get_pending_surebets()
    except Exception as e:
        await query.edit_message_text(f"❌ Error al leer Sheets: {e}")
        return

    sb = next((s for s in pendientes if s["surebet_id"] == surebet_id), None)
    if not sb:
        await query.edit_message_text("⚠️ Esta surebet ya fue resuelta o no se encontró.")
        return

    apuesta_ganadora = sb["apuesta_1"] if casa_index == "1" else sb["apuesta_2"]
    casa_ganadora    = str(apuesta_ganadora.get("Casa", ""))

    try:
        resumen = resolve_surebet(surebet_id, casa_ganadora)
    except Exception as e:
        await query.edit_message_text(f"❌ Error al resolver en Sheets: {e}")
        return

    bn      = resumen["beneficio_neto"]
    emoji   = "🟢" if bn >= 0 else "🔴"
    g       = resumen.get("ganada", {})
    p       = resumen.get("perdida", {})

    await query.edit_message_text(
        f"✅ *Surebet `{surebet_id}` resuelta*\n\n"
        f"🏆 Ganó: *{g.get('casa', '?')}* → +{g.get('beneficio', 0):.2f}€\n"
        f"❌ Perdió: *{p.get('casa', '?')}* → -{p.get('perdida', 0):.2f}€\n\n"
        f"{emoji} Beneficio neto: *{bn:+.2f}€*",
        parse_mode="Markdown"
    )
