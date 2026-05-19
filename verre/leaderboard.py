"""Client for the public Binance Futures Leaderboard endpoints.

These endpoints are unofficial (under ``/bapi/futures/v*/public/future/leaderboard``)
but have been publicly accessible for years and are used by virtually every
Binance copy-trading tool. We send a JSON POST body and parse the standard
``{code, message, data}`` envelope.

We expose three primary calls:

* :py:meth:`LeaderboardClient.get_other_position` — current open positions for a
  given ``encryptedUid``.
* :py:meth:`LeaderboardClient.get_other_performance` — performance stats.
* :py:meth:`LeaderboardClient.search` — search top traders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://www.binance.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "clienttype": "web",
}


class LeaderboardError(RuntimeError):
    """Raised when the leaderboard API returns a non-success envelope."""


@dataclass(frozen=True)
class LeaderPosition:
    """A single open position from a leader's portfolio."""

    symbol: str
    entry_price: float
    mark_price: float
    pnl: float
    roe: float
    amount: float  # signed: positive = LONG, negative = SHORT
    leverage: float | None
    update_time_ms: int | None

    @property
    def side(self) -> str:
        return "LONG" if self.amount > 0 else "SHORT"

    @property
    def quantity(self) -> float:
        return abs(self.amount)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> LeaderPosition:
        return cls(
            symbol=str(raw.get("symbol", "")).upper(),
            entry_price=float(raw.get("entryPrice", 0) or 0),
            mark_price=float(raw.get("markPrice", 0) or 0),
            pnl=float(raw.get("pnl", 0) or 0),
            roe=float(raw.get("roe", 0) or 0),
            amount=float(raw.get("amount", 0) or 0),
            leverage=(float(raw["leverage"]) if raw.get("leverage") is not None else None),
            update_time_ms=(
                int(raw["updateTimeStamp"]) if raw.get("updateTimeStamp") is not None else None
            ),
        )


class LeaderboardClient:
    """Thin async wrapper around the Binance Futures Leaderboard endpoints."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> LeaderboardClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, headers=HEADERS
            )
            self._owns_client = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, headers=HEADERS
            )
            self._owns_client = True
        return self._client

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        resp = await client.post(path, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise LeaderboardError(f"Unexpected response shape: {data!r}")
        code = str(data.get("code", ""))
        if code and code != "000000":
            raise LeaderboardError(f"Binance returned code={code}: {data.get('message')}")
        return data

    async def get_other_position(
        self, encrypted_uid: str, trade_type: str = "PERPETUAL"
    ) -> list[LeaderPosition]:
        """Return the leader's current open positions on USDⓈ-M perpetuals."""
        payload = {"encryptedUid": encrypted_uid, "tradeType": trade_type}
        data = await self._post(
            "/bapi/futures/v1/public/future/leaderboard/getOtherPosition", payload
        )
        inner = data.get("data") or {}
        raw_positions = inner.get("otherPositionRetList") or []
        result: list[LeaderPosition] = []
        for raw in raw_positions:
            if not isinstance(raw, dict):
                continue
            try:
                pos = LeaderPosition.from_raw(raw)
            except (TypeError, ValueError):
                continue
            if pos.quantity <= 0 or not pos.symbol:
                continue
            result.append(pos)
        return result

    async def get_other_performance(
        self,
        encrypted_uid: str,
        trade_type: str = "PERPETUAL",
        period_type: str = "EXACT_WEEKLY",
    ) -> dict[str, Any]:
        """Return performance stats (ROI/PnL/period) for the leader."""
        payload = {
            "encryptedUid": encrypted_uid,
            "tradeType": trade_type,
            "periodType": period_type,
        }
        data = await self._post(
            "/bapi/futures/v1/public/future/leaderboard/getOtherPerformance", payload
        )
        return data.get("data") or {}

    async def search(self, keyword: str) -> list[dict[str, Any]]:
        """Search the leaderboard for traders by nickname."""
        payload = {
            "keyword": keyword,
            "tradeType": "PERPETUAL",
            "statisticsType": "ROI",
            "periodType": "EXACT_WEEKLY",
            "isShared": True,
            "isTrader": False,
        }
        data = await self._post(
            "/bapi/futures/v3/public/future/leaderboard/searchLeaderboard", payload
        )
        inner = data.get("data") or {}
        result = inner.get("list") or []
        return [item for item in result if isinstance(item, dict)]
