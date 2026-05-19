"""Entry point: ``python -m verre`` or ``verre`` (via console_scripts)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

from telegram.error import TelegramError

from verre.bot.app import build_application
from verre.config import get_settings
from verre.db import init_db
from verre.poller import Poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verre")


async def _amain() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. See .env.example.")
        sys.exit(2)

    await init_db()
    app = build_application(settings.telegram_bot_token)

    async def notifier(telegram_id: int, text: str) -> None:
        try:
            await app.bot.send_message(chat_id=telegram_id, text=text)
        except TelegramError:
            logger.exception("Failed to send Telegram message to %s", telegram_id)

    poller = Poller(notifier)

    async with app:
        await app.start()
        if app.updater is not None:
            await app.updater.start_polling()
        poller.start()
        logger.info("Verre is running. Press Ctrl+C to stop.")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _on_signal() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _on_signal)

        await stop_event.wait()
        logger.info("Shutting down…")
        await poller.stop()
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_amain())


if __name__ == "__main__":
    main()
