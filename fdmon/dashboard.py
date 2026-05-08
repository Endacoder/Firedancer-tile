"""
Rich TUI dashboard for Firedancer Tile Monitor.

Layout (terminal rows, top → bottom):
┌─ Header bar ───────────────────────────────────────────────────────────┐
│  Backend | Time | Uptime | Connection status                           │
├─ Tile health table ─────────────────────────────────────────────────────┤
│  Tile | PID | CPU | Status | Heartbeat age | Lag/s | BP | TPS↓ | TPS↑ │
│  …                                                                      │
├─ Alert panel ───────────────────────────────────────────────────────────┤
│  Recent + active alerts with severity badges                            │
└─ Footer key-hint bar ───────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from rich import box
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fdmon.alerts import AlertEngine
from fdmon.models import Alert, AlertSeverity, TileHealth, TileStatus

# ── Style maps ───────────────────────────────────────────────────────────────

_STATUS_STYLE = {
    TileStatus.HEALTHY:  ("bold green",  "●"),
    TileStatus.WARNING:  ("bold yellow", "▲"),
    TileStatus.CRITICAL: ("bold red",    "✖"),
    TileStatus.STALE:    ("dim",         "○"),
    TileStatus.UNKNOWN:  ("grey50",      "?"),
}

_ALERT_STYLE = {
    AlertSeverity.CRITICAL: ("bold red",     "CRIT"),
    AlertSeverity.WARNING:  ("bold yellow",  "WARN"),
    AlertSeverity.INFO:     ("bold cyan",    "INFO"),
}

_VERSION = "1.0.0"


def _fmt_tps(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def _heartbeat_text(age: float) -> Text:
    if age == float("inf"):
        return Text("── never ──", style="dim")
    if age > 8.0:
        return Text(f"{age:.1f}s ago", style="bold red")
    if age > 3.0:
        return Text(f"{age:.1f}s ago", style="yellow")
    return Text(f"{age:.2f}s ago", style="green")


def _lag_text(lag: float) -> Text:
    if lag > 2.0:
        return Text(f"{lag:.2f}", style="bold red")
    if lag > 0.5:
        return Text(f"{lag:.2f}", style="yellow")
    return Text(f"{lag:.2f}", style="green")


# ---------------------------------------------------------------------------
# Dashboard class
# ---------------------------------------------------------------------------

class Dashboard:
    """Builds Rich renderables from tile health data."""

    def __init__(
        self,
        console: Optional[Console] = None,
        alert_engine: Optional[AlertEngine] = None,
    ) -> None:
        self.console       = console or Console(legacy_windows=False)
        self.alert_engine  = alert_engine
        self._start_time   = time.time()

    # ── Public render entry-point ─────────────────────────────────────────────

    def render(
        self,
        healths:      List[TileHealth],
        backend_type: str,
        connected:    bool,
    ) -> Layout:
        """Return a fully-populated Rich Layout ready for Live.update()."""
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="header",  size=3),
            Layout(name="tiles"),
            Layout(name="alerts",  size=12),
            Layout(name="footer",  size=1),
        )

        layout["header"].update(self._header(backend_type, connected))
        layout["tiles"].update(
            Panel(
                self._tile_table(healths),
                title="[bold cyan]Tile Health[/bold cyan]",
                border_style="cyan",
            )
        )
        layout["alerts"].update(self._alert_panel())
        layout["footer"].update(self._footer())

        return layout

    # ── Header ────────────────────────────────────────────────────────────────

    def _header(self, backend_type: str, connected: bool) -> Panel:
        now    = datetime.now().strftime("%H:%M:%S")
        uptime = int(time.time() - self._start_time)
        h, rem = divmod(uptime, 3600)
        m, s   = divmod(rem, 60)

        conn_str = (
            "[bold green]● LIVE[/bold green]"
            if connected
            else "[bold red]✖ DISCONNECTED[/bold red]"
        )

        content = (
            f"[bold blue]⚡ Firedancer Tile Monitor[/bold blue]  v{_VERSION}"
            f"   │   Backend: [bold]{backend_type}[/bold]"
            f"   │   {now}"
            f"   │   up [bold]{h:02d}:{m:02d}:{s:02d}[/bold]"
            f"   │   {conn_str}"
        )
        return Panel(content, box=box.HORIZONTALS, style="bold", padding=(0, 1))

    # ── Tile table ────────────────────────────────────────────────────────────

    def _tile_table(self, healths: List[TileHealth]) -> Table:
        table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            expand=True,
            padding=(0, 1),
            show_edge=False,
        )

        table.add_column("Tile",      style="bold white", min_width=12, no_wrap=True)
        table.add_column("PID",       justify="right",   min_width=7)
        table.add_column("CPU",       justify="right",   min_width=4)
        table.add_column("Status",    justify="center",   min_width=12)
        table.add_column("Beat age",  justify="right",   min_width=12)
        table.add_column("Lag/s",     justify="right",   min_width=7)
        table.add_column("Backpress", justify="center",   min_width=10)
        table.add_column("TPS ↓",    justify="right",   min_width=8)
        table.add_column("TPS ↑",    justify="right",   min_width=8)
        table.add_column("Note",      min_width=22)

        sorted_healths = sorted(
            healths,
            key=lambda h: (h.snapshot.name, h.snapshot.kind_id),
        )

        for h in sorted_healths:
            snap          = h.snapshot
            style_str, sym = _STATUS_STYLE[h.status]
            status_text   = Text(f"{sym} {h.status.value.upper()}", style=style_str)

            bp_text = (
                Text("● YES", style="bold yellow")
                if snap.in_backpressure
                else Text("○ no", style="dim")
            )

            tps_in  = snap.extra.get("tps_in",  0)
            tps_out = snap.extra.get("tps_out", 0)

            row_style = ""
            if h.status == TileStatus.CRITICAL:
                row_style = "on dark_red"
            elif h.status == TileStatus.WARNING:
                row_style = ""   # colour comes from the cell styles

            table.add_row(
                h.display_name,
                str(snap.pid)    if snap.pid     is not None else "—",
                str(snap.cpu_idx) if snap.cpu_idx is not None else "—",
                status_text,
                _heartbeat_text(h.heartbeat_age_sec),
                _lag_text(h.heartbeat_lag_rate),
                bp_text,
                _fmt_tps(tps_in),
                _fmt_tps(tps_out),
                Text(h.status_reason, style=style_str),
                style=row_style,
            )

        if not healths:
            table.add_row(
                *["[dim]—[/dim]"] * 10,
            )

        return table

    # ── Alert panel ───────────────────────────────────────────────────────────

    def _alert_panel(self) -> Panel:
        if not self.alert_engine:
            return Panel("[dim]No alert engine configured.[/dim]", title="Alerts")

        active  = self.alert_engine.active_alerts
        summary = self.alert_engine.get_summary()
        crit    = summary.get("critical", 0)
        warn    = summary.get("warning",  0)

        # Build badge
        badge = ""
        if crit:
            badge += f" [bold red]{crit} CRIT[/bold red]"
        if warn:
            badge += f" [bold yellow]{warn} WARN[/bold yellow]"
        if not crit and not warn:
            badge = " [bold green]ALL CLEAR[/bold green]"

        # Build body
        if not active:
            body = Text("✓ All tiles healthy — no active alerts.", style="bold green")
        else:
            lines: List[Text] = []
            for alert in active[:10]:  # cap display
                sev_style, sev_label = _ALERT_STYLE[alert.severity]
                age_s = alert.age_sec
                age_str = f"{age_s:.0f}s ago" if age_s < 120 else f"{age_s / 60:.0f}m ago"

                line = Text()
                line.append(f"[{sev_label}] ", style=sev_style)
                line.append(f"{alert.tile_id}: ", style="bold white")
                line.append(alert.message)
                line.append(f"  ({age_str})", style="dim")
                lines.append(line)

            body = Text("\n").join(lines)

        border = "red" if crit else "yellow" if warn else "green"
        return Panel(
            body,
            title=f"[bold]Active Alerts[/bold]{badge}",
            border_style=border,
        )

    # ── Footer ────────────────────────────────────────────────────────────────

    def _footer(self) -> Align:
        hint = Text(
            " [Q/Ctrl-C] Quit   [A] Acknowledge all alerts   [S] Snapshot JSON ",
            style="dim",
            justify="center",
        )
        return Align(hint, align="center")
