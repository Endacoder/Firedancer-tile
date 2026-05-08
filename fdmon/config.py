"""
Configuration dataclasses.  All fields have sensible defaults so that the
tool works out of the box with no config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

@dataclass
class AlertThresholds:
    # Heartbeat stale (seconds without a heartbeat change)
    heartbeat_stale_warn_s: float = 3.0
    heartbeat_stale_crit_s: float = 8.0

    # Heartbeat lag rate (lagged beats per second)
    heartbeat_lag_rate_warn: float = 0.5
    heartbeat_lag_rate_crit: float = 2.0

    # Link queue fill percentage
    link_fill_warn_pct: float = 75.0
    link_fill_crit_pct: float = 90.0

    # Per-tile overrides:  tile_name -> {threshold_key: value}
    tile_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def for_tile(self, tile_name: str) -> "AlertThresholds":
        """Return a copy with tile-specific overrides applied."""
        overrides = self.tile_overrides.get(tile_name, {})
        if not overrides:
            return self
        import copy
        merged = copy.copy(self)
        for k, v in overrides.items():
            if hasattr(merged, k):
                setattr(merged, k, v)
        return merged


# ---------------------------------------------------------------------------
# Backend configuration
# ---------------------------------------------------------------------------

@dataclass
class BackendConfig:
    # Which backend to use
    type: str = "simulator"   # prometheus | shm | fdctl | simulator

    # Prometheus HTTP backend
    metrics_url:       str   = "http://127.0.0.1:7999/metrics"
    scrape_interval_s: float = 1.0
    request_timeout_s: float = 5.0

    # fdctl backend
    fdctl_bin:    str = "/usr/local/bin/fdctl"
    fdctl_config: str = "/etc/firedancer/config.toml"

    # Shared-memory backend (Linux)
    shm_path: str = "/dev/shm/fd1"

    # Simulator backend
    sim_tile_count:   int   = 18
    sim_anomaly_rate: float = 0.03   # anomaly probability per second per tile


# ---------------------------------------------------------------------------
# Alert delivery configuration
# ---------------------------------------------------------------------------

@dataclass
class AlertConfig:
    log_file:       Optional[str] = None   # append alerts here
    webhook_url:    Optional[str] = None   # Discord / Slack incoming webhook
    sound:          bool          = True   # ring terminal bell on CRITICAL
    dedup_window_s: float         = 60.0   # suppress duplicate alerts within window
    max_history:    int           = 200    # max alerts kept in memory


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    backend:              BackendConfig  = field(default_factory=BackendConfig)
    thresholds:           AlertThresholds = field(default_factory=AlertThresholds)
    alerts:               AlertConfig    = field(default_factory=AlertConfig)
    refresh_interval_s:   float          = 1.0
    max_alert_display:    int            = 10

    # ── Constructors ─────────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_file(cls, path: str) -> "Config":
        import yaml
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        cfg = cls()

        if "backend" in data:
            b = data["backend"]
            cfg.backend = BackendConfig(
                **{k: v for k, v in b.items()
                   if k in BackendConfig.__dataclass_fields__}
            )

        if "thresholds" in data:
            t = data["thresholds"]
            cfg.thresholds = AlertThresholds(
                **{k: v for k, v in t.items()
                   if k in AlertThresholds.__dataclass_fields__}
            )

        if "alerts" in data:
            a = data["alerts"]
            cfg.alerts = AlertConfig(
                **{k: v for k, v in a.items()
                   if k in AlertConfig.__dataclass_fields__}
            )

        for key in ("refresh_interval_s", "max_alert_display"):
            if key in data:
                setattr(cfg, key, data[key])

        return cfg
