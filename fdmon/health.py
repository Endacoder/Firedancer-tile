"""
Health computation: compare two consecutive TileSnapshots to produce a
TileHealth with derived rates and an overall status.
"""

from __future__ import annotations

import time
from typing import Optional

from fdmon.models import TileHealth, TileSnapshot, TileStatus


def compute_health(
    snapshot: TileSnapshot,
    prev: Optional[TileSnapshot],
    heartbeat_stale_warn_s: float = 3.0,
    heartbeat_stale_crit_s: float = 8.0,
    heartbeat_lag_rate_warn: float = 0.5,
    heartbeat_lag_rate_crit: float = 2.0,
) -> TileHealth:
    """
    Derive a TileHealth from the current snapshot and its predecessor.

    If *prev* is None (first observation) the status is UNKNOWN.
    All thresholds can be overridden per call so the AlertEngine can pass
    tile-specific values.
    """
    health = TileHealth(snapshot=snapshot, prev_snapshot=prev)

    if prev is None:
        # First reading — not enough data yet.
        health.status = TileStatus.UNKNOWN
        health.status_reason = "awaiting first delta"
        return health

    # ── Time delta ──────────────────────────────────────────────────────────
    dt = snapshot.ts - prev.ts
    if dt <= 0:
        dt = 1e-3   # safety: avoid division by zero

    # ── Heartbeat lag rate ───────────────────────────────────────────────────
    lag_delta = max(0, snapshot.heartbeat_lagged_count - prev.heartbeat_lagged_count)
    health.heartbeat_lag_rate = lag_delta / dt

    # ── Backpressure rate ────────────────────────────────────────────────────
    bp_delta = max(0, snapshot.backpressure_count - prev.backpressure_count)
    health.backpressure_rate = bp_delta / dt

    # ── Message throughput (from tile-specific extra counters if present) ───
    if "tps_in" in snapshot.extra:
        health.msgs_in_rate = float(snapshot.extra["tps_in"])
    if "tps_out" in snapshot.extra:
        health.msgs_out_rate = float(snapshot.extra["tps_out"])

    # ── Heartbeat age ────────────────────────────────────────────────────────
    age = health.heartbeat_age_sec   # seconds since last beat

    # ── Overall status decision (highest severity wins) ──────────────────────
    if snapshot.last_beat_ts == 0.0:
        health.status = TileStatus.STALE
        health.status_reason = "no heartbeat received"

    elif age > heartbeat_stale_crit_s:
        health.status = TileStatus.CRITICAL
        health.status_reason = f"stale {age:.0f}s (crit >{heartbeat_stale_crit_s:.0f}s)"

    elif health.heartbeat_lag_rate > heartbeat_lag_rate_crit:
        health.status = TileStatus.CRITICAL
        health.status_reason = (
            f"lag {health.heartbeat_lag_rate:.2f}/s "
            f"(crit >{heartbeat_lag_rate_crit:.1f}/s)"
        )

    elif age > heartbeat_stale_warn_s:
        health.status = TileStatus.WARNING
        health.status_reason = f"stale {age:.1f}s (warn >{heartbeat_stale_warn_s:.0f}s)"

    elif health.heartbeat_lag_rate > heartbeat_lag_rate_warn:
        health.status = TileStatus.WARNING
        health.status_reason = (
            f"lag {health.heartbeat_lag_rate:.2f}/s "
            f"(warn >{heartbeat_lag_rate_warn:.1f}/s)"
        )

    elif snapshot.in_backpressure:
        health.status = TileStatus.WARNING
        health.status_reason = "backpressured"

    else:
        health.status = TileStatus.HEALTHY
        health.status_reason = ""

    return health
