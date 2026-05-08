"""Tests for fdmon.backends.simulator and fdmon.backends.prometheus (parsing)."""

import time
import pytest

from fdmon.config import BackendConfig
from fdmon.backends.simulator import SimulatorBackend
from fdmon.backends.prometheus import PrometheusBackend, _parse_text


# ---------------------------------------------------------------------------
# Simulator backend
# ---------------------------------------------------------------------------

class TestSimulatorBackend:
    def _backend(self, **kwargs):
        cfg = BackendConfig(type="simulator", sim_anomaly_rate=0.0, **kwargs)
        return SimulatorBackend(cfg)

    def test_connect_disconnect(self):
        b = self._backend()
        assert not b.is_connected
        b.connect()
        assert b.is_connected
        b.disconnect()
        assert not b.is_connected

    def test_read_tiles_returns_list(self):
        b = self._backend()
        with b:
            snaps = b.read_tiles()
        assert isinstance(snaps, list)
        assert len(snaps) > 0

    def test_snapshot_fields(self):
        b = self._backend()
        with b:
            snaps = b.read_tiles()
        for s in snaps:
            assert s.name
            assert s.kind_id >= 0
            assert s.pid  is not None
            assert s.ts   > 0
            assert s.last_beat_ts > 0
            assert "tps_in"  in s.extra
            assert "tps_out" in s.extra

    def test_tile_names(self):
        b = self._backend()
        with b:
            snaps = b.read_tiles()
        names = {s.name for s in snaps}
        # All core tiles should be present
        for expected in ("net", "quic", "verify", "dedup", "pack", "bank", "poh"):
            assert expected in names, f"Missing tile: {expected}"

    def test_counters_increase_over_time(self):
        b = self._backend()
        with b:
            s1_map = {f"{s.name}:{s.kind_id}": s for s in b.read_tiles()}
            time.sleep(0.1)
            s2_map = {f"{s.name}:{s.kind_id}": s for s in b.read_tiles()}

        advances = 0
        for key in s1_map:
            if key in s2_map:
                if s2_map[key].heartbeat_count > s1_map[key].heartbeat_count:
                    advances += 1
        assert advances > 0, "No heartbeat counter advanced between reads"

    def test_context_manager(self):
        b = self._backend()
        with b as backend:
            assert backend.is_connected
            snaps = backend.read_tiles()
            assert snaps
        assert not b.is_connected


# ---------------------------------------------------------------------------
# Prometheus text parser
# ---------------------------------------------------------------------------

SAMPLE_METRICS = """\
# HELP fd_tile_heartbeat_lagged_count Number of lagged heartbeats
# TYPE fd_tile_heartbeat_lagged_count counter
fd_tile_heartbeat_lagged_count{tile="quic",kind_id="0"} 3
fd_tile_heartbeat_lagged_count{tile="verify",kind_id="1"} 0
# HELP fd_tile_in_backpressure Whether tile is backpressured
# TYPE fd_tile_in_backpressure gauge
fd_tile_in_backpressure{tile="quic",kind_id="0"} 1
fd_tile_in_backpressure{tile="verify",kind_id="1"} 0
# HELP fd_tile_backpressure_count Cumulative backpressure events
fd_tile_backpressure_count{tile="quic",kind_id="0"} 7
fd_tile_pid{tile="quic",kind_id="0"} 18234
fd_tile_cpu{tile="quic",kind_id="0"} 4
"""


class TestPrometheusParser:
    def test_parse_text_basics(self):
        rows = _parse_text(SAMPLE_METRICS)
        names = {r[0] for r in rows}
        assert "fd_tile_heartbeat_lagged_count" in names
        assert "fd_tile_in_backpressure"        in names

    def test_parse_text_labels(self):
        rows = _parse_text(SAMPLE_METRICS)
        quic_lag = next(
            r for r in rows
            if r[0] == "fd_tile_heartbeat_lagged_count"
            and r[1].get("tile") == "quic"
        )
        assert quic_lag[2] == pytest.approx(3.0)

    def test_parse_text_skips_comments(self):
        rows = _parse_text(SAMPLE_METRICS)
        for name, _, _ in rows:
            assert not name.startswith("#")

    def test_prometheus_backend_parse(self):
        cfg     = BackendConfig(type="prometheus")
        backend = PrometheusBackend(cfg)
        snaps   = backend._parse(SAMPLE_METRICS)

        assert len(snaps) == 2  # quic:0 and verify:1

        quic = next(s for s in snaps if s.name == "quic" and s.kind_id == 0)
        assert quic.heartbeat_lagged_count == 3
        assert quic.in_backpressure        is True
        assert quic.backpressure_count     == 7
        assert quic.pid                    == 18234
        assert quic.cpu_idx                == 4

        verify = next(s for s in snaps if s.name == "verify" and s.kind_id == 1)
        assert verify.heartbeat_lagged_count == 0
        assert verify.in_backpressure        is False
