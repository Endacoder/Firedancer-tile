# ⚡ Firedancer Tile Monitor (`fdmon`)

A lightweight, open-source CLI dashboard that monitors the health of every
**Firedancer** tile in real time — heartbeat lag, backpressure, TPS, and more.

Firedancer (the high-performance Solana validator client) uses a *tiled*
architecture in which each logical task (networking, QUIC, signature
verification, packing, PoH, etc.) runs pinned to a dedicated CPU core and
communicates with adjacent tiles through lock-free shared-memory queues.
A lagging or stuck tile can silently degrade block production long before
any on-chain metric changes.  `fdmon` surfaces these issues immediately.

---

## Screenshots

### `fdmon monitor --sim` — live dashboard

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚡ Firedancer Tile Monitor  v1.0.0 │ Backend: Simulator │ 14:07:43         ║
║  up 00:02:11 │ ● LIVE                                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
╭─ Tile Health ────────────────────────────────────────────────────────────────╮
│  Tile          PID    CPU    Status        Beat age    Lag/s  BP      TPS ↓  TPS ↑  Note
│ ─────────────────────────────────────────────────────────────────────────────
│  net[0]      10000      0  ● HEALTHY      0.09s ago    0.00  ○ no    61.2K  59.8K
│  net[1]      10001      1  ● HEALTHY      0.11s ago    0.00  ○ no    60.4K  58.7K
│  quic[0]     10002      2  ● HEALTHY      0.10s ago    0.00  ○ no    54.1K  53.6K
│  quic[1]     10003      3  ▲ WARNING      4.83s ago    0.00  ○ no    52.3K  51.9K  stale 4.8s (warn >3s)
│  verify[0]   10004      4  ● HEALTHY      0.08s ago    0.00  ○ no    50.1K  49.3K
│  verify[1]   10005      5  ● HEALTHY      0.09s ago    0.62  ○ no    48.8K  47.6K  lag 0.62/s (warn >0.5/s)
│  verify[2]   10006      6  ✖ CRITICAL     9.21s ago    0.00  ○ no    46.2K  45.1K  stale 9.2s (crit >8s)
│  verify[3]   10007      7  ● HEALTHY      0.10s ago    0.00  ○ no    49.7K  48.8K
│  dedup[0]    10008      8  ● HEALTHY      0.12s ago    0.00  ● YES   44.3K  43.1K  backpressured
│  pack[0]     10009      9  ● HEALTHY      0.09s ago    0.00  ○ no    40.8K  39.5K
│  bank[0]     10010     10  ● HEALTHY      0.11s ago    0.00  ○ no    35.7K  34.6K
│  bank[1]     10011     11  ● HEALTHY      0.10s ago    0.00  ○ no    34.9K  34.1K
│  poh[0]      10012     12  ● HEALTHY      0.08s ago    0.00  ○ no    37.2K  36.1K
│  shred[0]    10013     13  ● HEALTHY      0.11s ago    0.00  ○ no    36.5K  35.3K
│  shred[1]    10014     14  ● HEALTHY      0.09s ago    0.00  ○ no    35.1K  34.0K
│  store[0]    10015     15  ● HEALTHY      0.12s ago    0.00  ○ no    34.8K  33.9K
│  gossip[0]   10016     16  ● HEALTHY      0.10s ago    0.00  ○ no      947    931
│  repair[0]   10017     17  ● HEALTHY      0.11s ago    0.00  ○ no      512    501
│  sign[0]     10018     18  ● HEALTHY      0.09s ago    0.00  ○ no      201    198
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Active Alerts  1 CRIT  2 WARN ─────────────────────────────────────────────╮
│  [CRIT] verify:2: No heartbeat for 9.2s — tile may be crashed (9s ago)      │
│  [WARN] quic:1: Heartbeat stale for 4.8s (warn >3s)  (5s ago)               │
│  [WARN] verify:1: Heartbeat lagging 0.62/s (warn >0.5/s)  (2s ago)          │
╰──────────────────────────────────────────────────────────────────────────────╯
  [Q/Ctrl-C] Quit   [A] Acknowledge all alerts   [S] Snapshot JSON
```

### `fdmon status --sim` — one-shot status table

```
$ fdmon status --sim

                    Firedancer Tile Status  (via Simulator)
