"""Notificaciones simples para la demo."""

import logging

logger = logging.getLogger("fona")


def connect():
    """No-op. Se mantiene para compatibilidad con main.py."""
    logger.info("Sistema de notificaciones iniciado")


async def push(title: str, body: str, category: str = "mensaje"):
    """Muestra una notificación en el log."""
    logger.info("[%s] %s: %s", category, title, body)