"""Periodic poller that drives the copy engine."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from verre.binance_trader import BinanceTrader
from verre.config import get_settings
from verre.copy_engine import (
    PlannedAction,
    apply_action_to_db,
    execute_action,
    fetch_all_users,
    fetch_mirror_state,
    fetch_tracked_leaders,
    plan_actions,
)
from verre.crypto import Cipher, EncryptionError
from verre.db import session_scope
from verre.leaderboard import LeaderboardClient, LeaderboardError
from verre.models import ApiKey, User

logger = logging.getLogger(__name__)

Notifier = Callable[[int, str], Awaitable[None]]


class Poller:
    """Periodic poller. Runs ``tick`` every ``interval`` seconds."""

    def __init__(
        self,
        notifier: Notifier,
        *,
        leaderboard: LeaderboardClient | None = None,
        cipher: Cipher | None = None,
        interval: int | None = None,
    ) -> None:
        self._notifier = notifier
        self._leaderboard = leaderboard or LeaderboardClient(
            timeout=get_settings().leaderboard_timeout
        )
        try:
            self._cipher: Cipher | None = cipher or Cipher(get_settings().encryption_key)
        except EncryptionError:
            self._cipher = None
        self._interval = interval or get_settings().poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="verre-poller")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._leaderboard.aclose()

    async def _loop(self) -> None:
        logger.info("Poller starting (interval=%ss)", self._interval)
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("Poller tick failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)

    async def tick(self) -> None:
        """One iteration: poll every tracked leader for every user."""
        async with session_scope() as session:
            users = await fetch_all_users(session)
        for user in users:
            try:
                await self._tick_user(user.id, user.telegram_id)
            except Exception:
                logger.exception("Failed processing user %s", user.telegram_id)

    async def _tick_user(self, user_id: int, telegram_id: int) -> None:
        async with session_scope() as session:
            tracked = await fetch_tracked_leaders(session, user_id)
            user_obj = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user_obj is None:
                return
            api_key_row = (
                await session.execute(select(ApiKey).where(ApiKey.user_id == user_id))
            ).scalar_one_or_none()

        if not tracked:
            return

        trader: BinanceTrader | None = None
        futures_balance = 0.0
        if user_obj.mode == "live":
            if api_key_row is None or self._cipher is None:
                await self._notifier(
                    telegram_id,
                    "⚠️ live mode без API ключей или без VERRE_ENCRYPTION_KEY — пропускаю.",
                )
                return
            try:
                api_key = self._cipher.decrypt(api_key_row.encrypted_key)
                api_secret = self._cipher.decrypt(api_key_row.encrypted_secret)
            except EncryptionError:
                await self._notifier(
                    telegram_id, "⚠️ Не получилось расшифровать API ключи. Перезадай /setkeys."
                )
                return
            trader = await BinanceTrader.create(
                api_key, api_secret, testnet=get_settings().binance_testnet
            )
            try:
                futures_balance = await trader.futures_usdt_balance()
            except Exception:
                logger.exception("Failed to fetch futures balance for user %s", telegram_id)
                await trader.close()
                return
        else:
            futures_balance = 1000.0  # placeholder for dry-run sizing

        try:
            for leader in tracked:
                await self._tick_leader(
                    user_obj,
                    leader.leader_uid,
                    futures_balance=futures_balance,
                    trader=trader,
                )
        finally:
            if trader is not None:
                await trader.close()

    async def _tick_leader(
        self,
        user_obj: object,
        leader_uid: str,
        *,
        futures_balance: float,
        trader: BinanceTrader | None,
    ) -> None:
        try:
            positions = await self._leaderboard.get_other_position(leader_uid)
        except LeaderboardError as exc:
            logger.warning("Leaderboard error for %s: %s", leader_uid, exc)
            return
        except Exception:
            logger.exception("Leaderboard fetch failed for %s", leader_uid)
            return

        async with session_scope() as session:
            mirror_state = await fetch_mirror_state(session, user_obj.id, leader_uid)  # type: ignore[attr-defined]

        actions = plan_actions(
            user_obj,  # type: ignore[arg-type]
            leader_uid,
            positions,
            mirror_state,
            futures_balance=futures_balance,
            spot_mirror_enabled=user_obj.spot_mirror_enabled,  # type: ignore[attr-defined]
        )
        for action in actions:
            await self._handle_action(action, trader)

    async def _handle_action(self, action: PlannedAction, trader: BinanceTrader | None) -> None:
        msg_lines = [
            f"{'[DRY-RUN] ' if action.dry_run else ''}{action.action.upper()} {action.market}",
            f"  {action.symbol} {action.side} qty={action.quantity:.6f}",
            f"  ref_price={action.reference_price:.6f}",
            f"  leader={action.leader_uid[:10]}…",
            f"  reason={action.reason}",
        ]
        if action.dry_run or trader is None:
            await self._notifier(action.telegram_id, "\n".join(msg_lines))
            async with session_scope() as session:
                with contextlib.suppress(IntegrityError):
                    await apply_action_to_db(session, action)
            return

        try:
            summary = await execute_action(trader, action)
        except Exception as exc:
            logger.exception("Order execution failed")
            await self._notifier(
                action.telegram_id, "❌ Order failed:\n" + "\n".join(msg_lines) + f"\n\n{exc}"
            )
            return

        async with session_scope() as session:
            with contextlib.suppress(IntegrityError):
                await apply_action_to_db(session, action)

        msg_lines.append(
            f"  ✓ executed: {summary['side']} {summary['quantity']} {summary['symbol']}"
        )
        await self._notifier(action.telegram_id, "\n".join(msg_lines))
