"""
Servicio de Cierre Mensual.

Qué hace /cierremes:
  1. Lee TODAS las apuestas de "Apuestas" y surebets de "Surebets"
  2. Crea la hoja "Cierre - Junio 2026" con el resumen + listado completo
  3. Borra las filas de datos de "Apuestas" (deja solo la cabecera)
  4. Borra las filas de datos de "Surebets" (deja solo la cabecera)
  5. Las apuestas PENDIENTES se conservan — se mueven a la nueva hoja limpia
     para que no se pierdan al empezar el mes

IMPORTANTE: las apuestas pendientes se traspasan automáticamente a la hoja
limpia del mes nuevo para que puedas seguir resolviéndolas.
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config.settings import (
    GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID,
    SHEET_NAME_BETS, SHEET_NAME_SUREBETS,
    ESTADO_GANADA, ESTADO_PERDIDA, ESTADO_VOID,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


def _client():
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES
    )
    return gspread.Client(auth=creds)


def _mes_nombre(dt: datetime = None) -> str:
    dt = dt or datetime.now()
    return f"{MESES_ES[dt.month]} {dt.year}"


def _safe_float(v) -> float:
    try:
        return float(str(v).replace(",", ".").replace("€", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _calcular_stats_apuestas(rows: list[dict]) -> dict:
    ganadas    = [r for r in rows if r.get("Estado") == ESTADO_GANADA]
    perdidas   = [r for r in rows if r.get("Estado") == ESTADO_PERDIDA]
    pendientes = [r for r in rows if r.get("Estado") == "PENDIENTE"]
    voids      = [r for r in rows if r.get("Estado") == ESTADO_VOID]

    invertido = sum(
        _safe_float(r.get("Importe (€)", 0)) for r in rows
        if r.get("Estado") != "PENDIENTE"
    )
    beneficio = sum(_safe_float(r.get("Beneficio/Pérd. (€)", 0)) for r in rows)
    roi = round(beneficio / invertido * 100, 2) if invertido else 0

    # Por casa
    casas: dict[str, dict] = {}
    for r in rows:
        c = str(r.get("Casa", "Desconocida"))
        casas.setdefault(c, {"total": 0, "ganadas": 0, "invertido": 0.0, "beneficio": 0.0})
        casas[c]["total"] += 1
        if r.get("Estado") == ESTADO_GANADA:
            casas[c]["ganadas"] += 1
        if r.get("Estado") != "PENDIENTE":
            casas[c]["invertido"] += _safe_float(r.get("Importe (€)", 0))
        casas[c]["beneficio"] += _safe_float(r.get("Beneficio/Pérd. (€)", 0))

    # Por deporte
    deportes: dict[str, dict] = {}
    for r in rows:
        d = str(r.get("Deporte", "Otro"))
        deportes.setdefault(d, {"total": 0, "ganadas": 0, "beneficio": 0.0})
        deportes[d]["total"] += 1
        if r.get("Estado") == ESTADO_GANADA:
            deportes[d]["ganadas"] += 1
        deportes[d]["beneficio"] += _safe_float(r.get("Beneficio/Pérd. (€)", 0))

    return {
        "total": len(rows), "ganadas": len(ganadas), "perdidas": len(perdidas),
        "pendientes": len(pendientes), "voids": len(voids),
        "invertido": round(invertido, 2), "beneficio": round(beneficio, 2),
        "roi": roi, "casas": casas, "deportes": deportes,
    }


def _calcular_stats_surebets(rows: list[dict]) -> dict:
    pares: dict[str, list] = {}
    for r in rows:
        sid = str(r.get("Surebet ID", "")).strip()
        if sid:
            pares.setdefault(sid, []).append(r)
    beneficio_neto = sum(_safe_float(r.get("Beneficio/Pérd. (€)", 0)) for r in rows)
    total_apostado = sum(
        _safe_float(r.get("Importe (€)", 0)) for r in rows
        if r.get("Estado") != "PENDIENTE"
    )
    return {
        "total_pares":    len(pares),
        "beneficio_neto": round(beneficio_neto, 2),
        "total_apostado": round(total_apostado, 2),
    }


def _escribir_hoja_cierre(sh, nombre_hoja: str, mes_label: str,
                           stats_ap: dict, stats_sb: dict,
                           apuestas: list[dict], surebets: list[dict]):
    """Crea la hoja de archivo histórico del mes."""
    names = [ws.title for ws in sh.worksheets()]
    if nombre_hoja in names:
        sh.del_worksheet(sh.worksheet(nombre_hoja))

    ws = sh.add_worksheet(title=nombre_hoja, rows=600, cols=20)
    rows_out = []

    # Cabecera
    rows_out += [
        [f"📅 CIERRE MENSUAL — {mes_label}", "", "", "", "", ""],
        ["Generado el", datetime.now().strftime("%d/%m/%Y %H:%M"), "", "", "", ""],
        ["", "", "", "", "", ""],
    ]

    # Resumen general
    rows_out += [
        ["📊 RESUMEN GENERAL", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["", "Apuestas normales", "Surebets (pares)", "TOTAL", "", ""],
        ["Operaciones",
            stats_ap["total"], stats_sb["total_pares"],
            stats_ap["total"] + stats_sb["total_pares"], "", ""],
        ["Total invertido (€)",
            stats_ap["invertido"], stats_sb["total_apostado"],
            round(stats_ap["invertido"] + stats_sb["total_apostado"], 2), "", ""],
        ["Beneficio neto (€)",
            stats_ap["beneficio"], stats_sb["beneficio_neto"],
            round(stats_ap["beneficio"] + stats_sb["beneficio_neto"], 2), "", ""],
        ["", "", "", "", "", ""],
        ["Ganadas",    stats_ap["ganadas"],    "", "", "", ""],
        ["Perdidas",   stats_ap["perdidas"],   "", "", "", ""],
        ["Pendientes", stats_ap["pendientes"], "", "", "", ""],
        ["Voids",      stats_ap["voids"],      "", "", "", ""],
        ["% Acierto",
            f"{round(stats_ap['ganadas'] / max(stats_ap['ganadas'] + stats_ap['perdidas'], 1) * 100, 1)}%",
            "", "", "", ""],
        ["ROI", f"{stats_ap['roi']}%", "", "", "", ""],
        ["", "", "", "", "", ""],
    ]

    # Por casa
    rows_out += [
        ["🏠 DESGLOSE POR CASA", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["Casa", "Apuestas", "Ganadas", "% Acierto", "Invertido (€)", "Beneficio (€)"],
    ]
    for casa, d in sorted(stats_ap["casas"].items(), key=lambda x: -x[1]["beneficio"]):
        pct = round(d["ganadas"] / max(d["total"], 1) * 100, 1)
        rows_out.append([casa, d["total"], d["ganadas"], f"{pct}%",
                         round(d["invertido"], 2), round(d["beneficio"], 2)])
    rows_out.append(["", "", "", "", "", ""])

    # Por deporte
    rows_out += [
        ["⚽ DESGLOSE POR DEPORTE", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["Deporte", "Apuestas", "Ganadas", "% Acierto", "", "Beneficio (€)"],
    ]
    for dep, d in sorted(stats_ap["deportes"].items(), key=lambda x: -x[1]["beneficio"]):
        pct = round(d["ganadas"] / max(d["total"], 1) * 100, 1)
        rows_out.append([dep, d["total"], d["ganadas"], f"{pct}%", "",
                         round(d["beneficio"], 2)])
    rows_out.append(["", "", "", "", "", ""])

    # Listado apuestas
    rows_out += [
        ["📋 APUESTAS DEL MES", "", "", "", "", ""],
        ["", "", "", "", "", ""],
        ["Fecha", "Casa", "Evento", "Descripción", "Cuota", "Importe (€)",
         "Estado", "Beneficio (€)"],
    ]
    for r in apuestas:
        rows_out.append([
            r.get("Fecha registro", ""), r.get("Casa", ""),
            r.get("Evento", ""),         r.get("Descripción", ""),
            r.get("Cuota", ""),          r.get("Importe (€)", ""),
            r.get("Estado", ""),         r.get("Beneficio/Pérd. (€)", ""),
        ])
    rows_out.append(["", "", "", "", "", ""])

    # Listado surebets
    if surebets:
        rows_out += [
            ["🔒 SUREBETS DEL MES", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            ["Fecha", "Partido", "Casa", "Pronóstico", "Cuota",
             "Importe (€)", "Estado", "Beneficio (€)"],
        ]
        for r in surebets:
            rows_out.append([
                r.get("Fecha", ""),    r.get("Partido", ""),
                r.get("Casa", ""),     r.get("Pronóstico", ""),
                r.get("Cuota", ""),    r.get("Importe (€)", ""),
                r.get("Estado", ""),   r.get("Beneficio/Pérd. (€)", ""),
            ])

    ws.update("A1", rows_out)
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    return ws


def _limpiar_hoja_bets(sh, pendientes: list[dict]):
    """
    Borra todas las filas de datos de 'Apuestas' y reescribe solo las pendientes.
    Preserva la fila de cabecera.
    """
    ws = sh.worksheet(SHEET_NAME_BETS)

    # Leer cabecera
    cabecera = ws.row_values(1)

    # Borrar todo excepto cabecera
    last_row = len(ws.get_all_values())
    if last_row > 1:
        ws.delete_rows(2, last_row)

    # Reescribir pendientes si las hay
    if pendientes:
        filas = []
        for r in pendientes:
            fila = [r.get(h, "") for h in cabecera]
            filas.append(fila)
        ws.append_rows(filas, value_input_option="RAW")


def _limpiar_hoja_surebets(sh, pendientes_sb: list[dict]):
    """
    Borra todas las filas de datos de 'Surebets' y reescribe solo las pendientes.
    """
    ws = sh.worksheet(SHEET_NAME_SUREBETS)
    cabecera = ws.row_values(1)

    last_row = len(ws.get_all_values())
    if last_row > 1:
        ws.delete_rows(2, last_row)

    if pendientes_sb:
        filas = []
        for r in pendientes_sb:
            fila = [r.get(h, "") for h in cabecera]
            filas.append(fila)
        ws.append_rows(filas, value_input_option="RAW")


# ── Función principal ────────────────────────────────────────────────────────

def ejecutar_cierre_mensual() -> dict:
    """
    Ejecuta el cierre del mes actual:
      1. Archiva en "Cierre - Mes Año"
      2. Limpia "Apuestas" y "Surebets" conservando los PENDIENTES

    Devuelve resumen para Telegram.
    """
    mes_label   = _mes_nombre()
    nombre_hoja = f"Cierre - {mes_label}"

    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)

    # Leer datos actuales
    all_bets     = sh.worksheet(SHEET_NAME_BETS).get_all_records(value_render_option='UNFORMATTED_VALUE')
    all_surebets = sh.worksheet(SHEET_NAME_SUREBETS).get_all_records(value_render_option='UNFORMATTED_VALUE')

    # Separar pendientes del resto
    bets_pendientes = [r for r in all_bets     if r.get("Estado") == "PENDIENTE"]
    sb_pendientes   = [r for r in all_surebets if r.get("Estado") == "PENDIENTE"]

    # Calcular estadísticas sobre TODO lo del mes (incluyendo pendientes para el conteo)
    stats_ap = _calcular_stats_apuestas(all_bets)
    stats_sb = _calcular_stats_surebets(all_surebets)

    # 1. Crear hoja de archivo
    _escribir_hoja_cierre(sh, nombre_hoja, mes_label,
                          stats_ap, stats_sb, all_bets, all_surebets)

    # 2. Limpiar hojas y dejar solo los pendientes
    _limpiar_hoja_bets(sh, bets_pendientes)
    _limpiar_hoja_surebets(sh, sb_pendientes)

    return {
        "mes_label":        mes_label,
        "nombre_hoja":      nombre_hoja,
        "apuestas":         stats_ap,
        "surebets":         stats_sb,
        "beneficio_total":  round(stats_ap["beneficio"] + stats_sb["beneficio_neto"], 2),
        "pendientes_bets":  len(bets_pendientes),
        "pendientes_sb":    len(sb_pendientes),
    }
