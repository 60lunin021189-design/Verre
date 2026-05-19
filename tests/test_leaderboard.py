"""Tests for the Binance Futures Leaderboard client (HTTP layer mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from verre.leaderboard import LeaderboardClient, LeaderboardError, LeaderPosition


@pytest.mark.asyncio
@respx.mock(base_url="https://www.binance.com")
async def test_get_other_position_parses_payload(respx_mock: respx.Router) -> None:
    respx_mock.post("/bapi/futures/v1/public/future/leaderboard/getOtherPosition").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "000000",
                "message": None,
                "data": {
                    "otherPositionRetList": [
                        {
                            "symbol": "BTCUSDT",
                            "entryPrice": 60000.0,
                            "markPrice": 61000.0,
                            "pnl": 100.0,
                            "roe": 0.05,
                            "amount": 0.5,
                            "leverage": 10,
                            "updateTimeStamp": 1700000000000,
                        },
                        {
                            "symbol": "ETHUSDT",
                            "entryPrice": 3000.0,
                            "markPrice": 2950.0,
                            "pnl": -50.0,
                            "roe": -0.02,
                            "amount": -2.0,
                            "leverage": 5,
                            "updateTimeStamp": 1700000001000,
                        },
                        # zero-amount position should be filtered out
                        {
                            "symbol": "SOLUSDT",
                            "entryPrice": 100.0,
                            "markPrice": 100.0,
                            "pnl": 0,
                            "roe": 0,
                            "amount": 0,
                            "leverage": 3,
                            "updateTimeStamp": 1700000002000,
                        },
                    ]
                },
            },
        )
    )

    async with LeaderboardClient() as client:
        positions = await client.get_other_position("abc123")

    assert len(positions) == 2
    btc, eth = positions
    assert isinstance(btc, LeaderPosition)
    assert btc.symbol == "BTCUSDT"
    assert btc.side == "LONG"
    assert btc.quantity == 0.5
    assert btc.entry_price == 60000.0
    assert eth.side == "SHORT"
    assert eth.quantity == 2.0


@pytest.mark.asyncio
@respx.mock(base_url="https://www.binance.com")
async def test_non_success_code_raises(respx_mock: respx.Router) -> None:
    respx_mock.post("/bapi/futures/v1/public/future/leaderboard/getOtherPosition").mock(
        return_value=httpx.Response(
            200,
            json={"code": "100001", "message": "rate limited", "data": None},
        )
    )

    async with LeaderboardClient() as client:
        with pytest.raises(LeaderboardError):
            await client.get_other_position("abc123")


@pytest.mark.asyncio
@respx.mock(base_url="https://www.binance.com")
async def test_search_returns_filtered_list(respx_mock: respx.Router) -> None:
    respx_mock.post("/bapi/futures/v3/public/future/leaderboard/searchLeaderboard").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "000000",
                "data": {
                    "list": [
                        {"encryptedUid": "uid-1", "nickName": "Alice", "roi": 0.5},
                        {"encryptedUid": "uid-2", "nickName": "Bob", "roi": 0.3},
                        "garbage",
                    ]
                },
            },
        )
    )

    async with LeaderboardClient() as client:
        results = await client.search("ali")
    assert len(results) == 2
    assert results[0]["encryptedUid"] == "uid-1"
