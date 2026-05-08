"""Tests for fdmon.alerts.AlertEngine."""

import time
import pytest

from fdmon.alerts import AlertEngine
from fdmon.config import AlertConfig, AlertThresholds
from fdmon.health import compute_health
from fdmon.models import AlertSeverity, TileHealth, TileSnapshot, TileStatus


def _make_engine(dedup_window_s=0.0):
    thresholds = AlertThresholds(
        heartbeat_stale_warn_s=3.0,
        heartbeat_stale_crit_s=8.0,
        heartbeat_lag_rate_warn=0.5,
        heartbeat_lag_rate_crit=2.0,
    )
    cfg = AlertConfig(dedup_window_s=dedup_window_s, max_history=50)
    return AlertEngine(thresholds, cfg)


def _healthy_pair(dt=1.0):
    t0 = time.time()
    s1 = TileSnapshot("quic", 0, ts=t0, last_beat_ts=t0 - 0.1)
    s2 = TileSnapshot("quic", 0, ts=t0 + dt, last_beat_ts=t0 + dt - 0.1)
    return compute_health(s2, s1)


def _stale_pair(age=10.0, dt=1.0):
    t0 = time.time()
    s1 = TileSnapshot("verify", 0, ts=t0,       last_beat_ts=t0 - age)
    s2 = TileSnapshot("verify", 0, ts=t0 + dt,  last_beat_ts=t0 - age)
    return compute_health(s2, s1, heartbeat_stale_crit_s=8.0)


def _lagging_pair(lag_count=5, dt=1.0):
    t0 = time.time()
    s1 = TileSnapshot("bank", 0, ts=t0,       heartbeat_lagged_count=0,
                      last_beat_ts=t0)
    s2 = TileSnapshot("bank", 0, ts=t0 + dt,  heartbeat_lagged_count=lag_count,
                      last_beat_ts=t0 + dt)
    return compute_health(s2, s1, heartbeat_lag_rate_crit=2.0)


class TestAlertEngine:
    def test_no_alert_healthy(self):
        engine = _make_engine()
        h      = _healthy_pair()
        alerts = engine.evaluate(h)
        assert alerts == []

    def test_critical_stale(self):
        engine = _make_engine()
        h      = _stale_pair(age=10.0)
        alerts = engine.evaluate(h)
        crits  = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        assert crits, "Expected a CRITICAL alert for stale heartbeat"
        assert "verify:0" in crits[0].tile_id

    def test_critical_lag(self):
        engine = _make_engine()
        h      = _lagging_pair(lag_count=5)
        alerts = engine.evaluate(h)
        crits  = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        assert crits, "Expected a CRITICAL alert for high lag rate"

    def test_warning_backpressure(self):
        engine = _make_engine()
        t0 = time.time()
        s1 = TileSnapshot("pack", 0, ts=t0,       last_beat_ts=t0, in_backpressure=False)
        s2 = TileSnapshot("pack", 0, ts=t0 + 1.0, last_beat_ts=t0 + 1.0, in_backpressure=True)
        h  = compute_health(s2, s1)
        alerts = engine.evaluate(h)
        warns = [a for a in alerts if a.severity == AlertSeverity.WARNING]
        assert warns

    def test_dedup_window(self):
        """Same condition should not fire twice within the dedup window."""
        engine = _make_engine(dedup_window_s=60.0)
        h      = _stale_pair(age=10.0)
        first  = engine.evaluate(h)
        second = engine.evaluate(h)
        assert len(first)  >= 1
        assert len(second) == 0   # deduplicated

    def test_dedup_expired(self):
        """After the window lapses the same condition fires again."""
        engine = _make_engine(dedup_window_s=0.0)
        h      = _stale_pair(age=10.0)
        first  = engine.evaluate(h)
        second = engine.evaluate(h)
        # Both should fire because dedup_window_s=0
        assert len(first)  >= 1
        assert len(second) >= 1

    def test_handler_called(self):
        received = []
        engine   = _make_engine()
        engine.add_handler(received.append)
        h = _stale_pair(age=10.0)
        engine.evaluate(h)
        assert received

    def test_acknowledge_all(self):
        engine = _make_engine()
        engine.evaluate(_stale_pair(age=10.0))
        assert engine.active_alerts
        engine.acknowledge_all()
        assert engine.active_alerts == []

    def test_summary(self):
        engine = _make_engine()
        engine.evaluate(_stale_pair(age=10.0))     # CRITICAL
        engine.evaluate(_lagging_pair(lag_count=1)) # WARNING (lag < crit)
        summary = engine.get_summary()
        assert summary["critical"] >= 1

    def test_tile_override(self):
        """repair tile should use its own looser stale threshold."""
        thresholds = AlertThresholds(
            heartbeat_stale_warn_s=3.0,
            heartbeat_stale_crit_s=8.0,
            tile_overrides={"repair": {"heartbeat_stale_crit_s": 30.0}},
        )
        cfg    = AlertConfig(dedup_window_s=0.0)
        engine = AlertEngine(thresholds, cfg)

        t0 = time.time()
        s1 = TileSnapshot("repair", 0, ts=t0,       last_beat_ts=t0 - 10.0)
        s2 = TileSnapshot("repair", 0, ts=t0 + 1.0, last_beat_ts=t0 - 10.0)
        h  = compute_health(s2, s1, heartbeat_stale_crit_s=30.0)
        # health itself will be WARNING not CRITICAL because of the override
        alerts = engine.evaluate(h)
        crits  = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        assert not crits, "Repair tile should not CRIT at 10s with 30s override"
