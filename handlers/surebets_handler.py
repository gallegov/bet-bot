"""
Handler completo para Surebets.

Flujos:
  1. Foto(s) en TOPIC_SUREBETS  → extrae, valida, guarda dos filas vinculadas
  2. /resolver_surebets          → lista pendientes con botones inline
  3. Callback "sb_WIN_*"         → resuelve el par y edita el mensaje

Gestión de álbumes (dos fotos enviadas juntas):
  Telegram envía cada foto del álbum como un update separado pero con el mismo
  media_group_id. Usamos context.bot_data como caché temporal para acumular las
  imágenes del mismo álbum durante 3 segundos antes de procesarlas.
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.surebets_vision_service import extract_surebet_from_images, validate_surebet
from services.surebets_sheets_service import add_surebet, get_pending_surebets, resolve_surebet, init_surebets_sheet
from utils.topic_filter import check_topic, log_thread_id, TEMA_SUREBETS
from utils.security import security_check
from config.settings import TOPIC_SUREBETS

logger = logging.getLogger(__name__)

# Tiempo de espera para acumular imágenes de un álbum (segundos)
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

    # ── Imagen suelta (sin álbum) ──────────────────────────────────────────
    if not media_group_id:
        await _process_images(update, context, [photo.file_id])
        return

    # ── Álbum (dos fotos enviadas juntas) ─────────────────────────────────
    cache_key = f"surebet_album_{media_group_id}"

    if cache_key not in context.bot_data:
        context.bot_data[cache_key] = []
        # Programar el procesamiento tras ALBUM_WAIT segundos
        asyncio.get_event_loop().call_later(
            ALBUM_WAIT,
            lambda: asyncio.ensure_future(
                _flush_album(update, context, cache_key, media_group_id)
            )
        )

    context.bot_data[cache_key].append(photo.file_id)


async def _flush_album(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       cache_key: str, media_group_id: str):
    """Dispara el procesamiento cuando el álbum está completo."""
    file_ids = context.bot_data.pop(cache_key, [])
    if file_ids:
        await _process_images(update, context, file_ids[:2])  # máximo 2


async def _process_images(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           file_ids: list[str]):
    """Descarga imágenes, llama a Claude Vision y guarda en Sheets."""
    # Inicializar hoja si no existe
    try:
        init_surebets_sheet()
    except Exception as e:
        logger.warning(f"init_surebets_sheet: {e}")

    msg = await update.message.reply_text(
        f"🔍 Analizando {'los boletos' if len(file_ids) > 1 else 'el boleto'}..."
    )

    # Descargar imágenes
    images_bytes = []
    for fid in file_ids:
        file = await context.bot.get_file(fid)
        raw = await file.download_as_bytearray()
        images_bytes.append(bytes(raw))

    await msg.edit_text("🧠 Extrayendo datos de la surebet con IA...")

    data = extract_surebet_from_images(images_bytes)
    valid, motivo = validate_surebet(data)

    if not valid:
        await msg.edit_text(
            f"❌ No pude leer la surebet correctamente.\n"
            f"Motivo: {motivo}\n\n"
            f"Asegúrate de que se vean claramente: casas, pronósticos, cuotas e importes."
        )
        return

    await msg.edit_text("📊 Guardando en Google Sheets...")

    try:
        surebet_id = add_surebet(data)
    except Exception as e:
        await msg.edit_text(f"❌ Error al guardar en Sheets: {e}")
        return

    # Calcular beneficio garantizado
    a1 = data["apuesta_1"]
    a2 = data["apuesta_2"]
    total_apostado = float(a1["cantidad_apostada"]) + float(a2["cantidad_apostada"])
    retorno_1 = float(a1["cuota"]) * float(a1["cantidad_apostada"])
    retorno_2 = float(a2["cuota"]) * float(a2["cantidad_apostada"])
    beneficio_min = round(min(retorno_1, retorno_2) - total_apostado, 2)
    beneficio_max = round(max(retorno_1, retorno_2) - total_apostado, 2)

    await msg.edit_text(
        f"✅ *Surebet registrada* `[{surebet_id}]`\n\n"
        f"🏟 *{data['partido']}*\n\n"
        f"🏠 *{a1['casa_de_apuestas']}* — {a1['pronostico']}\n"
        f"   Cuota {a1['cuota']} · {a1['cantidad_apostada']}€ → retorno {retorno_1:.2f}€\n\n"
        f"🏠 *{a2['casa_de_apuestas']}* — {a2['pronostico']}\n"
        f"   Cuota {a2['cuota']} · {a2['cantidad_apostada']}€ → retorno {retorno_2:.2f}€\n\n"
        f"💶 Total apostado: *{total_apostado:.2f}€*\n"
        f"💰 Beneficio garantizado: *{beneficio_min:+.2f}€ / {beneficio_max:+.2f}€*\n\n"
        f"Estado: ⏳ PENDIENTE — usa /resolver\\_surebets cuando acabe el partido",
        parse_mode="Markdown"
    )


# ── 2. Comando /resolver_surebets ────────────────────────────────────────────

async def cmd_resolver_surebets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista las surebets pendientes con botones inline para resolverlas."""
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

    await msg.edit_text(f"📋 *{len(pendientes)} surebet(s) pendiente(s):*", parse_mode="Markdown")

    for sb in pendientes:
        a1 = sb["apuesta_1"]
        a2 = sb["apuesta_2"]
        casa1 = str(a1.get("Casa", "Casa 1"))
        casa2 = str(a2.get("Casa", "Casa 2"))
        sid   = sb["surebet_id"]

        # Codificamos: sb_WIN_{surebet_id}_{casa_ganadora_index}
        # Usamos índice (1 o 2) para evitar nombres con caracteres problemáticos en callback_data
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"✅ Ganó {casa1}",
                    callback_data=f"sb_WIN_{sid}_1"
                ),
                InlineKeyboardButton(
                    f"✅ Ganó {casa2}",
                    callback_data=f"sb_WIN_{sid}_2"
                ),
            ]
        ])

        i1 = float(a1.get("Importe (€)", 0))
        i2 = float(a2.get("Importe (€)", 0))
        c1 = float(a1.get("Cuota", 1))
        c2 = float(a2.get("Cuota", 1))

        await update.message.reply_text(
            f"🔒 *Resuelve la Surebet:* {sb['partido']}\n"
            f"ID: `{sid}`\n\n"
            f"🏠 {casa1} — {a1.get('Pronóstico','?')} @ {c1} · {i1}€\n"
            f"🏠 {casa2} — {a2.get('Pronóstico','?')} @ {c2} · {i2}€",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


# ── 3. Callback inline ───────────────────────────────────────────────────────

async def callback_surebet_resolver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el botón pulsado y actualiza ambas filas en Sheets."""
    if not await security_check(update, context):
        return

    query = update.callback_query
    await query.answer()

    # Formato: sb_WIN_{surebet_id}_{casa_index}
    parts = query.data.split("_", 3)   # máx 4 partes: sb, WIN, sid, idx
    if len(parts) < 4:
        await query.edit_message_text("❌ Datos del botón incorrectos.")
        return

    surebet_id  = parts[2]
    casa_index  = parts[3]   # "1" o "2"

    # Recuperar las filas para saber el nombre de la casa
    try:
        pendientes = get_pending_surebets()
    except Exception as e:
        await query.edit_message_text(f"❌ Error al leer Sheets: {e}")
        return

    sb = next((s for s in pendientes if s["surebet_id"] == surebet_id), None)
    if not sb:
        await query.edit_message_text(
            "⚠️ Esta surebet ya fue resuelta o no se encontró."
        )
        return

    casa_ganadora = str(
        sb["apuesta_1"].get("Casa") if casa_index == "1"
        else sb["apuesta_2"].get("Casa")
    )

    try:
        resumen = resolve_surebet(surebet_id, casa_ganadora)
    except Exception as e:
        await query.edit_message_text(f"❌ Error al resolver en Sheets: {e}")
        return

    bn = resumen["beneficio_neto"]
    emoji_bn = "🟢" if bn >= 0 else "🔴"
    g = resumen.get("ganada", {})
    p = resumen.get("perdida", {})

    await query.edit_message_text(
        f"✅ *Surebet `{surebet_id}` resuelta*\n\n"
        f"🏆 Ganó: *{g.get('casa','?')}* → +{g.get('beneficio',0):.2f}€\n"
        f"❌ Perdió: *{p.get('casa','?')}* → -{p.get('perdida',0):.2f}€\n\n"
        f"{emoji_bn} Beneficio neto de la surebet: *{bn:+.2f}€*",
        parse_mode="Markdown"
    )
