"""
Handler completo para Surebets con integración de BankRoll.
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.surebets_vision_service import extract_surebet_from_images, validate_surebet
from services.surebets_sheets_service import (
    add_surebet, get_pending_surebets, resolve_surebet, init_surebets_sheet
)
from services.bankroll_service import async_update_bankroll
from utils.topic_filter import check_topic, log_thread_id, TEMA_SUREBETS
from utils.security import security_check
from config.settings import TOPIC_SUREBETS, ESTADO_GANADA, ESTADO_PERDIDA

logger = logging.getLogger(__name__)
ALBUM_WAIT = 3.0


# ── 1. Recepción de imágenes ─────────────────────────────────────────────────

async def handle_surebet_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    log_thread_id(update)
    if not await check_topic(update, TEMA_SUREBETS):
        return

    photo          = update.message.photo[-1]
    media_group_id = update.message.media_group_id

    if not media_group_id:
        await _process_images(update, context, [photo.file_id])
        return

    cache_key = f"surebet_album_{media_group_id}"
    chat_id   = update.effective_chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    if cache_key not in context.bot_data:
        context.bot_data[cache_key] = {"file_ids": [], "chat_id": chat_id, "thread_id": thread_id}
        context.job_queue.run_once(
            _flush_album_job,
            when=ALBUM_WAIT,
            data={"cache_key": cache_key},
            name=cache_key,
        )

    context.bot_data[cache_key]["file_ids"].append(photo.file_id)


async def _flush_album_job(context: ContextTypes.DEFAULT_TYPE):
    data      = context.job.data
    cache_key = data["cache_key"]
    album     = context.bot_data.pop(cache_key, None)
    if not album or not album["file_ids"]:
        return

    images_bytes = []
    for fid in album["file_ids"][:2]:
        file = await context.bot.get_file(fid)
        images_bytes.append(bytes(await file.download_as_bytearray()))

    await _run_extraction(context, images_bytes, album["chat_id"], album["thread_id"])


async def _process_images(update: Update, context: ContextTypes.DEFAULT_TYPE, file_ids: list):
    images_bytes = []
    for fid in file_ids:
        file = await context.bot.get_file(fid)
        images_bytes.append(bytes(await file.download_as_bytearray()))

    await _run_extraction(
        context, images_bytes,
        update.effective_chat.id,
        getattr(update.effective_message, "message_thread_id", None)
    )


async def _run_extraction(context, images_bytes, chat_id, thread_id):
    try:
        await asyncio.to_thread(init_surebets_sheet)
    except Exception as e:
        logger.warning(f"init_surebets_sheet: {e}")

    msg = await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=f"🔍 Analizando {'los boletos' if len(images_bytes) > 1 else 'el boleto'}..."
    )

    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                                        text="🧠 Extrayendo datos con IA...")

    data = await asyncio.to_thread(extract_surebet_from_images, images_bytes)
    valid, motivo = validate_surebet(data)

    if not valid:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=f"❌ No pude leer la surebet.\nMotivo: {motivo}"
        )
        return

    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                                        text="📊 Guardando en Google Sheets...")

    try:
        surebet_id = await asyncio.to_thread(add_surebet, data)
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                                            text=f"❌ Error al guardar en Sheets: {e}")
        return

    a1    = data["apuesta_1"]
    a2    = data["apuesta_2"]
    total = float(a1["cantidad_apostada"]) + float(a2["cantidad_apostada"])
    ret1  = round(float(a1["cuota"]) * float(a1["cantidad_apostada"]), 2)
    ret2  = round(float(a2["cuota"]) * float(a2["cantidad_apostada"]), 2)

    # Descontar el stake de cada casa al registrar la surebet
    for apuesta in (a1, a2):
        casa_sb  = apuesta.get("casa_de_apuestas", "")
        stake_sb = float(apuesta.get("cantidad_apostada", 0))
        if casa_sb and stake_sb > 0:
            try:
                from services.bankroll_service import async_deposit_withdraw
                await async_deposit_withdraw(casa_sb, -stake_sb)
            except Exception as e:
                logger.warning(f"BankRoll no descontado para '{casa_sb}' al registrar surebet: {e}")

    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=msg.message_id,
        parse_mode="Markdown",
        text=(
            f"✅ *Surebet registrada* `[{surebet_id}]`\n\n"
            f"🏟 *{data['partido']}*\n\n"
            f"🏠 *{a1['casa_de_apuestas']}* — {a1['pronostico']}\n"
            f"   Cuota {a1['cuota']} · {a1['cantidad_apostada']}€ → retorno {ret1:.2f}€\n\n"
            f"🏠 *{a2['casa_de_apuestas']}* — {a2['pronostico']}\n"
            f"   Cuota {a2['cuota']} · {a2['cantidad_apostada']}€ → retorno {ret2:.2f}€\n\n"
            f"💶 Total apostado: *{total:.2f}€*\n"
            f"💰 Beneficio garantizado: *{round(min(ret1,ret2)-total,2):+.2f}€ / "
            f"{round(max(ret1,ret2)-total,2):+.2f}€*\n\n"
            f"Estado: ⏳ PENDIENTE — usa /resolver\\_surebets cuando acabe"
        )
    )


# ── 2. /resolver_surebets ────────────────────────────────────────────────────

async def cmd_resolver_surebets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    if not await check_topic(update, TEMA_SUREBETS):
        return

    msg = await update.message.reply_text("🔄 Buscando surebets pendientes...")

    try:
        pendientes = await asyncio.to_thread(get_pending_surebets)
    except Exception as e:
        await msg.edit_text(f"❌ Error al leer Sheets: {e}")
        return

    if not pendientes:
        await msg.edit_text("✅ No hay surebets pendientes de resolver.")
        return

    await msg.edit_text(f"📋 *{len(pendientes)} surebet(s) pendiente(s):*", parse_mode="Markdown")

    for sb in pendientes:
        a1, a2 = sb["apuesta_1"], sb["apuesta_2"]
        sid    = sb["surebet_id"]
        casa1  = str(a1.get("Casa", "Casa 1"))
        casa2  = str(a2.get("Casa", "Casa 2"))
        c1, c2 = float(a1.get("Cuota", 1)), float(a2.get("Cuota", 1))
        i1, i2 = float(a1.get("Importe (€)", 0)), float(a2.get("Importe (€)", 0))

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Ganó {casa1}", callback_data=f"sb_WIN_{sid}_1"),
            InlineKeyboardButton(f"✅ Ganó {casa2}", callback_data=f"sb_WIN_{sid}_2"),
        ]])

        await update.message.reply_text(
            f"🔒 *Resuelve la Surebet:* {sb['partido']}\n"
            f"ID: `{sid}`\n\n"
            f"🏠 {casa1} — {a1.get('Pronóstico','?')} @ {c1} · {i1:.2f}€\n"
            f"🏠 {casa2} — {a2.get('Pronóstico','?')} @ {c2} · {i2:.2f}€",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


# ── 3. Callback inline ───────────────────────────────────────────────────────

async def callback_surebet_resolver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return

    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 3)
    if len(parts) < 4:
        await query.edit_message_text("❌ Datos del botón incorrectos.")
        return

    surebet_id  = parts[2]
    casa_index  = parts[3]

    try:
        pendientes = await asyncio.to_thread(get_pending_surebets)
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
        resumen = await asyncio.to_thread(resolve_surebet, surebet_id, casa_ganadora)
    except Exception as e:
        await query.edit_message_text(f"❌ Error al resolver en Sheets: {e}")
        return

    # ── Actualizar BankRoll para ambas casas ──────────────────────────────
    g = resumen.get("ganada", {})
    p = resumen.get("perdida", {})
    bankroll_errores = []

    if g.get("casa"):
        try:
            # Stake ya descontado al registrar → devolver retorno completo (stake + beneficio)
            importe_g = float(g.get("importe", p.get("perdida", 0)))  # stake de la ganadora
            retorno_g = importe_g + g["beneficio"]
            logger.info(f"BankRoll ganadora: '{g['casa']}' retorno={retorno_g:+.2f}")
            await async_update_bankroll(g["casa"], delta_caja=retorno_g, delta_mes=0)
        except Exception as e:
            msg_err = f"BankRoll no actualizado para *{g['casa']}*: {e}"
            logger.warning(msg_err)
            bankroll_errores.append(f"⚠️ {msg_err}")

    if p.get("casa"):
        try:
            # Stake ya descontado al registrar → En Caja no se toca, perdida ya contabilizada
            logger.info(f"BankRoll perdedora: '{p['casa']}' stake ya descontado, sin cambio en caja")
            # No tocar En Caja (delta_caja=0), ni columna mensual (delta_mes=0) para surebets
            pass
        except Exception as e:
            msg_err = f"BankRoll no actualizado para *{p['casa']}*: {e}"
            logger.warning(msg_err)
            bankroll_errores.append(f"⚠️ {msg_err}")

    bn    = resumen["beneficio_neto"]
    emoji = "🟢" if bn >= 0 else "🔴"

    texto = (
        f"✅ *Surebet `{surebet_id}` resuelta*\n\n"
        f"🏆 Ganó: *{g.get('casa','?')}* → +{g.get('beneficio',0):.2f}€\n"
        f"❌ Perdió: *{p.get('casa','?')}* → -{p.get('perdida',0):.2f}€\n\n"
        f"{emoji} Beneficio neto: *{bn:+.2f}€*"
    )
    if bankroll_errores:
        texto += "\n\n" + "\n".join(bankroll_errores)
        texto += "\n\n_Comprueba que el nombre de la casa en Surebets coincide con el de BankRoll._"

    await query.edit_message_text(texto, parse_mode="Markdown")
