"""Core copy-trading engine.

The engine periodically diffs each tracked leader's open positions against the
mirrored state we have in the DB and emits actions: ``open`` (new mirror) or
``close`` (close mirror). Each action is then executed by a
:class:`verre.binance_trader.BinanceTrader` — unless the user is in dry-run mode,
in which case we only emit a notification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from verre.binance_trader import BinanceTrader
from verre.leaderboard import LeaderPosition
from verre.models import MirroredPosition, TrackedLeader, User

logger = logging.getLogger(__name__)

Market = Literal["FUTURES", "SPOT"]
Action = Literal["open", "close"]


@dataclass(frozen=True)
class PlannedAction:
    """A single action the engine decided to perform."""

    user_id: int
    telegram_id: int
    leader_uid: str
    action: Action
    market: Market
    symbol: str
    side: str  # "LONG" or "SHORT" (for FUTURES) or "BUY"/"SELL" intent for spot
    quantity: float
    reference_price: float
    leverage: float | None = None
    dry_run: bool = True
    reason: str = ""


def plan_actions(
    user: User,
    leader_uid: str,
    leader_positions: list[LeaderPosition],
    current_mirror: list[MirroredPosition],
    *,
    futures_balance: float,
    spot_mirror_enabled: bool,
) -> list[PlannedAction]:
    """Compute the list of actions to take for a given leader's snapshot.

    The function is pure: it does not perform IO. It only returns the actions
    that should be executed.

    The position-size rule is simple: each new mirrored position uses
    ``user.size_percent`` of the user's USDⓈ-M USDT balance, sized at the
    leader's entry price (rounded down). Leverage is *not* applied on the user
    side automatically — the user's account leverage / margin mode settings are
    respected.
    """
    actions: list[PlannedAction] = []

    leader_by_key = {(p.symbol, p.side): p for p in leader_positions}
    mirror_by_key = {
        (m.symbol, m.position_side): m for m in current_mirror if m.market == "FUTURES"
    }
    spot_mirror_by_symbol = {m.symbol: m for m in current_mirror if m.market == "SPOT"}

    size_fraction = max(0.0, min(user.size_percent / 100.0, 1.0))

    for key, pos in leader_by_key.items():
        if key in mirror_by_key:
            continue
        if pos.entry_price <= 0:
            continue
        notional = futures_balance * size_fraction
        if notional <= 0:
            continue
        qty = notional / pos.entry_price
        if qty <= 0:
            continue
        actions.append(
            PlannedAction(
                user_id=user.id,
                telegram_id=user.telegram_id,
                leader_uid=leader_uid,
                action="open",
                market="FUTURES",
                symbol=pos.symbol,
                side=pos.side,
                quantity=qty,
                reference_price=pos.entry_price,
                leverage=pos.leverage,
                dry_run=user.mode != "live",
                reason="Leader opened position",
            )
        )
        if spot_mirror_enabled and pos.side == "LONG":
            actions.append(
                PlannedAction(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    leader_uid=leader_uid,
                    action="open",
                    market="SPOT",
                    symbol=pos.symbol,
                    side="BUY",
                    quantity=qty,
                    reference_price=pos.entry_price,
                    leverage=None,
                    dry_run=user.mode != "live",
                    reason="Spot mirror of LONG futures signal",
                )
            )

    for key, mirror in mirror_by_key.items():
        if key in leader_by_key:
            continue
        actions.append(
            PlannedAction(
                user_id=user.id,
                telegram_id=user.telegram_id,
                leader_uid=leader_uid,
                action="close",
                market="FUTURES",
                symbol=mirror.symbol,
                side=mirror.position_side,
                quantity=mirror.quantity,
                reference_price=mirror.entry_price,
                leverage=mirror.leverage,
                dry_run=user.mode != "live",
                reason="Leader closed position",
            )
        )
        spot_mirror = spot_mirror_by_symbol.get(mirror.symbol)
        if spot_mirror is not None and mirror.position_side == "LONG":
            actions.append(
                PlannedAction(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    leader_uid=leader_uid,
                    action="close",
                    market="SPOT",
                    symbol=spot_mirror.symbol,
                    side="SELL",
                    quantity=spot_mirror.quantity,
                    reference_price=spot_mirror.entry_price,
                    leverage=None,
                    dry_run=user.mode != "live",
                    reason="Spot mirror close of LONG futures",
                )
            )

    return actions


async def fetch_mirror_state(
    session: AsyncSession, user_id: int, leader_uid: str
) -> list[MirroredPosition]:
    stmt = select(MirroredPosition).where(
        MirroredPosition.user_id == user_id, MirroredPosition.leader_uid == leader_uid
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_tracked_leaders(session: AsyncSession, user_id: int) -> list[TrackedLeader]:
    stmt = select(TrackedLeader).where(TrackedLeader.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_all_users(session: AsyncSession) -> list[User]:
    stmt = select(User)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def execute_action(trader: BinanceTrader, action: PlannedAction) -> dict[str, str]:
    """Execute a single planned action and return a small summary dict.

    Raises any exception from the trader.
    """
    if action.market == "FUTURES":
        if action.action == "open":
            side = "BUY" if action.side == "LONG" else "SELL"
            result = await trader.open_futures_market(action.symbol, side, action.quantity)
        else:
            result = await trader.close_futures_market(action.symbol, action.side, action.quantity)
    else:  # SPOT
        result = await trader.spot_market(action.symbol, action.side, action.quantity)
    return {
        "market": result.market,
        "symbol": result.symbol,
        "side": result.side,
        "quantity": str(result.quantity),
    }


async def apply_action_to_db(session: AsyncSession, action: PlannedAction) -> None:
    """Update the mirror state in the DB to reflect the executed action."""
    if action.action == "open":
        session.add(
            MirroredPosition(
                user_id=action.user_id,
                leader_uid=action.leader_uid,
                symbol=action.symbol,
                position_side=action.side if action.market == "FUTURES" else "LONG",
                market=action.market,
                quantity=action.quantity,
                entry_price=action.reference_price,
                leverage=action.leverage,
            )
        )
        return

    stmt = select(MirroredPosition).where(
        MirroredPosition.user_id == action.user_id,
        MirroredPosition.leader_uid == action.leader_uid,
        MirroredPosition.symbol == action.symbol,
        MirroredPosition.market == action.market,
    )
    if action.market == "FUTURES":
        stmt = stmt.where(MirroredPosition.position_side == action.side)
    result = await session.execute(stmt)
    for row in result.scalars().all():
        await session.delete(row)
