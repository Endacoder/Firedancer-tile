"""
fdctl backend.

Runs ``fdctl monitor --format json`` as a subprocess and parses its
JSON output.  Each JSON line (or top-level object, depending on version)
corresponds to one polling cycle.

Supported fdctl invocation (Firedancer 0.2.x):

    fdctl --config <path> monitor --format json --interval 1000

Output format (one JSON object per line):

    {
      "tiles": [
        {
          "name":               "quic",
          "kind_id":            0,
          "pid":                18234,
          "cpu":                4,
          "heartbeat_count":    123456789,
          "heartbeat_lagged":   3,
          "in_backpressure":    false,
          "backpressure_count": 7,
          "msgs_in":            9000000,
          "msgs_out":           8950000
        },
        ...
      ],
      "ts": 1746700000.123
    }

If fdctl does not support ``--format json`` the process will exit early
and BackendError is raised with a helpful message.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from typing import List, Optional

from fdmon.backends.base import BaseBackend, BackendError
from fdmon.config import BackendConfig
from fdmon.models import TileSnapshot

logger = logging.getLogger(__name__)


class FdctlBackend(BaseBackend):
    """
    Spawns ``fdctl monitor --format json`` and streams its output.

    Parameters
    ----------
    cfg.fdctl_bin    : path to the fdctl binary
    cfg.fdctl_config : path to the Firedancer config.toml
    """

    def __init__(self, cfg: BackendConfig) -> None:
        self._cfg        = cfg
        self._proc:       Optional[subprocess.Popen] = None   # type: ignore[type-arg]
        self._connected   = False
        self._pending_buf = ""

    # ── BaseBackend ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        fdctl = self._cfg.fdctl_bin
        config = self._cfg.fdctl_config

        if not os.path.isfile(fdctl):
            raise BackendError(
                f"fdctl binary not found: {fdctl}\n"
                "Set fdctl_bin in your config or pass --backend simulator."
            )

        cmd = [fdctl, "--config", config, "monitor", "--format", "json"]
        logger.info("Launching: %s", " ".join(cmd))

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise BackendError(f"Failed to start fdctl: {exc}") from exc

        # Give fdctl a moment to start, then check it's still alive
        time.sleep(0.5)
        if self._proc.poll() is not None:
            stderr = (self._proc.stderr.read() if self._proc.stderr else "")
            raise BackendError(
                f"fdctl exited immediately (code {self._proc.returncode}).\n"
                f"stderr: {stderr.strip()}\n"
                "Ensure fdctl supports '--format json' (Firedancer >= 0.2)."
            )

        self._connected = True

    def disconnect(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._connected  = False
        self._pending_buf = ""

    @property
    def is_connected(self) -> bool:
        return self._connected and self._proc is not None and self._proc.poll() is None

    def read_tiles(self) -> List[TileSnapshot]:
        if not self._proc or not self._proc.stdout:
            raise BackendError("fdctl process is not running")

        if self._proc.poll() is not None:
            self._connected = False
            raise BackendError(
                f"fdctl exited unexpectedly (code {self._proc.returncode})"
            )

        # Non-blocking read of any buffered lines
        line = self._proc.stdout.readline()
        if not line:
            return []

        self._pending_buf += line
        # Try to parse the accumulated buffer as JSON
        try:
            obj = json.loads(self._pending_buf.strip())
            self._pending_buf = ""
            return self._parse_frame(obj)
        except json.JSONDecodeError:
            # Incomplete JSON — keep buffering
            return []

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_frame(self, obj: dict) -> List[TileSnapshot]:
        frame_ts = float(obj.get("ts", time.time()))
        tiles_raw = obj.get("tiles", [])
        snapshots: List[TileSnapshot] = []

        for t in tiles_raw:
            snap = TileSnapshot(
                name=str(t.get("name", "unknown")),
                kind_id=int(t.get("kind_id", 0)),
                pid=t.get("pid"),
                cpu_idx=t.get("cpu"),
                heartbeat_count=int(t.get("heartbeat_count", 0)),
                heartbeat_lagged_count=int(t.get("heartbeat_lagged", 0)),
                in_backpressure=bool(t.get("in_backpressure", False)),
                backpressure_count=int(t.get("backpressure_count", 0)),
                last_beat_ts=frame_ts,   # best approximation
                ts=frame_ts,
                extra={
                    "msgs_in":  int(t.get("msgs_in",  0)),
                    "msgs_out": int(t.get("msgs_out", 0)),
                },
            )
            snapshots.append(snap)

        return snapshots
