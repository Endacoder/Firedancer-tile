"""
Alert engine: evaluates TileHealth objects, deduplicates alerts, dispatches
them to registered handlers (log file, webhook, terminal bell).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from fdmon.models import Alert, AlertSeverity, TileHealth
from fdmon.config import AlertConfig, AlertThresholds

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Stateful alert engine.

    Usage::

        engine = AlertEngine(thresholds, alert_cfg)
        engine.add_handler(my_handler)

        for health in tile_healths:
            new_alerts = engine.evaluate(health)
    """

    def __init__(self, thresholds: AlertThresholds, cfg: AlertConfig) -> None:
        self._thresholds = thresholds
        self._cfg = cfg
        self._history: List[Alert] = []
        # (tile_id, condition) → last emit timestamp
        self._last_alerted: Dict[Tuple[str, str], float] = defaultdict(float)
        self._handlers: List[Callable[[Alert], None]] = []

    # ── Handler registration ─────────────────────────────────────────────────

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register a callable that receives every newly emitted Alert."""
        self._handlers.append(handler)

    # ── Evaluation ───────────────────────────────────────────────────────────

    def evaluate(self, health: TileHealth) -> List[Alert]:
        """
        Check all conditions for *health*, emit any new (non-deduplicated)
        alerts and return them.
        """
        snap   = health.snapshot
        tid    = health.tile_id
        t      = self._thresholds.for_tile(snap.name)
        age    = health.heartbeat_age_sec
        new_alerts: List[Alert] = []

        # 1 ── Heartbeat stale ───────────────────────────────────────────────
        if age == float("inf") or age > t.heartbeat_stale_crit_s:
            msg = (
                f"No heartbeat for {age:.1f}s (crit >{t.heartbeat_stale_crit_s:.0f}s)"
                " — tile may be crashed or not started"
                if age != float("inf")
                else "Heartbeat never received — tile may not be running"
            )
            a = self._maybe_emit(tid, "heartbeat_stale", AlertSeverity.CRITICAL, msg)
            if a:
                new_alerts.append(a)

        elif age > t.heartbeat_stale_warn_s:
            msg = (
                f"Heartbeat stale for {age:.1f}s "
                f"(warn >{t.heartbeat_stale_warn_s:.0f}s)"
            )
            a = self._maybe_emit(tid, "heartbeat_stale", AlertSeverity.WARNING, msg)
            if a:
                new_alerts.append(a)

        # 2 ── Heartbeat lag rate ────────────────────────────────────────────
        lag = health.heartbeat_lag_rate
        if lag > t.heartbeat_lag_rate_crit:
            a = self._maybe_emit(
                tid, "heartbeat_lag", AlertSeverity.CRITICAL,
                f"Heartbeat lagging {lag:.2f}/s (crit >{t.heartbeat_lag_rate_crit:.1f}/s)"
                " — tile CPU may be overloaded",
            )
            if a:
                new_alerts.append(a)
        elif lag > t.heartbeat_lag_rate_warn:
            a = self._maybe_emit(
                tid, "heartbeat_lag", AlertSeverity.WARNING,
                f"Heartbeat lagging {lag:.2f}/s (warn >{t.heartbeat_lag_rate_warn:.1f}/s)",
            )
            if a:
                new_alerts.append(a)

        # 3 ── Backpressure event ────────────────────────────────────────────
        if snap.in_backpressure:
            a = self._maybe_emit(
                tid, "backpressure", AlertSeverity.WARNING,
                "Tile is currently backpressured — downstream pipeline may be congested",
            )
            if a:
                new_alerts.append(a)

        # 4 ── Backpressure rate ─────────────────────────────────────────────
        if health.backpressure_rate > 5.0:
            a = self._maybe_emit(
                tid, "backpressure_rate", AlertSeverity.WARNING,
                f"High backpressure event rate: {health.backpressure_rate:.1f}/s",
            )
            if a:
                new_alerts.append(a)

        # 5 ── Link queue saturation ─────────────────────────────────────────
        for link in snap.links_in + snap.links_out:
            if link.fill_pct > t.link_fill_crit_pct:
                a = self._maybe_emit(
                    tid, f"link_fill_{link.name}", AlertSeverity.CRITICAL,
                    f"Link '{link.name}' queue {link.fill_pct:.0f}% full "
                    f"(crit >{t.link_fill_crit_pct:.0f}%)",
                )
                if a:
                    new_alerts.append(a)
            elif link.fill_pct > t.link_fill_warn_pct:
                a = self._maybe_emit(
                    tid, f"link_fill_{link.name}", AlertSeverity.WARNING,
                    f"Link '{link.name}' queue {link.fill_pct:.0f}% full "
                    f"(warn >{t.link_fill_warn_pct:.0f}%)",
                )
                if a:
                    new_alerts.append(a)

        # Persist & dispatch
        for alert in new_alerts:
            self._history.append(alert)
            if len(self._history) > self._cfg.max_history:
                self._history = self._history[-self._cfg.max_history :]
            for handler in self._handlers:
                try:
                    handler(alert)
                except Exception:
                    logger.exception("Alert handler raised an exception")

        return new_alerts

    # ── Accessors ────────────────────────────────────────────────────────────

    @property
    def active_alerts(self) -> List[Alert]:
        """Unacknowledged alerts sorted by severity (CRITICAL first) then recency."""
        active = [a for a in self._history if not a.acknowledged]
        return sorted(
            active,
            key=lambda a: (
                {"critical": 0, "warning": 1, "info": 2}[a.severity.value],
                -a.ts,
            ),
        )

    def get_summary(self) -> Dict[str, int]:
        active = self.active_alerts
        return {
            "critical": sum(1 for a in active if a.severity == AlertSeverity.CRITICAL),
            "warning":  sum(1 for a in active if a.severity == AlertSeverity.WARNING),
            "info":     sum(1 for a in active if a.severity == AlertSeverity.INFO),
        }

    def acknowledge_all(self) -> None:
        for a in self._history:
            a.acknowledged = True

    # ── Internal ─────────────────────────────────────────────────────────────

    def _maybe_emit(
        self,
        tile_id: str,
        condition: str,
        severity: AlertSeverity,
        message: str,
    ) -> Optional[Alert]:
        key = (tile_id, condition)
        now = time.time()
        if now - self._last_alerted[key] < self._cfg.dedup_window_s:
            return None
        self._last_alerted[key] = now
        return Alert(severity=severity, tile_id=tile_id, message=message, ts=now)