╭──────────┬───────┬─────┬──────────────┬──────────┬───────┬──────────┬───────┬───────╮
│ Tile     │   PID │ CPU │ Status       │ Beat age │ Lag/s │ Backpres │ TPS ↓ │ TPS ↑ │
├──────────┼───────┼─────┼──────────────┼──────────┼───────┼──────────┼───────┼───────┤
│ bank[0]  │ 10010 │  10 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 33.6K │ 32.5K │
│ bank[1]  │ 10011 │  11 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 35.2K │ 35.0K │
│ dedup[0] │ 10008 │   8 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 44.7K │ 43.6K │
│ gossip[0]│ 10016 │  16 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │   934 │   921 │
│ net[0]   │ 10000 │   0 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 61.4K │ 61.3K │
│ net[1]   │ 10001 │   1 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 61.9K │ 59.1K │
│ pack[0]  │ 10009 │   9 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 37.4K │ 36.3K │
│ poh[0]   │ 10012 │  12 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 36.7K │ 35.7K │
│ quic[0]  │ 10002 │   2 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 49.8K │ 49.2K │
│ quic[1]  │ 10003 │   3 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 55.3K │ 54.0K │
│ repair[0]│ 10017 │  17 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │   522 │   509 │
│ shred[0] │ 10013 │  13 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 34.2K │ 32.6K │
│ shred[1] │ 10014 │  14 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 36.5K │ 35.2K │
│ sign[0]  │ 10018 │  18 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │   195 │   185 │
│ store[0] │ 10015 │  15 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 31.5K │ 30.8K │
│ verify[0]│ 10004 │   4 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 48.7K │ 46.4K │
│ verify[1]│ 10005 │   5 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 54.3K │ 51.9K │
│ verify[2]│ 10006 │   6 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 45.7K │ 43.6K │
│ verify[3]│ 10007 │   7 │ ● HEALTHY    │     0.0s │  0.00 │  ○ no    │ 52.2K │ 49.9K │
╰──────────┴───────┴─────┴──────────────┴──────────┴───────┴──────────┴───────┴───────╯
```

### `fdmon status --sim --format json` — scripting-friendly output

```json
$ fdmon status --sim --format json

[
  {
    "tile": "net",
    "kind_id": 0,
    "pid": 10000,
    "cpu": 0,
    "status": "healthy",
    "heartbeat_age_s": 0.09,
    "heartbeat_lag_rate": 0.0,
    "in_backpressure": false,
    "backpressure_count": 0,
    "msgs_in_rate": 61200.0,
    "msgs_out_rate": 59800.0
  },
  {
    "tile": "quic",
    "kind_id": 0,
    "pid": 10002,
    "cpu": 2,
    "status": "healthy",
    "heartbeat_age_s": 0.10,
    "heartbeat_lag_rate": 0.0,
    "in_backpressure": false,
    "backpressure_count": 0,
    "msgs_in_rate": 54100.0,
    "msgs_out_rate": 53600.0
  },
  ...
]
```

### `fdmon check` — Nagios / cron health check

```
$ fdmon check --backend prometheus
OK: all 19 tiles healthy
$ echo $?
0

# When a tile is degraded:
$ fdmon check --backend prometheus
verify[2]: CRITICAL — stale 11.3s (crit >8s)
quic[1]:   WARNING  — lag 0.73/s (warn >0.5/s)
$ echo $?
2
```

---

## Features

| Feature | Details |
|---|---|
| **Live dashboard** | Rich terminal UI refreshed every second |
| **Heartbeat monitoring** | Detects stale tiles (crashed / hung) and lag rate |
| **Backpressure detection** | Flags tiles being choked by downstream congestion |
| **TPS throughput** | Messages per second in/out for every tile instance |
| **Alert engine** | CRITICAL / WARNING / INFO with deduplication window |
| **Discord / Slack alerts** | Incoming webhook support |
| **Log file** | Append alerts to a file for Grafana / ELK ingestion |
| **Multiple backends** | Prometheus HTTP · Linux SHM · fdctl JSON · Simulator |
| **Check command** | Nagios-compatible exit codes for cron monitoring |
| **Simulation mode** | Full demo without a live validator |

---

## Quick start

```bash
# 1. Install
pip install -e .          # from source
# or: pip install fdmon   # once published

# 2. Demo (no validator needed)
fdmon monitor --sim

# 3. Connect to a live validator
fdmon monitor --backend prometheus --metrics-url http://127.0.0.1:7999/metrics

# 4. One-shot health report (table)
fdmon status --sim

# 5. One-shot health report (JSON, for scripting)
fdmon status --sim --format json

# 6. Cron / Nagios check
fdmon check --backend prometheus
```

---

## Installation

**Requirements**: Python 3.8+, `rich`, `click`, `requests`, `pyyaml`

```bash
git clone https://github.com/your-org/firedancer-tile-monitor
cd firedancer-tile-monitor
pip install -e .
```

---

## Backends

### `prometheus` (recommended for production)

Firedancer's `metric` tile serves Prometheus-format metrics at
`http://127.0.0.1:7999/metrics` by default.

