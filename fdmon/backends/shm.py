"""
Linux shared-memory backend.

Firedancer writes live tile metrics into a set of shared-memory files
(backed by hugetlbfs on production validators) inside the workspace
directory, typically ``/dev/shm/<workspace_name>/``.

The monitoring binary layout used by ``fdctl monitor`` is an internal
struct array.  This reader reproduces that layout based on
Firedancer 0.2.x source (``src/app/fdctl/run/tiles/fd_metric.c`` and
``src/app/fdctl/monitor/fd_topo_mon.c``).

Layout of the monitor region (little-endian, all uint64):
──────────────────────────────────────────────────
  Header  (48 bytes)
    magic          u64   = 0xFDA44E0C4E3E37B1
    version        u64   = 2
    tile_cnt       u64
    ts_nanos       u64   (nanoseconds since epoch — updated each tick)
    reserved[2]    u64[2]

  Tile entry  (144 bytes each, tile_cnt entries follow header)
    name           char[16]
    kind_id        u64
    pid            u64
    cpu_idx        u64
    hb_count       u64  (heartbeat counter — increments ~1 000/s)
    hb_lagged      u64  (cumulative lagged beats)
    in_backpressure u64 (1 = currently backpressured, 0 = free)
    bp_count       u64  (cumulative backpressure events)
    msgs_in        u64  (cumulative messages consumed from in-links)
    msgs_out       u64  (cumulative messages produced to out-links)
    bytes_in       u64
    bytes_out      u64
    ts_nanos_beat  u64  (nanosec timestamp of last heartbeat)
    reserved[5]    u64[5]
──────────────────────────────────────────────────

NOTE: The binary layout above is based on public Firedancer source.
      It may differ between releases — always verify against the running
      fdctl version by checking ``src/app/fdctl/run/tiles/fd_metric.c``.
      If the magic number does not match the backend raises BackendError.
"""

from __future__ import annotations

import mmap
import os
import struct
import time
import logging
from typing import List, Optional

from fdmon.backends.base import BaseBackend, BackendError
from fdmon.config import BackendConfig
from fdmon.models import TileSnapshot

logger = logging.getLogger(__name__)

# ── Binary layout constants ───────────────────────────────────────────────────

_MAGIC   = 0xFDA44E0C4E3E37B1
_VERSION = 2

#                magic  ver  tile_cnt ts_ns  res[2]
_HEADER_FMT  = "<QQQQQQ"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)   # 48 bytes

#              name(16) kind pid cpu hb_cnt hb_lag in_bp bp_cnt msg_in msg_out b_in b_out ts_beat res[5]
_TILE_FMT  = "<16sQQQQQQQQQQQQ" + "QQQQQ"
_TILE_SIZE = struct.calcsize(_TILE_FMT)        # 144 bytes

# Monitor file name inside the workspace directory
_MONITOR_FILE = "monitor"


class ShmBackend(BaseBackend):
    """
    Reads tile metrics directly from Firedancer's shared-memory region.

    Linux only.  Requires read permission on the workspace files
    (typically owned by the *firedancer* user).

    Parameters
    ----------
    cfg.shm_path : str
        Path to the Firedancer workspace directory, e.g. ``/dev/shm/fd1``.
    """

    def __init__(self, cfg: BackendConfig) -> None:
        self._cfg         = cfg
        self._map:         Optional[mmap.mmap] = None
        self._fd:          Optional[int]       = None
        self._connected    = False
        self._monitor_path = os.path.join(cfg.shm_path, _MONITOR_FILE)

    # ── BaseBackend ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        if os.name != "posix":
            raise BackendError(
                "Shared-memory backend is only supported on Linux/POSIX systems."
            )
        if not os.path.exists(self._monitor_path):
            raise BackendError(
                f"Monitor file not found: {self._monitor_path}\n"
                "Ensure Firedancer is running and shm_path points to the "
                "correct workspace directory (e.g. /dev/shm/fd1)."
            )
        try:
            self._fd  = os.open(self._monitor_path, os.O_RDONLY)
            file_size = os.fstat(self._fd).st_size
            if file_size < _HEADER_SIZE:
                raise BackendError(
                    f"Monitor file too small ({file_size} B) — "
                    "is Firedancer fully initialised?"
                )
            self._map = mmap.mmap(self._fd, file_size, access=mmap.ACCESS_READ)
        except OSError as exc:
            self._cleanup()
            raise BackendError(
                f"Cannot open monitor file {self._monitor_path}: {exc}"
            ) from exc

        # Validate magic
        header = self._read_header()
        if header[0] != _MAGIC:
            self._cleanup()
            raise BackendError(
                f"Unexpected magic 0x{header[0]:016X} in {self._monitor_path}.\n"
                "The shared-memory format may have changed between Firedancer "
                "versions.  Check fdmon's shm.py against your fdctl build."
            )
        if header[1] != _VERSION:
            logger.warning(
                "Monitor file version %d differs from expected %d; "
                "some metrics may be misread.",
                header[1],
                _VERSION,
            )

        self._connected = True
        logger.info("SHM backend connected: %s (%d tiles)", self._monitor_path, header[2])

    def disconnect(self) -> None:
        self._cleanup()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_tiles(self) -> List[TileSnapshot]:
        if not self._map:
            raise BackendError("Not connected")
        try:
            return self._parse()
        except struct.error as exc:
            raise BackendError(f"Failed to parse SHM data: {exc}") from exc

    # ── Internal ─────────────────────────────────────────────────────────────

    def _read_header(self):
        assert self._map is not None
        self._map.seek(0)
        return struct.unpack(_HEADER_FMT, self._map.read(_HEADER_SIZE))

    def _parse(self) -> List[TileSnapshot]:
        assert self._map is not None
        self._map.seek(0)
        header = struct.unpack(_HEADER_FMT, self._map.read(_HEADER_SIZE))
        # header: (magic, version, tile_cnt, ts_nanos, res0, res1)
        tile_cnt = header[2]

        tiles: List[TileSnapshot] = []
        for _ in range(tile_cnt):
            raw = self._map.read(_TILE_SIZE)
            if len(raw) < _TILE_SIZE:
                break
            fields = struct.unpack(_TILE_FMT, raw)
            (
                name_bytes,
                kind_id, pid, cpu_idx,
                hb_count, hb_lagged,
                in_bp, bp_count,
                msgs_in, msgs_out, bytes_in, bytes_out,
                ts_nanos_beat,
                *_reserved,
            ) = fields

            name = name_bytes.rstrip(b"\x00").decode("ascii", errors="replace")
            last_beat_ts = ts_nanos_beat / 1e9 if ts_nanos_beat else 0.0

            snap = TileSnapshot(
                name=name,
                kind_id=int(kind_id),
                pid=int(pid) if pid else None,
                cpu_idx=int(cpu_idx),
                heartbeat_count=int(hb_count),
                heartbeat_lagged_count=int(hb_lagged),
                in_backpressure=bool(in_bp),
                backpressure_count=int(bp_count),
                last_beat_ts=last_beat_ts,
                ts=time.time(),
                extra={
                    "msgs_in":   int(msgs_in),
                    "msgs_out":  int(msgs_out),
                    "bytes_in":  int(bytes_in),
                    "bytes_out": int(bytes_out),
                },
            )
            tiles.append(snap)

        return tiles

    def _cleanup(self) -> None:
        if self._map:
            try:
                self._map.close()
            except Exception:
                pass
            self._map = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
