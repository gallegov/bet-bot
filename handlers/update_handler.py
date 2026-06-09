from telegram import Update
from telegram.ext import ContextTypes
from services.sheets_service import get_pending_bets, update_bet_result
from services.sports_service import get_result
from services.resolver_service import resolver_apuesta
from config.settings import ESTADO_GANADA, ESTADO_PERDIDA
from utils.topic_filter import check_topic, log_thread_id, TEMA_CAPTURAS

async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_thread_id(update)
    if not await check_topic(update, TEMA_CAPTURAS):
        return
    msg = await update.message.reply_text("🔄 Buscando apuestas pendientes...")

    pending = get_pending_bets()

    if not pending:
        await msg.edit_text("✅ No hay apuestas pendientes de comprobar.")
        return

    await msg.edit_text(f"⚽ Encontradas *{len(pending)}* apuestas pendientes.\nConsultando resultados...", parse_mode="Markdown")

    resumen = []
    actualizadas = 0
    sin_resultado = 0

    for bet in pending:
        deporte     = bet.get("Deporte", "Fútbol")
        evento      = bet.get("Evento", "")
        fecha       = bet.get("Fecha partido", "")
        row_idx     = bet["row_index"]
        bet_id      = bet.get("ID", "?")
        descripcion = bet.get("Descripción", "")
        importe     = bet.get("Importe (€)", 0)

        resultado = get_result(deporte, evento, fecha)
        estado, desc_res, beneficio = resolver_apuesta(bet, resultado)

        if estado is None:
            sin_resultado += 1
            resumen.append(f"⏳ #{bet_id} {evento[:30]} — sin resultado todavía")
            continue

        update_bet_result(row_idx, estado, desc_res, beneficio)
        actualizadas += 1

        emoji = "✅" if estado == ESTADO_GANADA else "❌"
        signo = "+" if beneficio >= 0 else ""
        resumen.append(
            f"{emoji} #{bet_id} {evento[:25]}\n"
            f"   {descripcion[:30]} → {desc_res}\n"
            f"   {signo}{beneficio:.2f}€"
        )

    resumen_txt = "\n\n".join(resumen)
    total_bn = sum(
        resolver_apuesta(b, get_result(b.get("Deporte",""), b.get("Evento",""), b.get("Fecha partido","")))[2]
        for b in pending
        if resolver_apuesta(b, get_result(b.get("Deporte",""), b.get("Evento",""), b.get("Fecha partido","")))[0] is not None
    )

    await msg.edit_text(
        f"📊 *Actualización completada*\n"
        f"✅ Resueltas: {actualizadas} · ⏳ Sin resultado: {sin_resultado}\n\n"
        f"{resumen_txt}\n\n"
        f"💰 Balance neto de esta actualización: *{total_bn:+.2f}€*\n"
        f"_(Ver hoja 'Resumen' para estadísticas completas)_",
        parse_mode="Markdown"
    )
