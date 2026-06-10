import anthropic
import base64
import json
import re
from config.settings import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROMPT = """Analiza esta captura de pantalla de una apuesta deportiva y extrae los datos en JSON.

Devuelve ÚNICAMENTE el JSON, sin texto adicional, con esta estructura exacta:
{
  "casa": "nombre de la casa de apuestas (Bet365, Codere, Betway, etc.)",
  "deporte": "Futbol | Baloncesto | Tenis | Otro",
  "evento": "Equipo/Jugador A vs Equipo/Jugador B",
  "fecha_partido": "DD/MM/YYYY o null si no se ve",
  "tipo": "1X2 | Handicap | Over/Under | Ganador | Set | Otro",
  "descripcion": "descripción exacta de la apuesta (ej: Real Madrid - Gana, Over 2.5)",
  "cuota": 2.10,
  "importe": 50.00,
  "notas": "cualquier dato extra relevante o null"
}

Si no puedes leer algún campo claramente, usa null.
La cuota e importe deben ser números (float), no texto."""

def extract_bet_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Limpia posibles bloques ```json ... ```
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
