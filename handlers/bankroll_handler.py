"""
Handler de Bankroll: /deposito y /retiro mediante ConversationHandler.

Flujo:
  1. /deposito o /retiro  → pide cantidad
  2. Usuario escribe número → bot muestra teclado inline con casas
  3. Usuario pulsa casa    → actualiza Sheets y confirma
"""

import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)
from services.bankroll_service import CASAS, async_deposit_withdraw, async_get_all_balances
from utils.security import security_check
from utils.topic_filter import check_topic, TEMA_SALDO

# Estados de la conversación
ASK_AMOUNT = 0
ASK_CASA   = 1


# ── Paso 1: arrancar conversación ────────────────────────────────────────────

async def cmd_deposito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return ConversationHandler.END
    if not await check_topic(update, TEMA_SALDO):
        return ConversationHandler.END

    context.user_data["br_tipo"] = "deposito"
    await update.message.reply_text("💶 ¿Qué cantidad quieres *depositar*? (ej: 50 o 50.50)",
                                    parse_mode="Markdown")
    return ASK_AMOUNT


async def cmd_retiro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return ConversationHandler.END
    if not await check_topic(update, TEMA_SALDO):
        return ConversationHandler.END

    context.user_data["br_tipo"] = "retiro"
    await update.message.reply_text("💶 ¿Qué cantidad quieres *retirar*? (ej: 50 o 50.50)",
                                    parse_mode="Markdown")
    return ASK_AMOUNT


# ── Paso 2: recibir cantidad y mostrar casas ─────────────────────────────────

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Introduce un número válido mayor que 0.")
        return ASK_AMOUNT

    context.user_data["br_amount"] = amount
    tipo = context.user_data["br_tipo"]
    emoji = "📥" if tipo == "deposito" else "📤"

    # Construir teclado inline con todas las casas (2 por fila)
    buttons = [
        InlineKeyboardButton(casa, callback_data=f"br_{casa.replace(' ', '~')}")
        for casa in CASAS
    ]
    # Agrupar de 2 en 2
    keyboard = InlineKeyboardMarkup(
        [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    )

    await update.message.reply_text(
        f"{emoji} *{tipo.capitalize()} de {amount:.2f}€*\n\n"
        f"¿En qué casa de apuestas?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return ASK_CASA


# ── Paso 3: recibir casa y ejecutar operación ────────────────────────────────

async def receive_casa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    casa   = query.data[3:].replace("~", " ")   # quitar prefijo "br_" y decodificar espacios
    amount = context.user_data.get("br_amount", 0)
    tipo   = context.user_data.get("br_tipo", "deposito")

    delta = amount if tipo == "deposito" else -amount
    emoji = "✅ Depósito" if tipo == "deposito" else "✅ Retiro"

    try:
        result = await async_deposit_withdraw(casa, delta)
    except ValueError as e:
        await query.edit_message_text(f"❌ {e}")
        return ConversationHandler.END
    except Exception as e:
        await query.edit_message_text(f"❌ Error al actualizar Sheets: {e}")
        return ConversationHandler.END

    nuevo_saldo = result["nuevo_saldo"]
    signo = "+" if delta > 0 else ""

    await query.edit_message_text(
        f"{emoji} de *{amount:.2f}€* en *{casa}* registrado.\n\n"
        f"💰 Nuevo saldo en caja: *{nuevo_saldo:.2f}€*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── Cancelar en cualquier momento ───────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END


# ── Comando /saldo ────────────────────────────────────────────────────────────

async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el saldo actual de todas las casas."""
    if not await security_check(update, context):
        return
    if not await check_topic(update, TEMA_SALDO):
        return

    msg = await update.message.reply_text("💰 Consultando saldos...")

    try:
        balances = await async_get_all_balances()
    except Exception as e:
        await msg.edit_text(f"❌ Error al leer Sheets: {e}")
        return

    if not balances:
        await msg.edit_text("No hay casas registradas en la hoja BankRoll.")
        return

    total = sum(b["saldo"] for b in balances)
    lineas = "\n".join(
        f"{'🟢' if b['saldo'] >= 0 else '🔴'} *{b['casa']}*: {b['saldo']:.2f}€"
        for b in balances
    )

    await msg.edit_text(
        f"💰 *Saldo en caja por casa*\n\n{lineas}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"💼 *Total: {total:.2f}€*",
        parse_mode="Markdown"
    )


# ── Factory: devuelve los handlers listos para registrar en bot.py ───────────

def build_bankroll_handlers():
    """
    Devuelve una lista de handlers para añadir en bot.py:
      bot_app.add_handler(h) for h in build_bankroll_handlers()
    """
    deposito_conv = ConversationHandler(
        entry_points=[CommandHandler("deposito", cmd_deposito)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            ASK_CASA:   [CallbackQueryHandler(receive_casa, pattern="^br_")],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
        per_message=False,
    )

    retiro_conv = ConversationHandler(
        entry_points=[CommandHandler("retiro", cmd_retiro)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            ASK_CASA:   [CallbackQueryHandler(receive_casa, pattern="^br_")],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
        per_message=False,
    )

    return [
        deposito_conv,
        retiro_conv,
        CommandHandler("saldo", cmd_saldo),
    ]
