"""Telegram bot application factory."""

from __future__ import annotations

import logging
from typing import Any

from telegram.ext import Application, ApplicationBuilder, CommandHandler

from verre.bot import handlers

logger = logging.getLogger(__name__)


def build_application(token: str) -> Application[Any, Any, Any, Any, Any, Any]:
    """Build a python-telegram-bot ``Application`` with all handlers wired up."""
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", handlers.start_cmd))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("setkeys", handlers.setkeys_cmd))
    app.add_handler(CommandHandler("keys", handlers.keys_cmd))
    app.add_handler(CommandHandler("track", handlers.track_cmd))
    app.add_handler(CommandHandler("untrack", handlers.untrack_cmd))
    app.add_handler(CommandHandler("list", handlers.list_cmd))
    app.add_handler(CommandHandler("size", handlers.size_cmd))
    app.add_handler(CommandHandler("spotmirror", handlers.spotmirror_cmd))
    app.add_handler(CommandHandler("mode", handlers.mode_cmd))
    app.add_handler(CommandHandler("status", handlers.status_cmd))
    app.add_handler(CommandHandler("positions", handlers.positions_cmd))
    app.add_handler(CommandHandler("stop", handlers.stop_cmd))
    app.add_handler(CommandHandler("search", handlers.search_cmd))
    return app
