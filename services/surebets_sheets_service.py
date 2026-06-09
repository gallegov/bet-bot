"""
Gestión de Surebets en Google Sheets.

Cada surebet ocupa DOS filas vinculadas por un SUREBET_ID (UUID corto).
Estructura de la hoja:
  ID | SUREBET_ID | Fecha | Partido | Casa | Pronóstico | Cuota | Importe | Retorno | Estado | Beneficio
"""

import uuid
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config.settings import (
    GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID,
    SHEET_NAME_SUREBETS, COL_SB,
    ESTADO_PENDIENTE, ESTADO_GANADA, ESTADO_PERDIDA,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Conexión ────────────────────────────────────────────────────────────────

def _get_sheet():
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_SUREBETS)


def _next_id(ws) -> int:
    values = ws.col_values(COL_SB["ID"])
    ids = [int(v) for v in values[1:] if str(v).isdigit()]
    return max(ids, default=0) + 1


# ── Inicialización ──────────────────────────────────────────────────────────

def init_surebets_sheet():
    """Crea la hoja 'Surebets' con cabeceras y formato si no existe."""
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)

    names = [ws.title for ws in sh.worksheets()]
    if SHEET_NAME_SUREBETS in names:
        return  # ya existe

    ws = sh.add_worksheet(title=SHEET_NAME_SUREBETS, rows=500, cols=12)
    headers = [
        "ID", "Surebet ID", "Fecha", "Partido",
        "Casa", "Pronóstico", "Cuota", "Importe (€)",
        "Retorno (€)", "Estado", "Beneficio/Pérd. (€)"
    ]
    ws.append_row(headers)
    ws.format("A1:K1", {
        "backgroundColor": {"red": 0.06, "green": 0.31, "blue": 0.55},
        "textFormat": {
            "bold": True,
            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
        },
        "horizontalAlignment": "CENTER"
    })
    # Ocultar la columna SUREBET_ID (columna B) — es interna
    sh.batch_update({
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 1,   # columna B (0-indexed)
                    "endIndex": 2
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser"
            }
        }]
    })


# ── Escritura ───────────────────────────────────────────────────────────────

def add_surebet(surebet_data: dict) -> str:
    """
    Guarda las DOS filas vinculadas de una surebet.
    Devuelve el surebet_id (UUID corto) para referencia.

    surebet_data esperado (output de vision_service):
    {
      "partido": "X vs Y",
      "apuesta_1": {"casa_de_apuestas": ..., "pronostico": ..., "cuota": ..., "cantidad_apostada": ...},
      "apuesta_2": {"casa_de_apuestas": ..., "pronostico": ..., "cuota": ..., "cantidad_apostada": ...}
    }
    """
    ws = _get_sheet()
    surebet_id = uuid.uuid4().hex[:8].upper()   # ej. "A3F9C21B"
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    partido = surebet_data.get("partido", "Partido desconocido")

    for apuesta in (surebet_data["apuesta_1"], surebet_data["apuesta_2"]):
        row_id = _next_id(ws)
        cuota   = float(apuesta.get("cuota", 1))
        importe = float(apuesta.get("cantidad_apostada", 0))
        retorno = round(cuota * importe, 2)

        row = [""] * 11
        row[COL_SB["ID"] - 1]         = row_id
        row[COL_SB["SUREBET_ID"] - 1] = surebet_id
        row[COL_SB["FECHA"] - 1]      = fecha
        row[COL_SB["PARTIDO"] - 1]    = partido
        row[COL_SB["CASA"] - 1]       = apuesta.get("casa_de_apuestas", "")
        row[COL_SB["PRONOSTICO"] - 1] = apuesta.get("pronostico", "")
        row[COL_SB["CUOTA"] - 1]      = cuota
        row[COL_SB["IMPORTE"] - 1]    = importe
        row[COL_SB["RETORNO"] - 1]    = retorno
        row[COL_SB["ESTADO"] - 1]     = ESTADO_PENDIENTE
        row[COL_SB["BENEFICIO"] - 1]  = ""
        ws.append_row(row)

    return surebet_id


# ── Lectura ─────────────────────────────────────────────────────────────────

def get_pending_surebets() -> list[dict]:
    """
    Devuelve una lista de surebets pendientes, agrupadas por SUREBET_ID.
    Cada elemento tiene: surebet_id, partido, apuesta_1, apuesta_2
    (con row_index para poder actualizar).
    """
    ws = _get_sheet()
    rows = ws.get_all_records()

    # Agrupar por SUREBET_ID
    grupos: dict[str, list] = {}
    for i, r in enumerate(rows):
        if r.get("Estado") != ESTADO_PENDIENTE:
            continue
        sid = str(r.get("Surebet ID", ""))
        if not sid:
            continue
        if sid not in grupos:
            grupos[sid] = []
        grupos[sid].append({"row_index": i + 2, **r})

    # Filtrar solo pares completos y construir estructura limpia
    result = []
    for sid, filas in grupos.items():
        if len(filas) < 2:
            continue
        result.append({
            "surebet_id": sid,
            "partido":    filas[0].get("Partido", ""),
            "apuesta_1":  filas[0],
            "apuesta_2":  filas[1],
        })
    return result


# ── Resolución ──────────────────────────────────────────────────────────────

def resolve_surebet(surebet_id: str, casa_ganadora: str):
    """
    Actualiza ambas filas de una surebet según la casa ganadora.
    Devuelve un dict con el resumen financiero.
    """
    ws = _get_sheet()
    rows = ws.get_all_records()

    filas = [
        {"row_index": i + 2, **r}
        for i, r in enumerate(rows)
        if str(r.get("Surebet ID", "")) == surebet_id
    ]

    if len(filas) < 2:
        raise ValueError(f"No se encontraron las dos filas para surebet_id={surebet_id}")

    resumen = {"ganada": None, "perdida": None, "beneficio_neto": 0.0}

    for fila in filas:
        row_idx = fila["row_index"]
        cuota   = float(fila.get("Cuota", 1))
        importe = float(fila.get("Importe (€)", 0))
        casa    = str(fila.get("Casa", ""))

        if casa.strip().lower() == casa_ganadora.strip().lower():
            beneficio = round(cuota * importe - importe, 2)
            estado    = ESTADO_GANADA
            resumen["ganada"] = {"casa": casa, "beneficio": beneficio}
            resumen["beneficio_neto"] += beneficio
        else:
            beneficio = -importe
            estado    = ESTADO_PERDIDA
            resumen["perdida"] = {"casa": casa, "perdida": importe}
            resumen["beneficio_neto"] += beneficio

        # Actualizar las 3 celdas en una sola llamada batch para reducir cuota de API
        ws.update(
            f"J{row_idx}:K{row_idx}",
            [[estado, round(beneficio, 2)]]
        )

    return resumen
