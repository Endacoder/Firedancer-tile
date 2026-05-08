"""
Simulator backend — generates realistic synthetic tile metrics.

Useful for:
  • Demoing the dashboard without a live validator
  • Running tests in CI
  • Developing alert rules offline

Tile topology mirrors a real Firedancer 0.2.x deployment.
Anomalies (stale heartbeat, lag, backpressure) are injected randomly
at a configurable rate so you can watch the alerting system in action.
"""

from __future__ import annotations

import math
import random
import time
from typing import List, Optional

from fdmon.backends.base import BaseBackend
from fdmon.config import BackendConfig
from fdmon.models import TileSnapshot


# ---------------------------------------------------------------------------
# Tile topology
# ---------------------------------------------------------------------------

# Each entry: (tile_name, num_instances, base_msgs_per_sec)
_TOPOLOGY = [
    ("net",    2,  60_000),
    ("quic",   2,  55_000),
    ("verify", 4,  50_000),
    ("dedup",  1,  45_000),
    ("pack",   1,  40_000),
    ("bank",   2,  35_000),
    ("poh",    1,  38_000),
    ("shred",  2,  36_000),
    ("store",  1,  34_000),
    ("gossip", 1,   1_000),
    ("repair", 1,     500),
    ("sign",   1,     200),
]


# ---------------------------------------------------------------------------
# Per-tile simulated state
# ---------------------------------------------------------------------------

class _SimTile:
    """Holds mutable sim state for one tile instance."""

    def __init__(
        self,
        name: str,
        kind_id: int,
        cpu_idx: int,
        pid: int,
        base_tps: int,
    ) -> None:
        self.name     = name
        self.kind_id  = kind_id
        self.cpu_idx  = cpu_idx
        self.pid      = pid
        self.base_tps = base_tps

        # Cumulative counters
        self.heartbeat_count        = 0
        self.heartbeat_lagged_count = 0
        self.backpressure_count     = 0

        # Transient state flags
        self.in_backpressure = False
        self._stuck          = False   # heartbeat frozen
        self._lagging        = False   # heartbeat running slow

        # Anomaly expiry (unix timestamp)
        self._anomaly_until: float = 0.0
        self._anomaly_type: Optional[str] = None

        self.last_beat_ts = time.time()

    # ── Simulation tick ──────────────────────────────────────────────────────

    def tick(self, dt: float, anomaly_rate: float) -> None:
        now = time.time()

        # Expire anomaly
        if self._anomaly_type and now > self._anomaly_until:
            self._anomaly_type   = None
            self._stuck          = False
            self._lagging        = False
            self.in_backpressure = False

        # Possibly trigger new anomaly
        if not self._anomaly_type:
            p_trigger = 1.0 - math.exp(-anomaly_rate * dt)
            if random.random() < p_trigger:
                self._start_anomaly(now)

        # Advance heartbeat
        if not self._stuck:
            beats = int(dt * 1_000)
            if self._lagging:
                lagged = int(beats * random.uniform(0.05, 0.20))
                self.heartbeat_lagged_count += lagged
            self.heartbeat_count += beats
            self.last_beat_ts = now

        # Random transient backpressure (independent of anomalies)
        if not self.in_backpressure and random.random() < 0.001 * dt:
            self.in_backpressure = True
            self.backpressure_count += 1
        elif self.in_backpressure and random.random() < 0.4 * dt:
            self.in_backpressure = False

    def _start_anomaly(self, now: float) -> None:
        choice = random.choices(
            ["lag", "backpressure", "stuck"],
            weights=[0.50, 0.35, 0.15],
        )[0]
        duration = random.uniform(4.0, 25.0)
        self._anomaly_type   = choice
        self._anomaly_until  = now + duration

        if choice == "stuck":
            self._stuck = True
        elif choice == "lag":
            self._lagging = True
        elif choice == "backpressure":
            self.in_backpressure = True
            self.backpressure_count += 1


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------

class SimulatorBackend(BaseBackend):
    """Generates synthetic Firedancer tile metrics."""

    def __init__(self, cfg: BackendConfig) -> None:
        self._cfg        = cfg
        self._tiles: List[_SimTile] = []
        self._connected  = False
        self._last_tick  = 0.0

    # ── BaseBackend interface ────────────────────────────────────────────────

    def connect(self) -> None:
        self._tiles      = self._build_tiles()
        self._connected  = True
        self._last_tick  = time.time()

    def disconnect(self) -> None:
        self._connected = False
        self._tiles     = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_tiles(self) -> List[TileSnapshot]:
        now = time.time()
        dt  = now - self._last_tick
        self._last_tick = now

        for tile in self._tiles:
            tile.tick(dt, self._cfg.sim_anomaly_rate)

        return [self._snapshot(t) for t in self._tiles]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_tiles(self) -> List[_SimTile]:
        tiles   : List[_SimTile] = []
        cpu_idx  = 0
        pid_base = 10_000

        for name, instances, base_tps in _TOPOLOGY:
            for kind_id in range(instances):
                tiles.append(_SimTile(
                    name=name,
                    kind_id=kind_id,
                    cpu_idx=cpu_idx,
                    pid=pid_base + cpu_idx,
                    base_tps=base_tps,
                ))
                cpu_idx += 1

        return tiles

    def _snapshot(self, t: _SimTile) -> TileSnapshot:
        jitter = random.uniform(0.90, 1.10)
        tps_in  = int(t.base_tps * jitter)
        tps_out = int(tps_in  * random.uniform(0.95, 1.00))

        return TileSnapshot(
            name=t.name,
            kind_id=t.kind_id,
            pid=t.pid,
            cpu_idx=t.cpu_idx,
            heartbeat_count=t.heartbeat_count,
            heartbeat_lagged_count=t.heartbeat_lagged_count,
            in_backpressure=t.in_backpressure,
            backpressure_count=t.backpressure_count,
            last_beat_ts=t.last_beat_ts,
            ts=time.time(),
            extra={"tps_in": tps_in, "tps_out": tps_out},
        )
