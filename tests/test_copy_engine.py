"""Tests for the pure copy-engine planner."""

from __future__ import annotations

from verre.copy_engine import plan_actions
from verre.leaderboard import LeaderPosition
from verre.models import MirroredPosition, User


def _user(mode: str = "dryrun", size: float = 1.0, spot: bool = False) -> User:
    u = User()
    u.id = 1
    u.telegram_id = 99
    u.username = "tester"
    u.mode = mode
    u.size_percent = size
    u.spot_mirror_enabled = spot
    return u


def _pos(symbol: str, amount: float, entry: float, lev: float = 5.0) -> LeaderPosition:
    return LeaderPosition(
        symbol=symbol,
        entry_price=entry,
        mark_price=entry,
        pnl=0.0,
        roe=0.0,
        amount=amount,
        leverage=lev,
        update_time_ms=1,
    )


def _mirror(symbol: str, side: str, market: str, qty: float, entry: float) -> MirroredPosition:
    m = MirroredPosition()
    m.user_id = 1
    m.leader_uid = "LEADER"
    m.symbol = symbol
    m.position_side = side
    m.market = market
    m.quantity = qty
    m.entry_price = entry
    m.leverage = 5.0
    return m


def test_new_long_opens_futures_and_spot_when_enabled() -> None:
    user = _user(spot=True)
    leader_positions = [_pos("BTCUSDT", amount=0.5, entry=60000.0)]
    actions = plan_actions(
        user, "LEADER", leader_positions, [], futures_balance=10_000, spot_mirror_enabled=True
    )
    assert len(actions) == 2
    futures = [a for a in actions if a.market == "FUTURES"]
    spots = [a for a in actions if a.market == "SPOT"]
    assert len(futures) == 1
    assert futures[0].action == "open"
    assert futures[0].side == "LONG"
    assert futures[0].symbol == "BTCUSDT"
    # size_percent=1% of 10_000 = 100 USDT  → 100/60000 ≈ 0.00166...
    assert abs(futures[0].quantity - (100 / 60000)) < 1e-9
    assert futures[0].dry_run is True
    assert len(spots) == 1
    assert spots[0].side == "BUY"


def test_short_does_not_open_spot_mirror() -> None:
    user = _user(spot=True)
    leader_positions = [_pos("ETHUSDT", amount=-2.0, entry=3000.0)]
    actions = plan_actions(
        user, "L", leader_positions, [], futures_balance=10_000, spot_mirror_enabled=True
    )
    markets = [a.market for a in actions]
    assert markets == ["FUTURES"]
    assert actions[0].side == "SHORT"


def test_closed_position_triggers_close() -> None:
    user = _user(spot=True)
    leader_positions: list[LeaderPosition] = []  # all closed on leader side
    mirror = [
        _mirror("BTCUSDT", "LONG", "FUTURES", qty=0.001, entry=60000),
        _mirror("BTCUSDT", "LONG", "SPOT", qty=0.001, entry=60000),
    ]
    actions = plan_actions(
        user, "LEADER", leader_positions, mirror, futures_balance=10_000, spot_mirror_enabled=True
    )
    assert len(actions) == 2
    assert {a.action for a in actions} == {"close"}
    assert {a.market for a in actions} == {"FUTURES", "SPOT"}
    spot_close = next(a for a in actions if a.market == "SPOT")
    assert spot_close.side == "SELL"


def test_no_action_when_mirror_matches_leader() -> None:
    user = _user()
    leader_positions = [_pos("BTCUSDT", amount=0.5, entry=60000)]
    mirror = [_mirror("BTCUSDT", "LONG", "FUTURES", qty=0.001, entry=60000)]
    actions = plan_actions(
        user, "L", leader_positions, mirror, futures_balance=10_000, spot_mirror_enabled=False
    )
    assert actions == []


def test_live_mode_sets_dry_run_false() -> None:
    user = _user(mode="live")
    leader_positions = [_pos("BTCUSDT", amount=0.5, entry=60000)]
    actions = plan_actions(
        user, "L", leader_positions, [], futures_balance=10_000, spot_mirror_enabled=False
    )
    assert actions[0].dry_run is False


def test_zero_balance_yields_no_actions() -> None:
    user = _user()
    leader_positions = [_pos("BTCUSDT", amount=0.5, entry=60000)]
    actions = plan_actions(
        user, "L", leader_positions, [], futures_balance=0, spot_mirror_enabled=True
    )
    assert actions == []