```bash
fdmon monitor --backend prometheus \
              --metrics-url http://127.0.0.1:7999/metrics
```

### `shm` (Linux only — lowest latency)

Reads the binary monitor region from Firedancer's shared-memory workspace
(`/dev/shm/<workspace_name>/monitor`) using `mmap`.  Requires read access
to the workspace files.

```bash
fdmon monitor --backend shm
# or in config.yaml:
#   backend:
#     type: shm
#     shm_path: /dev/shm/fd1
```

> **NOTE**: The binary layout is based on Firedancer 0.2.x.  Always verify
> `fdmon/backends/shm.py` against your running `fdctl` version's
> `src/app/fdctl/monitor/fd_topo_mon.c`.

### `fdctl` (streams fdctl JSON output)

Requires Firedancer ≥ 0.2 with `fdctl monitor --format json` support.

```bash
fdmon monitor --backend fdctl
```

### `simulator` (demo / CI)

Generates realistic synthetic metrics with random anomaly injection.
No validator needed.

```bash
fdmon monitor --sim
```

---

## Alert delivery

### Log file

```yaml
# config.yaml
alerts:
  log_file: /var/log/fdmon/alerts.log
```

### Discord / Slack webhook

```yaml
alerts:
  webhook_url: "https://discord.com/api/webhooks/<id>/<token>"
```

Alerts are delivered as rich embeds with colour-coded severity.

### Terminal bell

Enabled by default.  Disable with `--no-sound` or `sound: false` in config.

---

## Configuration reference

Copy `config.example.yaml` to `config.yaml` and pass it with `-c`:

```bash
fdmon monitor -c config.yaml
```

Key settings:

| Setting | Default | Description |
|---|---|---|
| `backend.type` | `simulator` | `prometheus` / `shm` / `fdctl` / `simulator` |
| `backend.metrics_url` | `http://127.0.0.1:7999/metrics` | Prometheus endpoint |
| `thresholds.heartbeat_stale_warn_s` | `3.0` | Warn after N s without heartbeat |
| `thresholds.heartbeat_stale_crit_s` | `8.0` | Critical after N s without heartbeat |
| `thresholds.heartbeat_lag_rate_warn` | `0.5` | Warn at N lagged beats/s |
| `thresholds.heartbeat_lag_rate_crit` | `2.0` | Critical at N lagged beats/s |
| `thresholds.tile_overrides` | `{}` | Per-tile threshold overrides |
| `alerts.dedup_window_s` | `60.0` | Suppress duplicate alerts for N s |
| `refresh_interval_s` | `1.0` | Dashboard refresh rate |

---

## Firedancer tile reference

| Tile | Instances | Role |
|---|---|---|
| `net` | 2 | XDP / kernel network I/O |
| `quic` | 2 | QUIC transport (transactions in) |
| `verify` | 4 | Ed25519 signature verification |
| `dedup` | 1 | Transaction deduplication |
| `pack` | 1 | Pack transactions into blocks |
| `bank` | 2 | Execute transactions (SVM) |
| `poh` | 1 | Proof-of-History tick loop |
| `shred` | 2 | Shred creation & propagation |
| `store` | 1 | Persistent block storage |
| `gossip` | 1 | Gossip protocol |
| `repair` | 1 | Missing shred repair |
| `sign` | 1 | Vote / block signing |

Each tile runs in an infinite loop issuing periodic *heartbeat* counter
increments (~1 000/s).  `fdmon` treats a tile as **stale** when its
heartbeat timestamp has not advanced beyond the configured threshold.

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Project layout

```
fdmon/
├── __init__.py
├── __main__.py         python -m fdmon
├── cli.py              Click commands: monitor / status / check
├── dashboard.py        Rich TUI layout
├── health.py           TileHealth computation from snapshot deltas
├── models.py           TileSnapshot, TileHealth, Alert data classes
├── config.py           Configuration dataclasses + YAML loader
├── alerts.py           AlertEngine: evaluation, dedup, dispatch
└── backends/
    ├── base.py         Abstract BaseBackend
    ├── prometheus.py   HTTP Prometheus scraper
    ├── shm.py          Linux mmap shared-memory reader
    ├── fdctl.py        fdctl --format json subprocess reader
    └── simulator.py    Synthetic data generator
tests/
├── test_models_and_health.py
├── test_alerts.py
└── test_backends.py
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
