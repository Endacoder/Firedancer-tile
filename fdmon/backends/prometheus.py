"""
Prometheus HTTP backend.

Reads from Firedancer's built-in metrics endpoint (default port 7999).
Firedancer exports Prometheus-format metrics via the *metric* tile:

    http://127.0.0.1:7999/metrics

Expected metric families (as of Firedancer 0.2.x):
  fd_tile_heartbeat_lagged_count{tile="quic",   kind_id="0"} 0
  fd_tile_in_backpressure       {tile="verify", kind_id="1"} 0
  fd_tile_backpressure_count    {tile="dedup",  kind_id="0"} 12
  fd_tile_pid                   {tile="bank",   kind_id="0"} 18234
  fd_tile_cpu                   {tile="pack",   kind_id="0"} 7
  fd_<tile>_<metric>            {tile="…",       kind_id="…"} <value>

Any metric whose name contains the tile name in a label is parsed
generically and stored in TileSnapshot.extra.
"""

from __future__ import annotations

import re
import time
import logging
from typing import Dict, List, Optional, Tuple

import requests
from requests.exceptions import RequestException

from fdmon.backends.base import BaseBackend, BackendError
from fdmon.config import BackendConfig
from fdmon.models import TileSnapshot

logger = logging.getLogger(__name__)

# Regex to parse a Prometheus text line:  name{labels} value
_LINE_RE  = re.compile(r'^(\w+)(?:\{([^}]*)\})?\s+([+-]?[\d.eE+inf-]+)')
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def _parse_labels(label_str: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in _LABEL_RE.finditer(label_str)}


def _parse_text(text: str) -> List[Tuple[str, Dict[str, str], float]]:
    """Parse Prometheus text format into (name, labels, value) triples."""
    results: List[Tuple[str, Dict[str, str], float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        name   = m.group(1)
        labels = _parse_labels(m.group(2) or "")
        raw    = m.group(3)
        try:
            value = float(raw)
        except ValueError:
            continue
        results.append((name, labels, value))
    return results


class PrometheusBackend(BaseBackend):
    """Scrapes Firedancer's Prometheus metrics endpoint."""

    def __init__(self, cfg: BackendConfig) -> None:
        self._cfg       = cfg
        self._session:   Optional[requests.Session] = None
        self._connected = False

    # ── BaseBackend ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "fdmon/1.0"})
        # Verify reachability
        try:
            resp = self._session.get(
                self._cfg.metrics_url,
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
            self._connected = True
            logger.info("Connected to metrics endpoint: %s", self._cfg.metrics_url)
        except RequestException as exc:
            if self._session:
                self._session.close()
                self._session = None
            raise BackendError(
                f"Cannot reach metrics endpoint {self._cfg.metrics_url}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_tiles(self) -> List[TileSnapshot]:
        if not self._session:
            raise BackendError("Not connected")
        try:
            resp = self._session.get(
                self._cfg.metrics_url,
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
        except RequestException as exc:
            self._connected = False
            raise BackendError(f"Metrics fetch failed: {exc}") from exc

        return self._parse(resp.text)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, text: str) -> List[TileSnapshot]:
        metrics = _parse_text(text)
        tile_map: Dict[Tuple[str, int], TileSnapshot] = {}
        now = time.time()

        for name, labels, value in metrics:
            # Identify tile and instance
            tile     = labels.get("tile") or labels.get("tile_name")
            kind_str = labels.get("kind_id", "0")
            if not tile:
                continue
            try:
                kind_id = int(kind_str)
            except ValueError:
                kind_id = 0

            key = (tile, kind_id)
            if key not in tile_map:
                tile_map[key] = TileSnapshot(name=tile, kind_id=kind_id, ts=now)
            snap = tile_map[key]

            # Map well-known metric names to snapshot fields
            lname = name.lower()
            if "heartbeat_lagged" in lname:
                snap.heartbeat_lagged_count = int(value)
            elif "heartbeat_count" in lname and "lagged" not in lname:
                snap.heartbeat_count = int(value)
            elif "in_backpressure" in lname:
                snap.in_backpressure = bool(int(value))
            elif "backpressure_count" in lname:
                snap.backpressure_count = int(value)
            elif lname.endswith("_pid"):
                snap.pid = int(value)
            elif lname.endswith("_cpu"):
                snap.cpu_idx = int(value)
            else:
                # Store any other fd_ counter in extra for display
                prefix = f"fd_{tile}_"
                extra_key = name[len(prefix):] if name.startswith(prefix) else name
                snap.extra[extra_key] = int(value)

            # Synthetic heartbeat timestamp: if the metric server is reachable
            # the tile is at minimum alive right now.
            if snap.last_beat_ts == 0.0:
                snap.last_beat_ts = now

        return list(tile_map.values())
