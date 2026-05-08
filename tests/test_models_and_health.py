"""Tests for fdmon.models and fdmon.health."""

import time
import pytest

from fdmon.models import (
    Alert,
    AlertSeverity,
    TileHealth,
    TileSnapshot,
    TileStatus,
)
from fdmon.health import compute_health


# ---------------------------------------------------------------------------
# TileSnapshot helpers
# ---------------------------------------------------------------------------

def _snap(
    name="quic",
    kind_id=0,
    ts=None,
    last_beat_ts=None,
    heartbeat_lagged_count=0,
    in_backpressure=False,
    backpressure_count=0,
    extra=None,
):
    now = time.time()
    return TileSnapshot(
        name=name,
        kind_id=kind_id,
        ts=ts if ts is not None else now,
        last_beat_ts=last_beat_ts if last_beat_ts is not None else now,
        heartbeat_lagged_count=heartbeat_lagged_count,
        in_backpressure=in_backpressure,
        backpressure_count=backpressure_count,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# TileSnapshot
# ---------------------------------------------------------------------------

class TestTileSnapshot:
    def test_defaults(self):
        s = TileSnapshot(name="bank", kind_id=1)
        assert s.name    == "bank"
        assert s.kind_id == 1
        assert s.pid     is None
        assert s.in_backpressure is False
        assert s.extra == {}

    def test_ts_auto(self):
        before = time.time()
        s = TileSnapshot(name="poh", kind_id=0)
        after = time.time()
        assert before <= s.ts <= after


# ---------------------------------------------------------------------------
# TileHealth
# ---------------------------------------------------------------------------

class TestTileHealth:
    def test_tile_id(self):
        snap = _snap(name="verify", kind_id=2)
        h    = TileHealth(snapshot=snap)
        assert h.tile_id     == "verify:2"
        assert h.display_name == "verify[2]"

    def test_heartbeat_age_no_beat(self):
        snap = TileSnapshot(name="net", kind_id=0, last_beat_ts=0.0)
        h    = TileHealth(snapshot=snap)
        assert h.heartbeat_age_sec == float("inf")

    def test_heartbeat_age_recent(self):
        snap = _snap(last_beat_ts=time.time() - 1.5)
        h    = TileHealth(snapshot=snap)
        assert 1.4 < h.heartbeat_age_sec < 2.0


# ---------------------------------------------------------------------------
# compute_health
# ---------------------------------------------------------------------------

class TestComputeHealth:
    def test_unknown_when_no_prev(self):
        snap = _snap()
        h    = compute_health(snap, prev=None)
        assert h.status == TileStatus.UNKNOWN

    def test_healthy(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       last_beat_ts=t0 - 0.5, heartbeat_lagged_count=0)
        s2 = _snap(ts=t0 + 1.0, last_beat_ts=t0 + 1.0, heartbeat_lagged_count=0)
        h  = compute_health(s2, prev=s1)
        assert h.status == TileStatus.HEALTHY
        assert h.heartbeat_lag_rate == pytest.approx(0.0)

    def test_critical_stale_heartbeat(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       last_beat_ts=t0 - 10.0)
        s2 = _snap(ts=t0 + 1.0, last_beat_ts=t0 - 10.0)  # no beat update
        h  = compute_health(s2, prev=s1,
                            heartbeat_stale_crit_s=8.0)
        assert h.status == TileStatus.CRITICAL
        assert "stale" in h.status_reason

    def test_warning_stale_heartbeat(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       last_beat_ts=t0 - 4.0)
        s2 = _snap(ts=t0 + 1.0, last_beat_ts=t0 - 5.0)
        h  = compute_health(s2, prev=s1,
                            heartbeat_stale_warn_s=3.0,
                            heartbeat_stale_crit_s=8.0)
        assert h.status == TileStatus.WARNING

    def test_critical_lag_rate(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       heartbeat_lagged_count=0)
        s2 = _snap(ts=t0 + 1.0, heartbeat_lagged_count=5)
        h  = compute_health(s2, prev=s1,
                            heartbeat_lag_rate_crit=2.0)
        assert h.status == TileStatus.CRITICAL
        assert h.heartbeat_lag_rate == pytest.approx(5.0)

    def test_warning_lag_rate(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       heartbeat_lagged_count=0)
        s2 = _snap(ts=t0 + 1.0, heartbeat_lagged_count=1)
        h  = compute_health(s2, prev=s1,
                            heartbeat_lag_rate_warn=0.5,
                            heartbeat_lag_rate_crit=2.0)
        assert h.status == TileStatus.WARNING

    def test_warning_backpressure(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       in_backpressure=False)
        s2 = _snap(ts=t0 + 1.0, in_backpressure=True)
        h  = compute_health(s2, prev=s1)
        assert h.status == TileStatus.WARNING
        assert "backpressure" in h.status_reason

    def test_stale_when_no_beat_ever(self):
        t0 = time.time()
        s1 = TileSnapshot(name="sign", kind_id=0, ts=t0,       last_beat_ts=0.0)
        s2 = TileSnapshot(name="sign", kind_id=0, ts=t0 + 1.0, last_beat_ts=0.0)
        h  = compute_health(s2, prev=s1)
        assert h.status == TileStatus.STALE

    def test_backpressure_rate(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       backpressure_count=0)
        s2 = _snap(ts=t0 + 1.0, backpressure_count=3)
        h  = compute_health(s2, prev=s1)
        assert h.backpressure_rate == pytest.approx(3.0)

    def test_tps_from_extra(self):
        t0 = time.time()
        s1 = _snap(ts=t0,       extra={"tps_in": 50_000, "tps_out": 49_000})
        s2 = _snap(ts=t0 + 1.0, extra={"tps_in": 52_000, "tps_out": 51_000})
        h  = compute_health(s2, prev=s1)
        assert h.msgs_in_rate  == pytest.approx(52_000)
        assert h.msgs_out_rate == pytest.approx(51_000)

    def test_negative_lag_clamped(self):
        """Counter should never go backwards but guard against stale reads."""
        t0 = time.time()
        s1 = _snap(ts=t0,       heartbeat_lagged_count=10)
        s2 = _snap(ts=t0 + 1.0, heartbeat_lagged_count=8)   # lower (stale read)
        h  = compute_health(s2, prev=s1)
        assert h.heartbeat_lag_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Alert model
# ---------------------------------------------------------------------------

class TestAlert:
    def test_str(self):
        a = Alert(severity=AlertSeverity.CRITICAL, tile_id="quic:0",
                  message="tile crashed", ts=time.time())
        assert "CRITICAL" in str(a)
        assert "quic:0"   in str(a)

    def test_age(self):
        past = time.time() - 5.0
        a    = Alert(severity=AlertSeverity.WARNING, tile_id="verify:1",
                     message="lagging", ts=past)
        assert 4.9 < a.age_sec < 6.0
