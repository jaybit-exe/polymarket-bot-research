"""Alert-mode risk guard design (generic, sanitized).

A guard reads a lane's settled-trade ledger and evaluates three independent rules:
  1. drawdown from the running peak of cumulative P&L,
  2. consecutive losses,
  3. realized loss within the current trading day.

Modes
  alert   - a tripped rule is recorded (and shown on the dashboard) but never blocks trading.
            Right for a paper test: you keep collecting unbiased data and still see what *would* have stopped you.
  enforce - a tripped rule latches a pause until a human resumes the lane. Right once real money is involved.

Design points worth copying
  * Limits are required constructor arguments. This file ships no recommended numbers.
  * Evaluation is a pure function of the ledger, so it can be replayed over history to ask
    "would this rule have tripped, and when?" before it is switched on.
  * Trips are edge-triggered: one alert per trip, not one per evaluation.
  * Fail open for alert mode: a guard bug must never stop a paper bot; in enforce mode the caller decides.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class Settled:
    ts: datetime
    pnl: float


@dataclass(frozen=True)
class GuardConfig:
    max_drawdown: float      # positive number: loss from peak cumulative P&L that trips the rule
    max_loss_streak: int
    daily_loss_limit: float  # positive number: net loss within one calendar day that trips the rule
    mode: str = "alert"      # "alert" | "enforce"


@dataclass
class GuardState:
    tripped: List[str] = field(default_factory=list)   # rule names currently latched
    paused: bool = False                               # only ever True in enforce mode


def evaluate(trades: Iterable[Settled], cfg: GuardConfig) -> List[str]:
    """Return the names of rules that are tripped right now (pure function)."""
    trades = sorted(trades, key=lambda t: t.ts)
    out: List[str] = []
    cum = peak = 0.0
    streak = 0
    for t in trades:
        cum += t.pnl
        peak = max(peak, cum)
        streak = streak + 1 if t.pnl < 0 else 0
    if peak - cum >= cfg.max_drawdown:
        out.append("drawdown")
    if streak >= cfg.max_loss_streak:
        out.append("loss_streak")
    if trades:
        day = trades[-1].ts.date()
        if -sum(t.pnl for t in trades if t.ts.date() == day) >= cfg.daily_loss_limit:
            out.append("daily_loss")
    return out


def step(state: GuardState, trades: Iterable[Settled], cfg: GuardConfig) -> List[str]:
    """Advance the guard one evaluation. Returns rules that newly tripped (the alerts to emit)."""
    now_tripped = evaluate(trades, cfg)
    new = [r for r in now_tripped if r not in state.tripped]
    state.tripped = sorted(set(state.tripped) | set(now_tripped))
    if cfg.mode == "enforce" and new:
        state.paused = True          # latched: only resume() clears it
    return new


def resume(state: GuardState, by: str, note: str) -> None:
    """Manual resume. Require a name and a note so every restart leaves an audit trail."""
    if not by or not note:
        raise ValueError("resume needs who and why")
    state.paused = False
    state.tripped = []


def may_trade(state: GuardState, cfg: GuardConfig) -> bool:
    return not (cfg.mode == "enforce" and state.paused)
