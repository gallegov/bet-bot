import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config.settings import (
    GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID,
    SHEET_NAME_BETS, SHEET_NAME_STATS, COL,
    ESTADO_PENDIENTE, ESTADO_GANADA, ESTADO_PERDIDA
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _client():
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.Client(auth=creds)

def _get_sheet(name: str):
    return _client().open_by_key(GOOGLE_SHEET_ID).worksheet(name)

def _next_id(ws) -> int:
    values = ws.col_values(COL["ID"])
    ids = [int(v) for v in values[1:] if str(v).isdigit()]
    return max(ids, default=0) + 1

def init_sheet():
    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    names = [ws.title for ws in sh.worksheets()]

    if SHEET_NAME_BETS not in names:
        ws = sh.add_worksheet(title=SHEET_NAME_BETS, rows=1000, cols=20)
        headers = [
            "ID", "Fecha registro", "Casa", "Deporte", "Evento",
            "Fecha partido", "Tipo apuesta", "Descripción",
            "Cuota", "Importe (€)", "Estado",
            "Resultado", "Beneficio/Pérd. (€)", "Notas"
        ]
        ws.append_row(headers)
        ws.format("A1:N1", {
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER"
        })

    if SHEET_NAME_STATS not in names:
        ws_stats = sh.add_worksheet(title=SHEET_NAME_STATS, rows=30, cols=5)
        _write_stats_formulas(ws_stats)

def _write_stats_formulas(ws):
    bets = SHEET_NAME_BETS
    ws.update("A1", [
        ["📊 RESUMEN DE APUESTAS", ""],
        ["", ""],
        ["Total apuestas",       f"=COUNTA('{bets}'!A2:A)"],
        ["Ganadas",              f"=COUNTIF('{bets}'!K2:K;\"GANADA\")"],
        ["Perdidas",             f"=COUNTIF('{bets}'!K2:K;\"PERDIDA\")"],
        ["Pendientes",           f"=COUNTIF('{bets}'!K2:K;\"PENDIENTE\")"],
        ["% Acierto",            f"=IFERROR(B4/(B4+B5);0)"],
        ["", ""],
        ["Total invertido (€)",  f"=SUMIF('{bets}'!K2:K;\"<>PENDIENTE\";'{bets}'!J2:J)"],
        ["Total ganado (€)",     f"=SUMIF('{bets}'!M2:M;\">0\";'{bets}'!M2:M)"],
        ["Total perdido (€)",    f"=SUMIF('{bets}'!M2:M;\"<0\";'{bets}'!M2:M)"],
        ["Beneficio neto (€)",   f"=SUM('{bets}'!M2:M)"],
        ["ROI (%)",              f"=IFERROR(B12/B9;0)"],
    ])
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("B7",  {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}})
    ws.format("B13", {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}})

def add_bet(bet_data: dict) -> int:
    ws = _get_sheet(SHEET_NAME_BETS)
    bet_id = _next_id(ws)
    row = [""] * 14
    row[COL["ID"] - 1]            = bet_id
    row[COL["FECHA"] - 1]         = datetime.now().strftime("%d/%m/%Y %H:%M")
    row[COL["CASA"] - 1]          = bet_data.get("casa", "")
    row[COL["DEPORTE"] - 1]       = bet_data.get("deporte", "")
    row[COL["EVENTO"] - 1]        = bet_data.get("evento", "")
    row[COL["FECHA_PARTIDO"] - 1] = bet_data.get("fecha_partido", "")
    row[COL["TIPO"] - 1]          = bet_data.get("tipo", "")
    row[COL["DESCRIPCION"] - 1]   = bet_data.get("descripcion", "")
    row[COL["CUOTA"] - 1]         = bet_data.get("cuota", "")
    row[COL["IMPORTE"] - 1]       = bet_data.get("importe", "")
    row[COL["ESTADO"] - 1]        = ESTADO_PENDIENTE
    row[COL["RESULTADO"] - 1]     = ""
    row[COL["BENEFICIO"] - 1]     = ""
    row[COL["NOTAS"] - 1]         = bet_data.get("notas", "")
    ws.append_row(row, value_input_option="RAW")
    return bet_id

def get_pending_bets() -> list[dict]:
    ws = _get_sheet(SHEET_NAME_BETS)
    rows = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
    return [
        {"row_index": i + 2, **r}
        for i, r in enumerate(rows)
        if r.get("Estado") == ESTADO_PENDIENTE
    ]

def update_bet_result(row_index: int, estado: str, resultado: str, beneficio: float):
    ws = _get_sheet(SHEET_NAME_BETS)
    ws.update(f"K{row_index}:M{row_index}", [[estado, resultado, round(beneficio, 2)]], value_input_option="RAW")

def get_bet_by_id(bet_id: int) -> dict | None:
    """Busca una apuesta por ID. Devuelve la fila con row_index o None."""
    ws = _get_sheet(SHEET_NAME_BETS)
    rows = ws.get_all_records(value_render_option='UNFORMATTED_VALUE')
    for i, r in enumerate(rows):
        if str(r.get("ID", "")) == str(bet_id):
            return {"row_index": i + 2, **r}
    return None

def update_bet_fields(row_index: int, campos: dict):
    """
    Actualiza campos individuales de una apuesta.
    campos es un dict con claves del COL map: "casa", "fecha_partido", "cuota", "importe"
    Usa RAW para evitar que Sheets reinterprete números/fechas según el locale regional.
    """
    ws = _get_sheet(SHEET_NAME_BETS)
    campo_col = {
        "casa":          COL["CASA"],
        "fecha_partido": COL["FECHA_PARTIDO"],
        "cuota":         COL["CUOTA"],
        "importe":       COL["IMPORTE"],
    }
    for campo, valor in campos.items():
        col = campo_col.get(campo)
        if col:
            cell = gspread.utils.rowcol_to_a1(row_index, col)
            ws.update([[valor]], cell, value_input_option="RAW")

def format_fecha_legible(valor) -> str:
    """
    Convierte un valor de fecha leído con UNFORMATTED_VALUE a texto legible.
    Si ya es texto (DD/MM/YYYY), lo devuelve tal cual.
    Si es número de serie de Google Sheets, lo convierte a DD/MM/YYYY.
    Si está vacío, devuelve cadena vacía.
    """
    if not valor and valor != 0:
        return ""

    s = str(valor).strip()
    if not s:
        return ""

    # Número de serie de Sheets (fecha guardada como float)
    if s.replace(".", "", 1).isdigit():
        try:
            from datetime import datetime, timedelta
            serial = float(s)
            dt = datetime(1899, 12, 30) + timedelta(days=serial)
            # Si tiene parte horaria (decimales), incluirla
            if serial % 1 != 0:
                return dt.strftime("%d/%m/%Y %H:%M")
            return dt.strftime("%d/%m/%Y")
        except (ValueError, OverflowError):
            return s

    return s
