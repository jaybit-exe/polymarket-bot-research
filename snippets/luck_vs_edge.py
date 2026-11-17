"""Luck-versus-edge check (generic, sanitized).

Question: "My paper P&L is positive. If the market's own prices were fair, how often would a result this good
happen by luck?"

Method: for every trade, the market-implied win probability is the price paid (a contract bought at price p
pays 1 if it wins, so fair odds are p). Simulate the same trades many times with each outcome drawn at that
implied probability, with the same fee per trade, and count how often the simulated P&L is >= the observed one.
A small share means the result is hard to explain by luck alone. A large share means "could easily be luck".
It does not prove an edge, and it says nothing about whether the edge survives out of sample.
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Trade:
    price: float      # price paid per share, 0 < price < 1
    shares: float
    won: bool


def pnl(trade: Trade, win: bool, fee_per_share: float = 0.0) -> float:
    gross = trade.shares * ((1.0 - trade.price) if win else -trade.price)
    return gross - trade.shares * fee_per_share


def observed_pnl(trades: Sequence[Trade], fee_per_share: float = 0.0) -> float:
    return sum(pnl(t, t.won, fee_per_share) for t in trades)


def luck_share(trades: Sequence[Trade], fee_per_share: float = 0.0, sims: int = 20000, seed: int = 0) -> float:
    """Share of simulations (outcomes drawn at market-implied odds) with P&L >= observed."""
    rng = random.Random(seed)
    obs = observed_pnl(trades, fee_per_share)
    hits = 0
    for _ in range(sims):
        total = sum(pnl(t, rng.random() < t.price, fee_per_share) for t in trades)
        if total >= obs - 1e-9:
            hits += 1
    return hits / sims
