"""
Handler /editar — permite corregir casa, fecha, cuota e importe de una apuesta.

Flujo conversacional:
  1. /editar 5           → muestra los datos actuales de la apuesta #5
                           con botones inline para elegir qué campo editar
  2. Usuario pulsa campo → bot pide el nuevo valor
  3. Usuario escribe     → valida, actualiza Sheets, confirma
  4. Bot ofrece editar otro campo o terminar

Estados ConversationHandler:
  ELIGIENDO_CAMPO   → esperando que pulse un botón
  ESCRIBIENDO_VALOR → esperando que escriba el nuevo valor
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)
from services.sheets_service import get_bet_by_id, update_bet_fields
from services.bankroll_service import CASAS
from utils.security import security_check
from utils.topic_filter import check_topic, TEMA_CAPTURAS

logger = logging.getLogger(__name__)

ELIGIENDO_CAMPO   = 0
ESCRIBIENDO_VALOR = 1

# Mapeo campo → etiqueta visible y columna de validación
CAMPOS = {
    "casa":          {"label": "🏠 Casa",             "tipo": "casa"},
    "fecha_partido": {"label": "📅 Fecha del partido", "tipo": "fecha"},
    "cuota":         {"label": "📈 Cuota",             "tipo": "float"},
    "importe":       {"label": "💶 Importe (€)",       "tipo": "float"},
}


def _resumen_apuesta(bet: dict) -> str:
    return (
        f"*Apuesta #{bet.get('ID', '?')}*\n\n"
        f"🏟 {bet.get('Evento', '?')}\n"
        f"🏠 Casa: *{bet.get('Casa', '?')}*\n"
        f"📅 Fecha partido: *{bet.get('Fecha partido', 'No detectada')}*\n"
        f"📈 Cuota: *{bet.get('Cuota', '?')}*\n"
        f"💶 Importe: *{bet.get('Importe (€)', '?')}€*\n"
        f"Estado: {bet.get('Estado', '?')}"
    )


def _teclado_campos(bet_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Casa",              callback_data=f"edit_{bet_id}_casa"),
            InlineKeyboardButton("📅 Fecha partido",     callback_data=f"edit_{bet_id}_fecha_partido"),
        ],
        [
            InlineKeyboardButton("📈 Cuota",             callback_data=f"edit_{bet_id}_cuota"),
            InlineKeyboardButton("💶 Importe",           callback_data=f"edit_{bet_id}_importe"),
        ],
        [
            InlineKeyboardButton("✅ Terminar edición",  callback_data=f"edit_{bet_id}_DONE"),
        ],
    ])


# ── Paso 1: /editar ID ────────────────────────────────────────────────────────

async def cmd_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return ConversationHandler.END
    if not await check_topic(update, TEMA_CAPTURAS):
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text(
            "❌ Indica el ID de la apuesta.\nEjemplo: `/editar 5`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    try:
        bet_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ El ID debe ser un número.")
        return ConversationHandler.END

    bet = await asyncio.to_thread(get_bet_by_id, bet_id)
    if not bet:
        await update.message.reply_text(f"❌ No se encontró la apuesta #{bet_id}.")
        return ConversationHandler.END

    context.user_data["edit_bet"]      = bet
    context.user_data["edit_bet_id"]   = bet_id

    await update.message.reply_text(
        f"✏️ *Editar apuesta*\n\n{_resumen_apuesta(bet)}\n\n"
        f"¿Qué campo quieres modificar?",
        parse_mode="Markdown",
        reply_markup=_teclado_campos(bet_id)
    )
    return ELIGIENDO_CAMPO


# ── Paso 2: elige campo ───────────────────────────────────────────────────────

async def elegir_campo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Formato: edit_{bet_id}_{campo}
    parts  = query.data.split("_", 2)
    bet_id = int(parts[1])
    campo  = parts[2]

    if campo == "DONE":
        await query.edit_message_text(
            f"✅ Edición de apuesta #{bet_id} finalizada.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    context.user_data["edit_campo"] = campo
    info = CAMPOS[campo]

    # Si es casa → mostrar teclado inline con casas
    if info["tipo"] == "casa":
        botones = [
            InlineKeyboardButton(c, callback_data=f"editval_{bet_id}_{campo}_{c}")
            for c in CASAS
        ]
        keyboard = InlineKeyboardMarkup(
            [botones[i:i+2] for i in range(0, len(botones), 2)]
        )
        await query.edit_message_text(
            f"🏠 *Selecciona la casa de apuestas:*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return ELIGIENDO_CAMPO   # seguimos en el mismo estado esperando callback

    # Para los demás campos → pedir texto
    hints = {
        "fecha_partido": "Formato: DD/MM/YYYY (ej: 15/06/2026)\nEscribe `0` si no hay fecha.",
        "cuota":         "Escribe la cuota (ej: 2.10)",
        "importe":       "Escribe el importe apostado en € (ej: 50 o 50.50)",
    }
    await query.edit_message_text(
        f"✏️ *{info['label']}*\n\n{hints.get(campo, 'Escribe el nuevo valor:')}\n\n"
        f"Escribe /cancelar para salir.",
        parse_mode="Markdown"
    )
    return ESCRIBIENDO_VALOR


# ── Paso 2b: elige casa (callback de valor) ───────────────────────────────────

async def elegir_casa_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback cuando el usuario pulsa una casa del teclado inline."""
    query = update.callback_query
    await query.answer()

    # Formato: editval_{bet_id}_{campo}_{valor}
    parts  = query.data.split("_", 3)
    bet_id = int(parts[1])
    campo  = parts[2]
    valor  = parts[3]

    bet = context.user_data.get("edit_bet", {})
    row_index = bet.get("row_index")

    await asyncio.to_thread(update_bet_fields, row_index, {campo: valor})

    # Refrescar datos en memoria
    bet_actualizado = await asyncio.to_thread(get_bet_by_id, bet_id)
    context.user_data["edit_bet"] = bet_actualizado

    await query.edit_message_text(
        f"✅ *Casa actualizada a: {valor}*\n\n"
        f"{_resumen_apuesta(bet_actualizado)}\n\n"
        f"¿Quieres modificar algo más?",
        parse_mode="Markdown",
        reply_markup=_teclado_campos(bet_id)
    )
    return ELIGIENDO_CAMPO


