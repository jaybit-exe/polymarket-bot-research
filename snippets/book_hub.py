"""Shared market-data hub pattern (generic, sanitized).

One process owns the single WebSocket connection and publishes the latest top-of-book per market to a small
JSON file. Every consumer (paper bots, dashboards) reads that file instead of opening its own connection.

Why: (1) one authenticated connection instead of one per bot, (2) every consumer sees the same data,
(3) every quote carries its own receive timestamp, so consumers can refuse stale data instead of trading on it.

This module is exchange-agnostic: you supply the URL, the subscribe message and a `parse` function that turns
one raw message into {market_id: (best_bid, best_ask)}. No venue-specific details are included.
"""
from __future__ import annotations
import json, os, tempfile, time
from typing import Callable, Dict, Optional, Tuple

Quote = Tuple[Optional[float], Optional[float]]


class BookStore:
    """Holds the latest quote per market and publishes it atomically."""

    def __init__(self, path: str):
        self.path = path
        self.quotes: Dict[str, dict] = {}

    def update(self, market_id: str, bid: Optional[float], ask: Optional[float], now: Optional[float] = None) -> None:
        self.quotes[market_id] = {"bid": bid, "ask": ask, "recv_ts": now if now is not None else time.time()}

    def publish(self) -> None:
        # Write to a temp file in the same directory, then rename: readers never see a half-written file.
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".books.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"written_ts": time.time(), "quotes": self.quotes}, f)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def read_quote(path: str, market_id: str, max_age_s: float, now: Optional[float] = None) -> Optional[dict]:
    """Return the quote, or None if it is missing, unreadable or older than `max_age_s`.

    `max_age_s` is deliberately a required argument: the staleness budget is a strategy decision, not a default.
    A None result means "skip this decision", never "fall back to some other price source".
    """
    try:
        with open(path) as f:
            doc = json.load(f)
        q = doc["quotes"][market_id]
    except (OSError, ValueError, KeyError):
        return None
    now = now if now is not None else time.time()
    if now - q["recv_ts"] > max_age_s:
        return None
    return q


async def run_hub(url: str, subscribe_msg: dict, parse: Callable[[str], Dict[str, Quote]], store: BookStore,
                  publish_every_s: float = 0.5, reconnect_delay_s: float = 5.0) -> None:
    """Connect, subscribe, update the store on every message, publish on a timer; reconnect on any error."""
    import asyncio
    import websockets  # pip install websockets

    async def publisher():
        while True:
            store.publish()
            await asyncio.sleep(publish_every_s)

    while True:
        task = asyncio.ensure_future(publisher())
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(subscribe_msg))
                async for raw in ws:
                    for market_id, (bid, ask) in parse(raw).items():
                        store.update(market_id, bid, ask)
        except Exception as exc:  # log and reconnect; staleness checks protect consumers meanwhile
            print(f"hub: connection lost ({type(exc).__name__}); retrying")
        finally:
            task.cancel()
        await asyncio.sleep(reconnect_delay_s)
