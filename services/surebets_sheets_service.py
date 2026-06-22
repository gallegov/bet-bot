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

def _client():
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.Client(auth=creds)

def _get_sheet():
    return _client().open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_SUREBETS)

def _next_id(ws) -> int:
    values = ws.col_values(COL_SB["ID"])
    ids = [int(v) for v in values[1:] if str(v).isdigit()]
    return max(ids, default=0) + 1

def init_surebets_sheet():
    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    names = [ws.title for ws in sh.worksheets()]
    if SHEET_NAME_SUREBETS in names:
        return

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
    # Ocultar columna Surebet ID (B)
    sh.batch_update({"requests": [{
        "updateDimensionProperties": {
            "range": {
                "sheetId": ws.id,
                "dimension": "COLUMNS",
                "startIndex": 1,
                "endIndex": 2
            },
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser"
        }
    }]})

def add_surebet(surebet_data: dict) -> str:
    ws = _get_sheet()
    surebet_id = uuid.uuid4().hex[:8].upper()
    fecha  = datetime.now().strftime("%d/%m/%Y %H:%M")
    partido = surebet_data.get("partido", "Partido desconocido")

    rows_to_append = []
    for apuesta in (surebet_data["apuesta_1"], surebet_data["apuesta_2"]):
        row_id  = _next_id(ws) + len(rows_to_append)  # evita ID duplicado en batch
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
        rows_to_append.append(row)

    # Escribir las dos filas de golpe
    ws.append_rows(rows_to_append, value_input_option="RAW")
    return surebet_id

def get_pending_surebets() -> list[dict]:
    ws = _get_sheet()
    rows = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')

    grupos: dict[str, list] = {}
    for i, r in enumerate(rows):
        if r.get("Estado") != ESTADO_PENDIENTE:
            continue
        sid = str(r.get("Surebet ID", "")).strip()
        if not sid:
            continue
        grupos.setdefault(sid, []).append({"row_index": i + 2, **r})

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

def resolve_surebet(surebet_id: str, casa_ganadora: str) -> dict:
    ws = _get_sheet()
    rows = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')

    filas = [
        {"row_index": i + 2, **r}
        for i, r in enumerate(rows)
        if str(r.get("Surebet ID", "")).strip() == surebet_id
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
        else:
            beneficio = -importe
            estado    = ESTADO_PERDIDA
            resumen["perdida"] = {"casa": casa, "perdida": importe}

        resumen["beneficio_neto"] += beneficio
        # Columnas J (Estado=10) y K (Beneficio=11)
        ws.update(f"J{row_idx}:K{row_idx}", [[estado, round(beneficio, 2)]], value_input_option="RAW")

    return resumen

def fix_number_format_columns():
    """
    Utilidad de mantenimiento: limpia el formato numérico de las columnas
    Cuota, Importe y Beneficio para que Sheets deje de reinterpretar
    los valores según el locale regional. Ejecutar una vez si los números
    aparecen multiplicados por 10 o 100.
    """
    ws = _get_sheet()
    sh = ws.spreadsheet
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 1,
                "startColumnIndex": col - 1,
                "endColumnIndex": col
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": "0.00"}
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    } for col in (COL_SB["CUOTA"], COL_SB["IMPORTE"], COL_SB["RETORNO"], COL_SB["BENEFICIO"])]

    sh.batch_update({"requests": requests})