# ── Paso 3: recibe valor de texto ─────────────────────────────────────────────

async def recibir_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    campo     = context.user_data.get("edit_campo")
    bet       = context.user_data.get("edit_bet", {})
    bet_id    = context.user_data.get("edit_bet_id")
    row_index = bet.get("row_index")
    texto     = update.message.text.strip()
    info      = CAMPOS.get(campo, {})

    # Validar según tipo
    if info["tipo"] == "float":
        try:
            valor = float(texto.replace(",", "."))
            if valor <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Introduce un número válido mayor que 0. Inténtalo de nuevo:"
            )
            return ESCRIBIENDO_VALOR

    elif info["tipo"] == "fecha":
        if texto == "0":
            valor = ""
        else:
            # Validar formato DD/MM/YYYY
            from datetime import datetime
            try:
                datetime.strptime(texto[:10], "%d/%m/%Y")
                valor = texto[:10]
            except ValueError:
                await update.message.reply_text(
                    "❌ Formato incorrecto. Usa DD/MM/YYYY (ej: 15/06/2026).\n"
                    "O escribe `0` para dejar sin fecha."
                )
                return ESCRIBIENDO_VALOR
    else:
        valor = texto

    # Guardar en Sheets
    try:
        await asyncio.to_thread(update_bet_fields, row_index, {campo: valor})
    except Exception as e:
        await update.message.reply_text(f"❌ Error al guardar: {e}")
        return ESCRIBIENDO_VALOR

    # Refrescar datos
    bet_actualizado = await asyncio.to_thread(get_bet_by_id, bet_id)
    context.user_data["edit_bet"] = bet_actualizado

    label = info.get("label", campo)
    valor_display = f"{valor}€" if info["tipo"] == "float" and campo == "importe" else valor

    await update.message.reply_text(
        f"✅ *{label} actualizado a: {valor_display}*\n\n"
        f"{_resumen_apuesta(bet_actualizado)}\n\n"
        f"¿Quieres modificar algo más?",
        parse_mode="Markdown",
        reply_markup=_teclado_campos(bet_id)
    )
    return ELIGIENDO_CAMPO


# ── Cancelar ──────────────────────────────────────────────────────────────────

async def cancelar_edicion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Edición cancelada.")
    return ConversationHandler.END


# ── Factory ───────────────────────────────────────────────────────────────────

def build_editar_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("editar", cmd_editar)],
        states={
            ELIGIENDO_CAMPO: [
                CallbackQueryHandler(elegir_casa_valor, pattern="^editval_"),
                CallbackQueryHandler(elegir_campo,      pattern="^edit_"),
            ],
            ESCRIBIENDO_VALOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_valor),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_edicion)],
        per_message=False,
    )
