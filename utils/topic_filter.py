"""
Utilidad para restringir cada comando/mensaje al tema correcto del grupo.

Uso en un handler:
    from utils.topic_filter import check_topic, TEMA_CAPTURAS
    
    async def handle_bet_image(update, context):
        if not await check_topic(update, TEMA_CAPTURAS):
            return
        ...
"""

from telegram import Update
from telegram.ext import ContextTypes
from config.settings import (
    TOPIC_CAPTURAS, TOPIC_ESTADISTICAS,
    TOPIC_CIERRE, TOPIC_SALDO, TOPIC_SUREBETS
)

TEMA_CAPTURAS     = "capturas"
TEMA_ESTADISTICAS = "estadisticas"
TEMA_CIERRE       = "cierre"
TEMA_SALDO        = "saldo"
TEMA_SUREBETS     = "surebets"

_TOPIC_MAP = {
    TEMA_CAPTURAS:     (TOPIC_CAPTURAS,     "📸 Capturas y Resultados"),
    TEMA_ESTADISTICAS: (TOPIC_ESTADISTICAS, "📊 Estadísticas"),
    TEMA_CIERRE:       (TOPIC_CIERRE,       "📅 Cierre Mensual"),
    TEMA_SALDO:        (TOPIC_SALDO,        "💶 Consultar saldo"),
    TEMA_SUREBETS:     (TOPIC_SUREBETS,     "🔒 Surebets"),
}

def _get_thread_id(update: Update) -> int | None:
    """Devuelve el message_thread_id del mensaje, o None si no es un grupo con temas."""
    msg = update.effective_message
    return getattr(msg, "message_thread_id", None)

async def check_topic(update: Update, tema: str) -> bool:
    """
    Comprueba que el mensaje llegó al tema correcto.
    - Si los IDs de tema no están configurados (todos a 0), deja pasar todo
      para no bloquear durante el desarrollo.
    - Si el mensaje viene del tema equivocado, responde indicando el tema correcto
      y devuelve False para que el handler aborte.
    """
    expected_id, nombre = _TOPIC_MAP[tema]

    # Si no hay IDs configurados aún, modo permisivo
    if expected_id == 0:
        return True

    thread_id = _get_thread_id(update)

    # Mensaje fuera de cualquier tema (chat directo o grupo sin temas)
    if thread_id is None:
        return True

    if thread_id != expected_id:
        await update.effective_message.reply_text(
            f"⚠️ Este comando solo funciona en el tema *{nombre}*.",
            parse_mode="Markdown"
        )
        return False

    return True


def log_thread_id(update: Update):
    """
    Imprime el thread_id en consola para ayudar a configurar los IDs.
    Llama esto desde cualquier handler mientras configuras el grupo.
    """
    tid = _get_thread_id(update)
    chat = update.effective_chat
    print(f"[TOPIC DEBUG] chat_id={chat.id} | thread_id={tid} | chat='{chat.title}'")
