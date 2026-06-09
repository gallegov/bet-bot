"""
Extracción de datos de Surebets mediante Claude Vision.
Soporta una imagen (boleto doble) o dos imágenes separadas.
"""

import anthropic
import base64
import json
import re
from config.settings import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROMPT = """Analiza los boletos de apuesta y devuelve ÚNICAMENTE un JSON con esta estructura exacta, sin texto adicional ni bloques de código:
{
  "tipo": "Surebet",
  "estado": "Pendiente",
  "partido": "Equipo A vs Equipo B",
  "apuesta_1": {
    "casa_de_apuestas": "Nombre Casa A",
    "pronostico": "Pronóstico A (ej: Victoria local, Over 2.5...)",
    "cuota": 2.10,
    "cantidad_apostada": 50.00
  },
  "apuesta_2": {
    "casa_de_apuestas": "Nombre Casa B",
    "pronostico": "Pronóstico B",
    "cuota": 1.95,
    "cantidad_apostada": 53.84
  }
}
Las cuotas y cantidades deben ser números float. Si algún campo no es legible usa null."""


def _encode(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def _parse_json(raw: str) -> dict | None:
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def extract_surebet_from_images(images: list[bytes], mime_type: str = "image/jpeg") -> dict | None:
    """
    Extrae datos de surebet de 1 o 2 imágenes.
    - 1 imagen: boleto doble o pantalla partida
    - 2 imágenes: cada una con un boleto diferente
    """
    content = []

    for img_bytes in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": _encode(img_bytes),
            }
        })

    content.append({"type": "text", "text": PROMPT})

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": content}]
    )

    return _parse_json(message.content[0].text.strip())


def validate_surebet(data: dict) -> tuple[bool, str]:
    """
    Valida que el JSON extraído tenga todos los campos necesarios.
    Devuelve (True, "") si es válido, (False, motivo) si no.
    """
    if not data:
        return False, "No se pudieron extraer datos"

    for key in ("partido", "apuesta_1", "apuesta_2"):
        if not data.get(key):
            return False, f"Falta el campo '{key}'"

    for n, apuesta in (("apuesta_1", data["apuesta_1"]), ("apuesta_2", data["apuesta_2"])):
        for campo in ("casa_de_apuestas", "pronostico", "cuota", "cantidad_apostada"):
            if apuesta.get(campo) is None:
                return False, f"Falta '{campo}' en {n}"
        try:
            float(apuesta["cuota"])
            float(apuesta["cantidad_apostada"])
        except (TypeError, ValueError):
            return False, f"Cuota o importe no numérico en {n}"

    return True, ""
