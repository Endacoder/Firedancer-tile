"""
Data models for Firedancer tile metrics, health assessments, and alerts.

Firedancer tiles (as of 0.2.x):
  net, quic, verify, dedup, pack, bank, poh, shred, store,
  gossip, repair, replay, sign, metric, gui
Each tile type may run as multiple instances (kind_id 0, 1, …).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TileStatus(Enum):
    HEALTHY  = "healthy"
    WARNING  = "warning"
    CRITICAL = "critical"
    STALE    = "stale"    # no heartbeat data yet or SHM file absent
    UNKNOWN  = "unknown"  # first observation, no delta yet


class AlertSeverity(Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Raw snapshot — one reading from the backend
# ---------------------------------------------------------------------------

@dataclass
class LinkMetrics:
    """One directional link between two tiles."""
    name: str             = ""
    rx_count: int         = 0    # cumulative messages received
    rx_bytes: int         = 0    # cumulative bytes received
    fill_pct: float       = 0.0  # current queue fill 0–100
    # Rates computed by the health layer
    rx_count_rate: float  = 0.0  # msgs/s
    rx_bytes_rate:  float = 0.0  # bytes/s


@dataclass
class TileSnapshot:
    """Point-in-time metrics snapshot for a single tile instance."""
    # Identity
    name:    str
    kind_id: int

    pid:     Optional[int] = None   # OS process ID
    cpu_idx: Optional[int] = None   # pinned CPU core index

    # Heartbeat counters (monotonically increasing)
    heartbeat_count:        int   = 0
    heartbeat_lagged_count: int   = 0   # times heartbeat was late
    last_beat_ts:           float = 0.0  # unix timestamp of latest heartbeat

    # Backpressure
    in_backpressure:  bool = False
    backpressure_count: int = 0     # cumulative events

    # Per-link metrics
    links_in:  List[LinkMetrics] = field(default_factory=list)
    links_out: List[LinkMetrics] = field(default_factory=list)

    # Tile-specific extra counters (name → value)
    extra: Dict[str, int] = field(default_factory=dict)

    # Wall-clock time of this snapshot
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Computed health — derived from two consecutive snapshots
# ---------------------------------------------------------------------------

@dataclass
class TileHealth:
    """Health assessment for one tile instance, derived from a snapshot pair."""
    snapshot:      TileSnapshot
    prev_snapshot: Optional[TileSnapshot] = None

    # Rates (per second), computed relative to prev_snapshot
    heartbeat_lag_rate: float = 0.0   # lagged beats / s
    backpressure_rate:  float = 0.0   # new backpressure events / s
    msgs_in_rate:       float = 0.0   # messages / s into this tile
    msgs_out_rate:      float = 0.0   # messages / s out of this tile

    # Overall assessment
    status:        TileStatus = TileStatus.UNKNOWN
    status_reason: str        = ""

    # ── Convenience helpers ─────────────────────────────────────────────────

    @property
    def tile_id(self) -> str:
        """Human-readable unique identifier, e.g. 'quic:1'."""
        return f"{self.snapshot.name}:{self.snapshot.kind_id}"

    @property
    def display_name(self) -> str:
        """Name shown in the dashboard table, e.g. 'quic[1]'."""
        return f"{self.snapshot.name}[{self.snapshot.kind_id}]"

    @property
    def heartbeat_age_sec(self) -> float:
        """Seconds since last heartbeat update.  inf if never received."""
        ts = self.snapshot.last_beat_ts
        if ts == 0.0:
            return float("inf")
        return time.time() - ts


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    severity: AlertSeverity
    tile_id:  str
    message:  str
    ts: float         = field(default_factory=time.time)
    acknowledged: bool = False

    @property
    def age_sec(self) -> float:
        return time.time() - self.ts

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()}] {self.tile_id}: {self.message}"
