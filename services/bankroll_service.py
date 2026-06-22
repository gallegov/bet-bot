"""
Servicio centralizado de Bankroll.

Hoja 'BankRoll':
  Columna A : En Caja (saldo actual)
  Columna B : Casa de Apuestas
  Columna C+: Meses (ej. "Junio 2026", "Julio 2026"...)

Función principal:
  update_bankroll(casa, delta_caja, delta_mes)
    - delta_caja : importe a sumar/restar en columna A
    - delta_mes  : importe a sumar/restar en la columna del mes actual

Función para depósitos/retiros manuales:
  deposit_withdraw(casa, amount)   → amount positivo=depósito, negativo=retiro
  get_all_balances()               → lista de {casa, saldo}
"""

import asyncio
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config.settings import GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID

SHEET_NAME = "BankRoll"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Casas conocidas (columna B de la hoja)
CASAS = [
    "Codere", "Winamax", "Bet365", "Betfair", "William Hill",
    "Versus", "Bwin", "Madrid", "Olybet", "Betway",
    "Yosports", "Yaass Casino", "Sol", "Marbella",
]


# ── Conexión ─────────────────────────────────────────────────────────────────

def _client():
    creds = Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=SCOPES
    )
    return gspread.Client(auth=creds)

def _get_sheet():
    return _client().open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)


# ── Helpers internos ─────────────────────────────────────────────────────────

def _current_month_name() -> str:
    """Devuelve el nombre del mes actual en español, ej: 'Junio 2026'."""
    meses = [
        "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    now = datetime.now()
    return f"{meses[now.month]} {now.year}"


def _find_casa_row(ws, casa: str) -> int | None:
    """
    Busca la fila de una casa en la columna B.
    Devuelve el índice de fila (1-based) o None si no se encuentra.
    """
    casas_col = ws.col_values(2)  # columna B
    for i, name in enumerate(casas_col):
        if name.strip().lower() == casa.strip().lower():
            return i + 1  # 1-based
    return None


def _get_or_create_month_col(ws, mes: str) -> int:
    """
    Busca la columna del mes actual en la fila 1 (desde columna C en adelante).
    Si no existe, la crea en la siguiente columna libre a la derecha.
    Devuelve el índice de columna (1-based).
    """
    headers = ws.row_values(1)  # fila 1 completa
    # Buscar desde columna C (índice 2) en adelante
    for i in range(2, len(headers)):
        if headers[i].strip() == mes:
            return i + 1  # 1-based

    # No existe → primera columna libre desde C en adelante (columna 3 mínimo)
    # Buscamos la última celda con contenido en fila 1 y sumamos 1
    last_used = 2  # columna B como mínimo (0-indexed)
    for i in range(2, len(headers)):
        if headers[i].strip():
            last_used = i
    # Si ninguna columna C+ tiene contenido, empezamos en C (col 3, índice 2)
    new_col = last_used + 2 if any(h.strip() for h in headers[2:]) else 3

    # Escribir el header del mes — gspread requiere lista de listas
    cell = gspread.utils.rowcol_to_a1(1, new_col)
    ws.update([[mes]], cell)
    return new_col


def _safe_float(value) -> float:
    """Convierte el valor de una celda a float, devuelve 0.0 si está vacío."""
    try:
        return float(str(value).replace(",", ".").replace("€", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ── API pública ──────────────────────────────────────────────────────────────

def update_bankroll(casa: str, delta_caja: float, delta_mes: float) -> dict:
    """
    Actualiza el saldo en caja y el registro mensual de una casa.

    Parámetros:
        casa        : nombre de la casa (debe coincidir con columna B)
        delta_caja  : cantidad a sumar (+) o restar (-) en columna A
        delta_mes   : cantidad a sumar (+) o restar (-) en la columna del mes actual

    Devuelve:
        {"casa": str, "nuevo_saldo": float, "mes": str, "nuevo_mes": float}

    Lanza ValueError si la casa no se encuentra en la hoja.
    """
    ws       = _get_sheet()
    row      = _find_casa_row(ws, casa)
    if row is None:
        raise ValueError(f"Casa '{casa}' no encontrada en la hoja BankRoll")

    mes      = _current_month_name()
    mes_col  = _get_or_create_month_col(ws, mes)

    # Leer valores actuales
    saldo_actual = _safe_float(ws.cell(row, 1, value_render_option='UNFORMATTED_VALUE').value)   # columna A
    mes_actual   = _safe_float(ws.cell(row, mes_col, value_render_option='UNFORMATTED_VALUE').value)

    nuevo_saldo  = round(saldo_actual + delta_caja, 2)
    nuevo_mes    = round(mes_actual + delta_mes, 2)

    # Escribir los dos valores en batch (una sola llamada si están en la misma fila)
    ws.update_cell(row, 1, nuevo_saldo, value_input_option="RAW")
    ws.update_cell(row, mes_col, nuevo_mes, value_input_option="RAW")

    return {
        "casa":        casa,
        "nuevo_saldo": nuevo_saldo,
        "mes":         mes,
        "nuevo_mes":   nuevo_mes,
    }


def deposit_withdraw(casa: str, amount: float) -> dict:
    """
    Registra un depósito (amount > 0) o retiro (amount < 0).
    Solo actualiza columna A, NO la columna mensual
    (los movimientos de caja no son P&L).
    """
    ws  = _get_sheet()
    row = _find_casa_row(ws, casa)
    if row is None:
        raise ValueError(f"Casa '{casa}' no encontrada en la hoja BankRoll")

    saldo_actual = _safe_float(ws.cell(row, 1, value_render_option='UNFORMATTED_VALUE').value)
    nuevo_saldo  = round(saldo_actual + amount, 2)
    ws.update_cell(row, 1, nuevo_saldo, value_input_option="RAW")

    return {"casa": casa, "nuevo_saldo": nuevo_saldo}


def get_all_balances() -> list[dict]:
    """
    Devuelve una lista con el saldo de cada casa.
    [{"casa": "Bet365", "saldo": 150.0}, ...]
    """
    ws    = _get_sheet()
    col_a = ws.col_values(1, value_render_option='UNFORMATTED_VALUE')   # En Caja
    col_b = ws.col_values(2)   # Casa de Apuestas
    rows  = max(len(col_a), len(col_b))

    result = []
    for i in range(rows):
        casa   = col_b[i].strip() if i < len(col_b) else ""
        saldo  = _safe_float(col_a[i]) if i < len(col_a) else 0.0
        if casa and casa not in ("Casa de Apuestas",):  # excluir cabecera
            result.append({"casa": casa, "saldo": saldo})
    return result


# ── Wrappers async (para usar con asyncio.to_thread) ────────────────────────

async def async_update_bankroll(casa: str, delta_caja: float, delta_mes: float) -> dict:
    return await asyncio.to_thread(update_bankroll, casa, delta_caja, delta_mes)

async def async_deposit_withdraw(casa: str, amount: float) -> dict:
    return await asyncio.to_thread(deposit_withdraw, casa, amount)

async def async_get_all_balances() -> list[dict]:
    return await asyncio.to_thread(get_all_balances)
