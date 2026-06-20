import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from services.sheets_service import get_pending_bets, update_bet_result
from services.sports_service import get_result
from services.resolver_service import resolver_apuesta
from services.bankroll_service import async_update_bankroll
from config.settings import ESTADO_GANADA, ESTADO_PERDIDA
from utils.topic_filter import check_topic, log_thread_id, TEMA_CAPTURAS
from utils.security import security_check
import logging

logger = logging.getLogger(__name__)


async def _apply_bankroll(casa: str, estado: str, beneficio: float, importe: float):
    """
    Actualiza BankRoll tras resolver una apuesta normal.
    El stake YA fue descontado al registrar la apuesta, así que:
    - GANADA : devuelve el retorno completo (stake + beneficio neto)
              delta_caja  = importe + beneficio
              delta_mes   = beneficio neto (solo la ganancia para P&L)
    - PERDIDA: el dinero ya salió al registrar, no tocar En Caja.
              delta_caja  = 0 (ya descontado)
              delta_mes   = -importe (registrar la pérdida en el mes)
    - VOID   : devolver el stake que se descontó al registrar
              delta_caja  = +importe (devolución)
              delta_mes   = 0
    """
    if estado == ESTADO_GANADA:
        delta_caja = importe + beneficio   # retorno completo
        delta_mes  = beneficio             # solo la ganancia neta en P&L
    elif estado == ESTADO_PERDIDA:
        delta_caja = 0                     # ya descontado al registrar
        delta_mes  = -abs(importe)         # apuntar pérdida en el mes
    elif estado == "VOID":
        delta_caja = abs(importe)          # devolver el stake
        delta_mes  = 0
    else:
        return

    try:
        await async_update_bankroll(casa, delta_caja=delta_caja, delta_mes=delta_mes)
    except Exception as e:
        logger.warning(f"BankRoll no actualizado para '{casa}': {e}")


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await security_check(update, context):
        return
    log_thread_id(update)
    if not await check_topic(update, TEMA_CAPTURAS):
        return

    msg = await update.message.reply_text("🔄 Buscando apuestas pendientes...")

    pending = await asyncio.to_thread(get_pending_bets)

    if not pending:
        await msg.edit_text("✅ No hay apuestas pendientes de comprobar.")
        return

    await msg.edit_text(
        f"⚽ Encontradas *{len(pending)}* apuestas pendientes.\nConsultando resultados...",
        parse_mode="Markdown"
    )

    resumen_auto = []
    actualizadas = 0

    for bet in pending:
        deporte     = bet.get("Deporte", "Fútbol")
        evento      = bet.get("Evento", "")
        fecha       = bet.get("Fecha partido", "")
        row_idx     = bet["row_index"]
        bet_id      = bet.get("ID", "?")
        descripcion = bet.get("Descripción", "")
        casa        = bet.get("Casa", "")
        importe     = float(bet.get("Importe (€)", 0) or 0)

        # Saltar apuestas cuya fecha de partido aún no ha llegado
        if fecha:
            try:
                fecha_str = str(fecha).strip()
                fecha_dt = None

                # Caso 1: número de serie de Google Sheets (fecha como float)
                if fecha_str.replace(".", "", 1).isdigit():
                    from datetime import timedelta
                    serial = float(fecha_str)
                    # Google Sheets epoch: 30/12/1899
                    fecha_dt = datetime(1899, 12, 30) + timedelta(days=serial)
                else:
                    # Caso 2: texto con formato de fecha
                    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                        try:
                            fecha_dt = datetime.strptime(fecha_str[:10], fmt)
                            break
                        except ValueError:
                            continue

                if fecha_dt and fecha_dt.date() > datetime.now().date():
                    continue  # partido futuro, ignorar
            except Exception as e:
                logger.warning(f"No se pudo parsear fecha '{fecha}' de apuesta #{bet_id}: {e}")

        resultado = await asyncio.to_thread(get_result, deporte, evento, fecha)
        estado, desc_res, beneficio = resolver_apuesta(bet, resultado)

        if estado is not None:
            await asyncio.to_thread(update_bet_result, row_idx, estado, desc_res, beneficio)
            await _apply_bankroll(casa, estado, beneficio, importe)
            actualizadas += 1
            emoji = "✅" if estado == ESTADO_GANADA else "❌"
            resumen_auto.append(
                f"{emoji} #{bet_id} {evento[:25]}\n"
                f"   {descripcion[:30]} → {desc_res}\n"
                f"   {beneficio:+.2f}€"
            )
        else:
            cuota    = float(bet.get("Cuota", 1) or 1)
            ganancia = round(importe * cuota - importe, 2)

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        f"✅ Ganada (+{ganancia}€)",
                        callback_data=f"res_WIN_{row_idx}_{bet_id}_{importe}_{cuota}_{casa}"
                    ),
                    InlineKeyboardButton(
                        f"❌ Perdida (-{importe}€)",
                        callback_data=f"res_LOSE_{row_idx}_{bet_id}_{importe}_{cuota}_{casa}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🚫 Void (devuelto)",
                        callback_data=f"res_VOID_{row_idx}_{bet_id}_{importe}_{cuota}_{casa}"
                    ),
                ]
            ])

            await update.message.reply_text(
                f"❓ *Apuesta #{bet_id} — resolución manual*\n\n"
                f"🏟 {evento}\n"
                f"🎯 {descripcion}\n"
                f"📅 {fecha or 'sin fecha'}\n"
                f"📈 Cuota {cuota} · {importe}€ apostados",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

    if resumen_auto:
        txt = "\n\n".join(resumen_auto)
        await msg.edit_text(
            f"📊 *Resueltas automáticamente: {actualizadas}*\n\n{txt}",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text(
            "ℹ️ Ninguna apuesta pudo resolverse automáticamente.\n"
            "Usa los botones de arriba para marcarlas manualmente.",
            parse_mode="Markdown"
        )


async def callback_resolver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botones de resolución manual — ahora también actualizan BankRoll."""
    if not await security_check(update, context):
        return

    query = update.callback_query
    await query.answer()

    # Formato: res_ACCION_rowIdx_betId_importe_cuota_casa
    # Casa puede tener espacios → split con maxsplit=6
    parts  = query.data.split("_", 6)
    accion  = parts[1]
    row_idx = int(parts[2])
    bet_id  = parts[3]
    importe = float(parts[4])
    cuota   = float(parts[5])
    casa    = parts[6] if len(parts) > 6 else ""

    if accion == "WIN":
        estado    = ESTADO_GANADA
        beneficio = round(importe * cuota - importe, 2)
        resultado = "Ganada manualmente"
        emoji     = "✅"
    elif accion == "LOSE":
        estado    = ESTADO_PERDIDA
        beneficio = -importe
        resultado = "Perdida manualmente"
        emoji     = "❌"
    else:  # VOID
        estado    = "VOID"
        beneficio = 0.0
        resultado = "Void / devuelta"
        emoji     = "🚫"

    await asyncio.to_thread(update_bet_result, row_idx, estado, resultado, beneficio)
    await _apply_bankroll(casa, estado, beneficio, importe)

    await query.edit_message_text(
        f"{emoji} *Apuesta #{bet_id} marcada como {estado}*\n"
        f"Beneficio registrado: *{beneficio:+.2f}€*",
        parse_mode="Markdown"
    )
