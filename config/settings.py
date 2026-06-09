import os
from dotenv import load_dotenv

load_dotenv()  # carga anticipada para que os.getenv funcione en este módulo

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Anthropic (Claude Vision)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# APIs deportivas
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")   # fútbol
API_SPORTS_KEY   = os.getenv("API_SPORTS_KEY")     # baloncesto / tenis (misma plataforma)

# Hoja de apuestas
SHEET_NAME_BETS   = "Apuestas"
SHEET_NAME_STATS  = "Resumen"

# Columnas del sheet (A=1, B=2, ...)
COL = {
    "ID":         1,
    "FECHA":      2,
    "CASA":       3,
    "DEPORTE":    4,
    "EVENTO":     5,
    "FECHA_PARTIDO": 6,
    "TIPO":       7,
    "DESCRIPCION":8,
    "CUOTA":      9,
    "IMPORTE":    10,
    "ESTADO":     11,   # PENDIENTE / GANADA / PERDIDA / VOID
    "RESULTADO":  12,
    "BENEFICIO":  13,
    "NOTAS":      14,
}

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_GANADA    = "GANADA"
ESTADO_PERDIDA   = "PERDIDA"
ESTADO_VOID      = "VOID"

# ── Temas del grupo de Telegram ──────────────────────────────
# Rellena estos IDs después de crear los temas en el grupo.
# Para obtener el ID de un tema: activa el modo de depuración
# enviando cualquier mensaje en ese tema y mirando "message_thread_id"
# en los logs (el bot los imprime al arrancar con nivel INFO).
# Ponlos también en el .env para no hardcodearlos aquí.
TOPIC_CAPTURAS       = int(os.getenv("TOPIC_CAPTURAS", 0))       # "Capturas y Resultados"
TOPIC_ESTADISTICAS   = int(os.getenv("TOPIC_ESTADISTICAS", 0))   # "Estadísticas"
TOPIC_CIERRE         = int(os.getenv("TOPIC_CIERRE", 0))          # "Cierre Mensual"
TOPIC_SALDO          = int(os.getenv("TOPIC_SALDO", 0))           # "Consultar saldo"
