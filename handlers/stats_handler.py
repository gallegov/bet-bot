from telegram import Update
from telegram.ext import ContextTypes
from services.sheets_service import get_pending_bets, _get_sheet
from config.settings import SHEET_NAME_BETS, ESTADO_GANADA, ESTADO_PERDIDA
from utils.topic_filter import check_topic, log_thread_id, TEMA_ESTADISTICAS

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_thread_id(update)
    if not await check_topic(update, TEMA_ESTADISTICAS):
        return
    msg = await update.message.reply_text("📈 Calculando estadísticas...")

    try:
        ws = _get_sheet(SHEET_NAME_BETS)
        rows = ws.get_all_records()
    except Exception as e:
        await msg.edit_text(f"❌ Error al leer Sheets: {e}")
        return

    if not rows:
        await msg.edit_text("📭 Aún no hay apuestas registradas.")
        return

    total       = len(rows)
    ganadas     = sum(1 for r in rows if r.get("Estado") == ESTADO_GANADA)
    perdidas    = sum(1 for r in rows if r.get("Estado") == ESTADO_PERDIDA)
    pendientes  = sum(1 for r in rows if r.get("Estado") == "PENDIENTE")

    resueltas = ganadas + perdidas
    pct = round(ganadas / resueltas * 100, 1) if resueltas else 0

    invertido = sum(float(r.get("Importe (€)", 0) or 0) for r in rows if r.get("Estado") != "PENDIENTE")
    beneficio_neto = sum(float(r.get("Beneficio/Pérd. (€)", 0) or 0) for r in rows)
    roi = round(beneficio_neto / invertido * 100, 1) if invertido else 0

    # Por deporte
    deportes: dict[str, dict] = {}
    for r in rows:
        d = r.get("Deporte", "Otro")
        if d not in deportes:
            deportes[d] = {"total": 0, "ganadas": 0}
        deportes[d]["total"] += 1
        if r.get("Estado") == ESTADO_GANADA:
            deportes[d]["ganadas"] += 1

    deporte_lines = "\n".join(
        f"  • {d}: {v['total']} apuestas, {v['ganadas']} ganadas"
        for d, v in deportes.items()
    )

    emoji_roi = "🟢" if roi >= 0 else "🔴"
    emoji_bn  = "🟢" if beneficio_neto >= 0 else "🔴"

    await msg.edit_text(
        f"📊 *Mis estadísticas de apuestas*\n\n"
        f"📌 Total registradas: *{total}*\n"
        f"✅ Ganadas: *{ganadas}* · ❌ Perdidas: *{perdidas}* · ⏳ Pendientes: *{pendientes}*\n"
        f"🎯 % Acierto: *{pct}%*\n\n"
        f"💶 Total invertido: *{invertido:.2f}€*\n"
        f"{emoji_bn} Beneficio neto: *{beneficio_neto:+.2f}€*\n"
        f"{emoji_roi} ROI: *{roi:+.1f}%*\n\n"
        f"🏅 Por deporte:\n{deporte_lines}",
        parse_mode="Markdown"
    )
