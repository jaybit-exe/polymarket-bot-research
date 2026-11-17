import json, os, sys, tempfile, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
import book_hub, lane_guard, luck_vs_edge as lve


def test_stale_quote_is_refused_and_fresh_is_returned():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "books.json")
        s = book_hub.BookStore(p)
        s.update("m1", 0.4, 0.5, now=1000.0); s.publish()
        assert book_hub.read_quote(p, "m1", max_age_s=5, now=1003.0)["ask"] == 0.5
        assert book_hub.read_quote(p, "m1", max_age_s=5, now=1010.0) is None
        assert book_hub.read_quote(p, "missing", max_age_s=5) is None


def test_publish_is_atomic_json():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "books.json")
        s = book_hub.BookStore(p)
        for i in range(50):
            s.update("m", 0.1, 0.2); s.publish(); json.load(open(p))
        assert [f for f in os.listdir(d) if f.endswith(".tmp")] == []


def _trades(pnls):
    t0 = datetime(2026, 1, 1, 12, 0)
    return [lane_guard.Settled(t0 + timedelta(minutes=i), x) for i, x in enumerate(pnls)]


CFG = dict(max_drawdown=100, max_loss_streak=4, daily_loss_limit=60)  # illustrative toy limits


def test_rules_trip_independently():
    assert lane_guard.evaluate(_trades([10, 10, -5, -5, -5, -5]), lane_guard.GuardConfig(**CFG)) == ["loss_streak"]
    assert "drawdown" in lane_guard.evaluate(_trades([50, -60, 20, -70]), lane_guard.GuardConfig(**CFG))
    assert lane_guard.evaluate(_trades([5, -5, 5]), lane_guard.GuardConfig(**CFG)) == []


def test_alert_mode_never_blocks_enforce_latches_until_resume():
    bad = _trades([-30, -30, -30, -30])
    a, st = lane_guard.GuardConfig(**CFG), lane_guard.GuardState()
    assert lane_guard.step(st, bad, a) and lane_guard.may_trade(st, a)
    assert lane_guard.step(st, bad, a) == []                       # edge-triggered: no repeat alert
    e, st2 = lane_guard.GuardConfig(**CFG, mode="enforce"), lane_guard.GuardState()
    lane_guard.step(st2, bad, e)
    assert not lane_guard.may_trade(st2, e)
    lane_guard.resume(st2, "me", "reviewed")
    assert lane_guard.may_trade(st2, e)


def test_luck_share_is_high_for_fair_coinflips_and_low_for_a_lucky_streak():
    fair = [lve.Trade(0.5, 1, i % 2 == 0) for i in range(40)]           # exactly half won
    assert lve.luck_share(fair, sims=4000) > 0.3
    lucky = [lve.Trade(0.5, 1, True) for _ in range(30)]                # 30 for 30 at even odds
    assert lve.luck_share(lucky, sims=4000) < 0.001
