"""
Consulta resultados deportivos usando api-sports.io
- Fútbol:     api-football.com  (mismo key que API_FOOTBALL_KEY)
- Baloncesto: api-basketball.com
- Tenis:      api-tennis.com (resultados ATP/WTA)
"""

import requests
from datetime import datetime, timedelta
from rapidfuzz import fuzz
from config.settings import API_FOOTBALL_KEY, API_SPORTS_KEY

HEADERS_FOOTBALL    = {"x-apisports-key": API_FOOTBALL_KEY}
HEADERS_BASKETBALL  = {"x-apisports-key": API_SPORTS_KEY}
HEADERS_TENNIS      = {"x-apisports-key": API_SPORTS_KEY}

# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────

def _parse_date(date_str) -> str | None:
    """Convierte DD/MM/YYYY, número de serie de Sheets, o YYYY-MM-DD a YYYY-MM-DD."""
    if not date_str:
        return None

    s = str(date_str).strip()

    # Caso: número de serie de Google Sheets (fecha guardada como float)
    if s.replace(".", "", 1).isdigit():
        try:
            serial = float(s)
            dt = datetime(1899, 12, 30) + timedelta(days=serial)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def _best_match(query: str, candidates: list[str]) -> tuple[str, int]:
    """Devuelve el candidato más parecido y su score (0-100)."""
    best, score = "", 0
    for c in candidates:
        s = fuzz.token_set_ratio(query.lower(), c.lower())
        if s > score:
            best, score = c, s
    return best, score

# ─────────────────────────────────────────────
# FÚTBOL
# ─────────────────────────────────────────────

def get_football_result(evento: str, fecha_str: str) -> dict | None:
    """
    Busca el resultado de un partido de fútbol.
    Retorna dict con 'resultado', 'marcador', 'estado' o None si no encuentra.
    """
    date = _parse_date(fecha_str)
    if not date:
        # Intentamos los últimos 7 días
        date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    url = "https://v3.football.api-sports.io/fixtures"
    resp = requests.get(url, headers=HEADERS_FOOTBALL, params={"date": date}, timeout=10)
    if resp.status_code != 200:
        return None

    fixtures = resp.json().get("response", [])
    if not fixtures:
        return None

    # Construye lista de "Local vs Visitante"
    names = [
        f"{f['teams']['home']['name']} vs {f['teams']['away']['name']}"
        for f in fixtures
    ]
    best, score = _best_match(evento, names)

    if score < 55:
        return None

    idx = names.index(best)
    f = fixtures[idx]
    status = f["fixture"]["status"]["short"]   # FT, HT, NS, etc.

    if status != "FT":
        return {"estado": "no_finalizado", "marcador": None, "resultado": None}

    home = f["teams"]["home"]
    away = f["teams"]["away"]
    gh = f["goals"]["home"]
    ga = f["goals"]["away"]

    if gh > ga:
        ganador = home["name"]
        signo = "1"
    elif ga > gh:
        ganador = away["name"]
        signo = "2"
    else:
        ganador = "Empate"
        signo = "X"

    return {
        "estado": "finalizado",
        "marcador": f"{gh}-{ga}",
        "ganador": ganador,
        "signo": signo,         # "1", "X", "2"
        "total_goles": gh + ga,
        "home": home["name"],
        "away": away["name"],
    }

# ─────────────────────────────────────────────
# BALONCESTO
# ─────────────────────────────────────────────

def get_basketball_result(evento: str, fecha_str: str) -> dict | None:
    date = _parse_date(fecha_str)
    if not date:
        date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    url = "https://v1.basketball.api-sports.io/games"
    resp = requests.get(url, headers=HEADERS_BASKETBALL, params={"date": date}, timeout=10)
    if resp.status_code != 200:
        return None

    games = resp.json().get("response", [])
    names = [
        f"{g['teams']['home']['name']} vs {g['teams']['away']['name']}"
        for g in games
    ]
    best, score = _best_match(evento, names)
    if score < 55:
        return None

    idx = names.index(best)
    g = games[idx]

    if g["status"]["short"] != "FT":
        return {"estado": "no_finalizado", "marcador": None, "resultado": None}

    sh = g["scores"]["home"]["total"]
    sa = g["scores"]["away"]["total"]
    ganador = g["teams"]["home"]["name"] if sh > sa else g["teams"]["away"]["name"]

    return {
        "estado": "finalizado",
        "marcador": f"{sh}-{sa}",
        "ganador": ganador,
        "total_puntos": sh + sa,
        "home": g["teams"]["home"]["name"],
        "away": g["teams"]["away"]["name"],
    }

# ─────────────────────────────────────────────
# TENIS
# ─────────────────────────────────────────────

def get_tennis_result(evento: str, fecha_str: str) -> dict | None:
    date = _parse_date(fecha_str)
    if not date:
        date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    url = "https://v1.tennis.api-sports.io/games"
    resp = requests.get(url, headers=HEADERS_TENNIS, params={"date": date}, timeout=10)
    if resp.status_code != 200:
        return None

    games = resp.json().get("response", [])
    names = [
        f"{g['players']['home']['name']} vs {g['players']['away']['name']}"
        for g in games
    ]
    best, score = _best_match(evento, names)
    if score < 50:
        return None

    idx = names.index(best)
    g = games[idx]

    if g["status"]["short"] != "FT":
        return {"estado": "no_finalizado", "marcador": None, "resultado": None}

    ganador = g["winner"]["name"] if g.get("winner") else None

    return {
        "estado": "finalizado",
        "ganador": ganador,
        "home": g["players"]["home"]["name"],
        "away": g["players"]["away"]["name"],
    }

# ─────────────────────────────────────────────
# Dispatcher principal
# ─────────────────────────────────────────────

def get_result(deporte: str, evento: str, fecha_str: str) -> dict | None:
    d = deporte.lower()
    if "futbol" in d or "fútbol" in d or "football" in d or "soccer" in d:
        return get_football_result(evento, fecha_str)
    elif "balon" in d or "basket" in d or "nba" in d:
        return get_basketball_result(evento, fecha_str)
    elif "tenis" in d or "tennis" in d:
        return get_tennis_result(evento, fecha_str)
    return None
