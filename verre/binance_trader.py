"""Binance trading client wrapper supporting both Futures (USDⓈ-M) and Spot.

Wraps :class:`binance.AsyncClient` so we can stub it out cleanly in tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from binance import AsyncClient

logger = logging.getLogger(__name__)


class _BinanceClientProto(Protocol):  # pragma: no cover - structural typing only
    async def futures_create_order(self, **params: Any) -> dict[str, Any]: ...
    async def futures_account_balance(self, **params: Any) -> list[dict[str, Any]]: ...
    async def futures_exchange_info(self, **params: Any) -> dict[str, Any]: ...
    async def get_symbol_ticker(self, **params: Any) -> dict[str, Any]: ...
    async def create_order(self, **params: Any) -> dict[str, Any]: ...
    async def get_account(self, **params: Any) -> dict[str, Any]: ...
    async def get_exchange_info(self) -> dict[str, Any]: ...
    async def close_connection(self) -> None: ...


@dataclass(frozen=True)
class OrderResult:
    """Normalized result of placing an order."""

    market: str  # "FUTURES" or "SPOT"
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    raw: dict[str, Any]


class BinanceTrader:
    """High-level wrapper for placing market orders on Binance Futures and Spot."""

    def __init__(self, client: _BinanceClientProto) -> None:
        self._client = client

    @classmethod
    async def create(cls, api_key: str, api_secret: str, testnet: bool = False) -> BinanceTrader:
        client = await AsyncClient.create(api_key, api_secret, testnet=testnet)
        return cls(client)

    async def close(self) -> None:
        await self._client.close_connection()

    async def futures_usdt_balance(self) -> float:
        """Return the available USDT balance on USDⓈ-M futures."""
        balances = await self._client.futures_account_balance()
        for bal in balances:
            if bal.get("asset") == "USDT":
                return float(bal.get("availableBalance", bal.get("balance", 0)) or 0)
        return 0.0

    async def spot_usdt_balance(self) -> float:
        """Return the free USDT balance on the spot account."""
        acct = await self._client.get_account()
        for bal in acct.get("balances", []):
            if bal.get("asset") == "USDT":
                return float(bal.get("free", 0) or 0)
        return 0.0

    async def get_mark_price(self, symbol: str) -> float:
        """Best-effort symbol price (used for sizing). Uses futures ticker."""
        ticker = await self._client.get_symbol_ticker(symbol=symbol)
        return float(ticker.get("price", 0) or 0)

    async def open_futures_market(self, symbol: str, side: str, quantity: float) -> OrderResult:
        """Open a futures position via a MARKET order. ``side`` is BUY/SELL."""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": _format_qty(quantity),
        }
        raw = await self._client.futures_create_order(**params)
        return OrderResult(
            market="FUTURES", symbol=symbol, side=side.upper(), quantity=quantity, raw=raw
        )

    async def close_futures_market(
        self, symbol: str, position_side: str, quantity: float
    ) -> OrderResult:
        """Close a futures position with a reduceOnly MARKET order.

        ``position_side`` is the side of the leader's original position: ``LONG``
        means we previously bought (so we sell to close); ``SHORT`` means we
        previously sold (so we buy to close).
        """
        side = "SELL" if position_side.upper() == "LONG" else "BUY"
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": _format_qty(quantity),
            "reduceOnly": True,
        }
        raw = await self._client.futures_create_order(**params)
        return OrderResult(market="FUTURES", symbol=symbol, side=side, quantity=quantity, raw=raw)

    async def spot_market(self, symbol: str, side: str, quantity: float) -> OrderResult:
        """Place a spot MARKET order."""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": _format_qty(quantity),
        }
        raw = await self._client.create_order(**params)
        return OrderResult(
            market="SPOT", symbol=symbol, side=side.upper(), quantity=quantity, raw=raw
        )


def _format_qty(quantity: float) -> str:
    """Render a quantity as a fixed-point string without scientific notation.

    Binance rejects scientific notation. We trim trailing zeros to keep messages
    readable.
    """
    if quantity <= 0:
        return "0"
    text = f"{quantity:.8f}".rstrip("0").rstrip(".")
    return text or "0"
