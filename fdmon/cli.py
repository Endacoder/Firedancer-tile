"""
CLI entry-point.

Commands
────────
  fdmon monitor   Live dashboard (default command)
  fdmon status    One-shot tile status report (table or JSON)
  fdmon check     Exit-code health check suitable for cron / Nagios

Examples
────────
  # Demo with simulated tiles
  fdmon monitor --sim

  # Connect to a local validator's Prometheus endpoint
  fdmon monitor --backend prometheus --metrics-url http://127.0.0.1:7999/metrics

  # Alert to a Discord webhook and log file
  fdmon monitor --sim --webhook-url https://discord.com/api/webhooks/... \\
                       --log-file /var/log/fdmon/alerts.log

  # One-shot JSON report
  fdmon status --sim --format json

  # Cron-friendly check (exits 2 on CRITICAL, 1 on WARNING, 0 if healthy)
  fdmon check --backend prometheus
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Dict, List, Optional

import click
from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from fdmon import __version__
from fdmon.alerts import AlertEngine
from fdmon.config import Config
from fdmon.dashboard import Dashboard
from fdmon.health import compute_health
from fdmon.models import TileHealth, TileSnapshot, TileStatus

console = Console(legacy_windows=False)
logger  = logging.getLogger("fdmon")


# ---------------------------------------------------------------------------
# Helper: build the right backend from config
# ---------------------------------------------------------------------------

def _make_backend(cfg: Config):
    """Return (backend_instance, display_label) based on cfg.backend.type."""
    t = cfg.backend.type.lower()
    if t == "prometheus":
        from fdmon.backends.prometheus import PrometheusBackend
        return PrometheusBackend(cfg.backend), "Prometheus"
    if t == "fdctl":
        from fdmon.backends.fdctl import FdctlBackend
        return FdctlBackend(cfg.backend), "fdctl"
    if t == "shm":
        from fdmon.backends.shm import ShmBackend
        return ShmBackend(cfg.backend), "Shared Memory"
    from fdmon.backends.simulator import SimulatorBackend
    return SimulatorBackend(cfg.backend), "Simulator"


# ---------------------------------------------------------------------------
# Helper: set up alert handlers from config
# ---------------------------------------------------------------------------

def _attach_handlers(engine: AlertEngine, cfg: Config) -> None:
    from fdmon.models import AlertSeverity

    if cfg.alerts.log_file:
        al = logging.getLogger("fdmon.alert")

        def _log_handler(alert):
            al.warning(str(alert))

        engine.add_handler(_log_handler)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(message)s",
            handlers=[logging.FileHandler(cfg.alerts.log_file, encoding="utf-8")],
        )

    if cfg.alerts.webhook_url:
        import requests as _req

        _webhook_url = cfg.alerts.webhook_url

        def _webhook_handler(alert):
            colours = {"critical": 0xFF0000, "warning": 0xFFAA00, "info": 0x0088FF}
            payload = {
                "embeds": [
                    {
                        "title":       f"[{alert.severity.value.upper()}] {alert.tile_id}",
                        "description": alert.message,
                        "color":       colours.get(alert.severity.value, 0x888888),
                        "footer":      {"text": f"fdmon v{__version__} — Firedancer Tile Monitor"},
                    }
                ]
            }
            try:
                _req.post(_webhook_url, json=payload, timeout=5)
            except Exception as exc:
                logger.debug("Webhook delivery failed: %s", exc)

        engine.add_handler(_webhook_handler)

    if cfg.alerts.sound:
        def _bell_handler(alert):
            if alert.severity == AlertSeverity.CRITICAL:
                print("\a", end="", flush=True)  # ANSI terminal bell

        engine.add_handler(_bell_handler)


# ---------------------------------------------------------------------------
# Shared Click options
# ---------------------------------------------------------------------------

def _shared_options(fn):
    """Decorator that adds options common to multiple commands."""
    fn = click.option(
        "--config", "-c", "config_file", default=None,
        metavar="PATH", help="YAML config file (see config.example.yaml).",
    )(fn)
    fn = click.option(
        "--backend", "-b", "backend_type", default=None,
        type=click.Choice(["prometheus", "fdctl", "shm", "simulator"], case_sensitive=False),
        help="Data backend to use.",
    )(fn)
    fn = click.option(
        "--sim", is_flag=True, default=False,
        help="Shorthand for --backend simulator.",
    )(fn)
    fn = click.option(
        "--metrics-url", default=None,
        metavar="URL",
        help="Prometheus metrics URL (implies --backend prometheus).",
    )(fn)
    return fn


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="fdmon")
def cli():
    """⚡ Firedancer Tile Monitor — real-time validator tile health."""


# ---------------------------------------------------------------------------
# `fdmon monitor`
# ---------------------------------------------------------------------------

@cli.command()
@_shared_options
@click.option("--interval", "-i", default=None, type=float,
              help="Refresh interval in seconds (overrides config).")
@click.option("--log-file",    default=None, metavar="PATH",
              help="Append alert lines to this file.")
@click.option("--webhook-url", default=None, metavar="URL",
              help="Discord / Slack incoming webhook for CRITICAL/WARNING alerts.")
@click.option("--no-sound", is_flag=True, default=False,
              help="Disable terminal bell on CRITICAL alerts.")
def monitor(
    config_file, backend_type, sim, metrics_url,
    interval, log_file, webhook_url, no_sound,
):
    """Launch the live tile health dashboard.  Press Q or Ctrl-C to quit."""
    cfg = Config.from_file(config_file) if config_file else Config.default()

    # CLI overrides
    if sim:
        cfg.backend.type = "simulator"
    elif backend_type:
        cfg.backend.type = backend_type

    if metrics_url:
        cfg.backend.metrics_url = metrics_url
        cfg.backend.type        = "prometheus"

    if interval is not None:
        cfg.refresh_interval_s = interval
    if log_file:
        cfg.alerts.log_file = log_file
    if webhook_url:
        cfg.alerts.webhook_url = webhook_url
    if no_sound:
        cfg.alerts.sound = False

    alert_engine            = AlertEngine(cfg.thresholds, cfg.alerts)
    _attach_handlers(alert_engine, cfg)

    backend, label          = _make_backend(cfg)
    dash                    = Dashboard(console=console, alert_engine=alert_engine)
    prev_snaps: Dict[str, TileSnapshot] = {}

    console.print(
        f"[bold blue]Firedancer Tile Monitor[/bold blue] v{__version__}"
        f"  │  backend: [bold]{label}[/bold]"
        f"  │  press [bold]Ctrl-C[/bold] to exit"
    )

    try:
        backend.connect()
    except Exception as exc:
        console.print(f"[bold red]Cannot connect:[/bold red] {exc}")
        if cfg.backend.type != "simulator":
            console.print("[dim]Tip: add --sim to run in simulation mode.[/dim]")
        sys.exit(1)

    try:
        with Live(console=console, refresh_per_second=4, screen=True) as live:
            while True:
                try:
                    snapshots = backend.read_tiles()
                except Exception as exc:
                    logger.error("read_tiles failed: %s", exc)
                    snapshots = []

                healths: List[TileHealth] = []
                for snap in snapshots:
                    key    = f"{snap.name}:{snap.kind_id}"
                    prev   = prev_snaps.get(key)
                    health = compute_health(
                        snap, prev,
                        heartbeat_stale_warn_s=cfg.thresholds.heartbeat_stale_warn_s,
                        heartbeat_stale_crit_s=cfg.thresholds.heartbeat_stale_crit_s,
                        heartbeat_lag_rate_warn=cfg.thresholds.heartbeat_lag_rate_warn,
                        heartbeat_lag_rate_crit=cfg.thresholds.heartbeat_lag_rate_crit,
                    )
                    healths.append(health)
                    prev_snaps[key] = snap
                    alert_engine.evaluate(health)

                live.update(
                    dash.render(healths=healths, backend_type=label,
                                connected=backend.is_connected)
                )
                time.sleep(cfg.refresh_interval_s)

    except KeyboardInterrupt:
        pass
    finally:
        backend.disconnect()
        console.print("\n[bold]fdmon[/bold] — goodbye!")


# ---------------------------------------------------------------------------
# `fdmon status`
# ---------------------------------------------------------------------------

@cli.command()
@_shared_options
@click.option("--format", "fmt", default="table",
              type=click.Choice(["table", "json"]), help="Output format.")
def status(config_file, backend_type, sim, metrics_url, fmt):
    """Print a one-shot tile status report and exit."""
    cfg = Config.from_file(config_file) if config_file else Config.default()

    if sim:
        cfg.backend.type = "simulator"
    elif backend_type:
        cfg.backend.type = backend_type
    if metrics_url:
        cfg.backend.metrics_url = metrics_url
        cfg.backend.type        = "prometheus"

    backend, label = _make_backend(cfg)

    try:
        backend.connect()
        # Two reads to get rate deltas
        snaps1 = backend.read_tiles()
        time.sleep(1.0)
        snaps2 = backend.read_tiles()
        backend.disconnect()
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    snap_map = {f"{s.name}:{s.kind_id}": s for s in snaps1}
    healths: List[TileHealth] = []
    for snap in snaps2:
        key    = f"{snap.name}:{snap.kind_id}"
        health = compute_health(snap, snap_map.get(key))
        healths.append(health)

    if fmt == "json":
        output = []
        for h in healths:
            s = h.snapshot
            output.append({
                "tile":               s.name,
                "kind_id":            s.kind_id,
                "pid":                s.pid,
                "cpu":                s.cpu_idx,
                "status":             h.status.value,
                "heartbeat_age_s":    None if h.heartbeat_age_sec == float("inf") else h.heartbeat_age_sec,
                "heartbeat_lag_rate": h.heartbeat_lag_rate,
                "in_backpressure":    s.in_backpressure,
                "backpressure_count": s.backpressure_count,
                "msgs_in_rate":       h.msgs_in_rate,
                "msgs_out_rate":      h.msgs_out_rate,
            })
        click.echo(json.dumps(output, indent=2))
    else:
        from rich.text import Text as RText
        from fdmon.dashboard import _STATUS_STYLE, _fmt_tps

        tbl = Table(
            title=f"Firedancer Tile Status  [dim](via {label})[/dim]",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        tbl.add_column("Tile",        style="bold")
        tbl.add_column("PID",         justify="right")
        tbl.add_column("CPU",         justify="right")
        tbl.add_column("Status",      justify="center")
        tbl.add_column("Beat age",    justify="right")
        tbl.add_column("Lag/s",       justify="right")
        tbl.add_column("Backpressure", justify="center")
        tbl.add_column("TPS ↓",      justify="right")
        tbl.add_column("TPS ↑",      justify="right")

        for h in sorted(healths, key=lambda x: (x.snapshot.name, x.snapshot.kind_id)):
            s           = h.snapshot
            st, sym     = _STATUS_STYLE[h.status]
            age         = h.heartbeat_age_sec
            age_str     = "never" if age == float("inf") else f"{age:.1f}s"
            tbl.add_row(
                h.display_name,
                str(s.pid)     if s.pid     is not None else "—",
                str(s.cpu_idx) if s.cpu_idx is not None else "—",
                RText(f"{sym} {h.status.value.upper()}", style=st),
                age_str,
                f"{h.heartbeat_lag_rate:.2f}",
                RText("● YES", style="bold yellow") if s.in_backpressure else RText("○ no", style="dim"),
                _fmt_tps(int(h.msgs_in_rate)),
                _fmt_tps(int(h.msgs_out_rate)),
            )
        console.print(tbl)


# ---------------------------------------------------------------------------
# `fdmon check`
# ---------------------------------------------------------------------------

@cli.command()
@_shared_options
def check(config_file, backend_type, sim, metrics_url):
    """
    Machine-readable health check (Nagios / cron compatible).

    Exit codes:
      0 = all tiles HEALTHY
      1 = at least one tile WARNING
      2 = at least one tile CRITICAL
      3 = could not read metrics (UNKNOWN)
    """
    cfg = Config.from_file(config_file) if config_file else Config.default()

    if sim:
        cfg.backend.type = "simulator"
    elif backend_type:
        cfg.backend.type = backend_type
    if metrics_url:
        cfg.backend.metrics_url = metrics_url
        cfg.backend.type        = "prometheus"

    backend, label = _make_backend(cfg)

    try:
        backend.connect()
        snaps1 = backend.read_tiles()
        time.sleep(1.0)
        snaps2 = backend.read_tiles()
        backend.disconnect()
    except Exception as exc:
        click.echo(f"UNKNOWN: cannot read metrics — {exc}")
        sys.exit(3)

    snap_map = {f"{s.name}:{s.kind_id}": s for s in snaps1}
    worst    = TileStatus.HEALTHY
    issues: List[str] = []

    for snap in snaps2:
        key    = f"{snap.name}:{snap.kind_id}"
        health = compute_health(snap, snap_map.get(key))
        if health.status in (TileStatus.CRITICAL, TileStatus.STALE):
            worst = TileStatus.CRITICAL
            issues.append(f"{health.display_name}: CRITICAL — {health.status_reason}")
        elif health.status == TileStatus.WARNING and worst != TileStatus.CRITICAL:
            worst = TileStatus.WARNING
            issues.append(f"{health.display_name}: WARNING  — {health.status_reason}")

    if worst == TileStatus.HEALTHY:
        click.echo(f"OK: all {len(snaps2)} tiles healthy")
        sys.exit(0)

    click.echo("\n".join(issues))

    if worst == TileStatus.CRITICAL:
        sys.exit(2)
    sys.exit(1)
