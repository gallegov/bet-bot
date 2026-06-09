"""
Decide si una apuesta ha ganado, perdido o no se puede resolver,
cruzando los datos del sheet con el resultado deportivo.
"""

from config.settings import ESTADO_GANADA, ESTADO_PERDIDA

def resolver_apuesta(bet: dict, resultado: dict) -> tuple[str, str, float]:
    """
    Parámetros:
        bet       – fila del sheet (dict con columnas como claves)
        resultado – dict devuelto por sports_service.get_result()

    Retorna:
        (estado, descripcion_resultado, beneficio_neto)
    """
    if resultado is None or resultado.get("estado") != "finalizado":
        return None, None, 0.0

    tipo        = str(bet.get("Tipo apuesta", "")).upper()
    descripcion = str(bet.get("Descripción", "")).lower()
    cuota       = float(bet.get("Cuota", 1))
    importe     = float(bet.get("Importe (€)", 0))

    ganado = False
    desc_resultado = resultado.get("marcador") or resultado.get("ganador") or "Finalizado"

    # ── 1X2 / GANADOR ────────────────────────────────────────────────
    if tipo in ("1X2", "GANADOR") or any(k in descripcion for k in ["gana", "victoria", "winner"]):
        signo = resultado.get("signo")      # fútbol
        ganador = resultado.get("ganador")  # baloncesto/tenis

        if signo:
            if "local" in descripcion or "1" == descripcion.strip() or resultado.get("home", "").lower() in descripcion:
                ganado = signo == "1"
            elif "empate" in descripcion or "x" == descripcion.strip():
                ganado = signo == "X"
            elif "visitante" in descripcion or "2" == descripcion.strip() or resultado.get("away", "").lower() in descripcion:
                ganado = signo == "2"
        elif ganador:
            ganado = ganador.lower() in descripcion

    # ── OVER / UNDER ─────────────────────────────────────────────────
    elif "over" in descripcion or "under" in descripcion or "más" in descripcion or "menos" in descripcion:
        total = resultado.get("total_goles") or resultado.get("total_puntos")
        if total is not None:
            # Extrae el número de la descripción, ej: "over 2.5"
            import re
            match = re.search(r"(\d+(?:\.\d+)?)", descripcion)
            if match:
                linea = float(match.group(1))
                if "over" in descripcion or "más" in descripcion:
                    ganado = total > linea
                else:
                    ganado = total < linea

    # ── HANDICAP ─────────────────────────────────────────────────────
    elif "handicap" in tipo.lower() or "handicap" in descripcion:
        # Lógica básica: extrae handicap y calcula
        import re
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", descripcion)
        if match and resultado.get("marcador"):
            handicap = float(match.group(1))
            marcador = resultado["marcador"]
            gh, ga = map(int, marcador.split("-"))
            # Asumimos handicap sobre local
            if resultado.get("home", "").lower() in descripcion or "local" in descripcion:
                ganado = (gh + handicap) > ga
            else:
                ganado = (ga + handicap) > gh

    # ── Calcular beneficio ────────────────────────────────────────────
    if ganado:
        beneficio = round(importe * cuota - importe, 2)
        estado = ESTADO_GANADA
    else:
        beneficio = -importe
        estado = ESTADO_PERDIDA

    return estado, desc_resultado, beneficio
