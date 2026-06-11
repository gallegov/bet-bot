"""
Handler del cierre mensual.

Comando: /cierremes

Flujo:
  1. Bot muestra advertencia clara de lo que va a hacer y pide confirmación
  2. Usuario confirma → archiva + limpia
  3. Bot confirma con resumen del mes cerrado
"""

import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.cierre_service import ejecutar_cierre_mensual
from utils.topic_filter import check_topic, TEMA_CIERRE
from utils.security import security_check

logger = logging.getLogger(__name__)

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


async def cmd_cierremes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    if not await check_topic(update, TEMA_CIERRE):
        return

    now = datetime.now()
    mes_label = f"{MESES_ES[now.month]} {now.year}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sí, cerrar el mes", callback_data="cierre_OK"),
        InlineKeyboardButton("❌ Cancelar",           callback_data="cierre_CANCEL"),
    ]])

    await update.message.reply_text(
        f"📅 *Cierre mensual — {mes_label}*\n\n"
        f"Esto hará lo siguiente:\n\n"
        f"1️⃣ Creará la hoja *\"Cierre - {mes_label}\"* con el resumen completo del mes\n"
        f"2️⃣ *Borrará todas las apuestas y surebets resueltas* de las hojas activas\n"
        f"3️⃣ Conservará las apuestas *PENDIENTES* para que puedas seguir resolviéndolas\n\n"
        f"⚠️ *Esta acción no se puede deshacer.* Los datos quedan archivados en la hoja de cierre.\n\n"
        f"¿Confirmas el cierre de {mes_label}?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def callback_cierre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return

    query = update.callback_query
    await query.answer()

    if query.data == "cierre_CANCEL":
        await query.edit_message_text("❌ Cierre mensual cancelado.")
        return

    now = datetime.now()
    mes_label = f"{MESES_ES[now.month]} {now.year}"

    await query.edit_message_text(
        f"⏳ Ejecutando cierre de *{mes_label}*...\n\n"
        f"Archivando datos y limpiando hojas...",
        parse_mode="Markdown"
    )

    try:
        resumen = await asyncio.to_thread(ejecutar_cierre_mensual)
    except Exception as e:
        logger.error(f"Error en cierre mensual: {e}")
        await query.edit_message_text(f"❌ Error al ejecutar el cierre: {e}")
        return

    ap  = resumen["apuestas"]
    sb  = resumen["surebets"]
    bn  = resumen["beneficio_total"]
    emoji_bn = "🟢" if bn >= 0 else "🔴"

    # Top casas por beneficio (máx 5)
    casas_txt = ""
    for casa, d in sorted(ap["casas"].items(), key=lambda x: -x[1]["beneficio"])[:5]:
        casas_txt += f"  • {casa}: {d['beneficio']:+.2f}€ ({d['total']} ap.)\n"

    # Info sobre pendientes traspasados
    pendientes_txt = ""
    total_pend = resumen["pendientes_bets"] + resumen["pendientes_sb"]
    if total_pend > 0:
        pendientes_txt = (
            f"\n📌 *Traspasadas al nuevo mes:*\n"
            f"  • {resumen['pendientes_bets']} apuesta(s) pendiente(s)\n"
            f"  • {resumen['pendientes_sb']} surebet(s) pendiente(s)\n"
        )

    await query.edit_message_text(
        f"✅ *Cierre de {mes_label} completado*\n"
        f"📄 Hoja archivada: _\"{resumen['nombre_hoja']}\"_\n\n"

        f"📊 *Apuestas del mes*\n"
        f"  Total: {ap['total']} · ✅{ap['ganadas']} ❌{ap['perdidas']} "
        f"⏳{ap['pendientes']} 🚫{ap['voids']}\n"
        f"  Invertido: {ap['invertido']:.2f}€\n"
        f"  Beneficio: {ap['beneficio']:+.2f}€ · ROI: {ap['roi']}%\n\n"

        f"🔒 *Surebets del mes*\n"
        f"  Pares: {sb['total_pares']}\n"
        f"  Apostado: {sb['total_apostado']:.2f}€\n"
        f"  Beneficio: {sb['beneficio_neto']:+.2f}€\n\n"

        f"{emoji_bn} *Beneficio neto total del mes: {bn:+.2f}€*\n\n"

        f"🏠 *Top casas:*\n{casas_txt}"
        f"{pendientes_txt}\n"
        f"🗓 Las hojas *Apuestas* y *Surebets* ya están limpias para el nuevo mes.",
        parse_mode="Markdown"
    )
