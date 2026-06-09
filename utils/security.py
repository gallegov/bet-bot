"""
Middleware de seguridad.
Bloquea silenciosamente cualquier mensaje que no venga del grupo autorizado.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from config.settings import ALLOWED_GROUP_ID

logger = logging.getLogger(__name__)

async def security_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Devuelve True si el mensaje es válido (viene del grupo autorizado).
    Devuelve False y no responde nada si viene de otro sitio.

    Si ALLOWED_GROUP_ID es 0 (no configurado), deja pasar todo.
    """
    if ALLOWED_GROUP_ID == 0:
        return True

    chat = update.effective_chat
    if chat is None:
        return False

    if chat.id != ALLOWED_GROUP_ID:
        logger.warning(
            f"Mensaje bloqueado — chat_id={chat.id} ({chat.type}) "
            f"no es el grupo autorizado ({ALLOWED_GROUP_ID})"
        )
        return False  # silencio total, no respondemos nada

    return True
