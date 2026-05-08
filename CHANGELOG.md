# Changelog

All notable changes to `fdmon` will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0] — 2026-05-08

### Added
- **Live TUI dashboard** (`fdmon monitor`) — Rich terminal UI with auto-refresh,
  colour-coded tile status, heartbeat age, lag rate, backpressure indicator, and TPS.
- **One-shot status report** (`fdmon status`) — table and `--format json` output.
- **Nagios/cron health check** (`fdmon check`) — exits 0 / 1 / 2 for OK / WARNING / CRITICAL.
- **Four backends**:
  - `prometheus` — scrapes Firedancer's `:7999/metrics` Prometheus endpoint.
  - `shm` — Linux `mmap` reader of the binary monitor shared-memory region.
  - `fdctl` — streams `fdctl monitor --format json` subprocess output.
  - `simulator` — synthetic tiles with configurable random anomaly injection (demo / CI).
- **Alert engine** with CRITICAL / WARNING / INFO levels, per-condition deduplication
  window, and pluggable handlers.
- **Discord / Slack webhook** delivery for alerts.
- **Log-file appending** for Grafana / ELK ingestion.
- **Terminal bell** on CRITICAL alerts (opt-out with `--no-sound`).
- **Per-tile threshold overrides** in YAML config.
- **38-test suite** covering models, health computation, alert engine, and backends.
- `pyproject.toml`, `.gitignore`, `requirements-dev.txt`, `config.example.yaml`.
