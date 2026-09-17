"""Dynamic terminal dashboard for the training monitor.

The terminal view is intentionally read-only.  The server reports physical GPU
hardware, while active run IDs determine the number of model task slots.  The
mentor sprite is a single permanent character; it is never multiplied by GPU
count.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
import select
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import requests
except ImportError:  # direct desktop mode only needs the standard library
    requests = None

try:
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by minimal installations
    RICH_AVAILABLE = False


PHASE_LABELS = {
    "preparing": "整理丹方",
    "training": "搅拌炼丹",
    "validating": "检验成丹",
    "saving": "封存模型",
    "finished": "丹成",
    "stopped": "暂时停炉",
    "paused": "暂停观察",
    "error": "炉火异常",
    "idle": "待命",
    "stalled": "炉火停滞",
}


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def effective_runs(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return active runs, including compatibility with the legacy root shape."""

    runs = [run for run in state.get("runs", []) if isinstance(run, dict)]
    if runs:
        return runs
    if state.get("run_id") and state.get("status") != "idle":
        return [dict(state)]
    return []


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def phase_for(run: Dict[str, Any], stale_after: float = 180.0, now: Optional[datetime] = None) -> str:
    """Map a server run state to a display phase and flag silent runs."""

    status = str(run.get("status") or "idle")
    if status in {"finished", "stopped", "paused"}:
        return status
    if status == "error":
        return "error"
    updated = _parse_time(run.get("updated_at"))
    if status == "training" and updated is not None:
        clock = now or datetime.now(updated.tzinfo)
        age = (clock - updated).total_seconds()
        if age > max(1.0, stale_after):
            return "stalled"
    phase = str(run.get("phase") or status)
    return phase if phase in PHASE_LABELS else "training"


def progress_percent(run: Dict[str, Any]) -> float:
    if run.get("status") == "finished":
        return 100.0
    epoch = _number(run.get("epoch")) or 0.0
    total = _number(run.get("total_epochs")) or 0.0
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, epoch / total * 100.0))


def metric_value(run: Dict[str, Any], metric_name: Optional[str] = None) -> Optional[float]:
    name = metric_name or str(run.get("metric_name") or "IoU")
    metrics = run.get("metrics")
    if isinstance(metrics, dict) and name in metrics:
        return _number(metrics.get(name))
    return _number(run.get("current_iou"))


def history_values(run: Dict[str, Any], metric_name: Optional[str] = None) -> List[float]:
    name = metric_name or str(run.get("metric_name") or "IoU")
    values: List[float] = []
    for point in run.get("history", []) if isinstance(run.get("history"), list) else []:
        if not isinstance(point, dict):
            continue
        metrics = point.get("metrics")
        value = metrics.get(name) if isinstance(metrics, dict) and name in metrics else point.get("iou")
        parsed = _number(value)
        if parsed is not None:
            values.append(parsed)
    return values


def gpu_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    hardware = state.get("hardware")
    if isinstance(hardware, dict):
        rows = [gpu for gpu in hardware.get("gpus", []) if isinstance(gpu, dict)]
        if rows:
            return rows
    fallback: List[Dict[str, Any]] = []
    for gpu_id in state.get("available_gpus", []) if isinstance(state.get("available_gpus"), list) else []:
        fallback.append({"id": str(gpu_id), "name": "reported by run"})
    return fallback


def gpu_slot_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return one visual work slot per physical GPU, even while it is idle."""

    rows = gpu_rows(state)
    if rows:
        return rows
    hardware = state.get("hardware") if isinstance(state.get("hardware"), dict) else {}
    count = hardware.get("count")
    if isinstance(count, int) and count > 0:
        return [{"id": str(index), "name": "physical GPU"} for index in range(count)]
    return []


def gpu_run_counts(runs: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for run in runs:
        ids = run.get("gpu_ids") or ([run.get("gpu_id")] if run.get("gpu_id") is not None else [])
        for gpu_id in ids:
            key = str(gpu_id)
            counts[key] = counts.get(key, 0) + 1
    return counts


def format_number(value: Any, digits: int = 4) -> str:
    parsed = _number(value)
    if parsed is None:
        return "—"
    formatted = f"{parsed:.{digits}f}"
    return formatted if digits == 0 else formatted.rstrip("0").rstrip(".")


def format_eta(value: Any) -> str:
    parsed = _number(value)
    if parsed is None or parsed < 0:
        return "—"
    seconds = int(parsed)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def progress_bar(percent: float, width: int = 24, ascii_only: bool = False) -> str:
    width = max(4, width)
    filled = min(width, max(0, int(round(percent / 100.0 * width))))
    if ascii_only:
        return "[" + "#" * filled + "." * (width - filled) + "]"
    return "[" + "━" * filled + "─" * (width - filled) + "]"


def sparkline(values: List[float], width: int = 34, ascii_only: bool = False) -> str:
    if not values:
        return "—"
    values = values[-max(1, width):]
    low, high = min(values), max(values)
    if high == low:
        indexes = [len("._-:=+*#") // 2] * len(values)
    else:
        indexes = [int((value - low) / (high - low) * 7) for value in values]
    if ascii_only:
        palette = "._-:=+*#"
    else:
        palette = "▁▂▃▄▅▆▇█"
    return "".join(palette[max(0, min(7, index))] for index in indexes)


def mentor_sprite(phase: str, ascii_only: bool = False) -> str:
    """Return a compact ANSI-safe text sprite for the permanent mentor."""

    action = PHASE_LABELS.get(phase, PHASE_LABELS["training"])
    if ascii_only:
        if phase in {"stopped", "error", "stalled"}:
            face = ["    /  o  o  \\", "   |    v    |", "    \\  _    / "]
        elif phase in {"finished", "paused"}:
            face = ["    /  o  o  \\", "   |    -    |", "    \\  ---  / "]
        else:
            face = ["    /  o  o  \\", "   |    ^    |", "    \\  ---  / "]
        lines = [
            "       *   .  ",
            "     .-''''-. ",
            *face,
            "   .-\\____/-.",
            "  /  /|    |\\  ",
            " /__/ |    | \\__",
            "    __|____|__   ",
            "   /  /    \\  \\",
            "  /__/      \\__\\",
        ]
    else:
        if phase in {"stopped", "error", "stalled"}:
            face = ["     ╱  ▣  ▣  ╲", "    │    ˅    │", "    │  ───   │"]
        elif phase in {"finished", "paused"}:
            face = ["     ╱  ▣  ▣  ╲", "    │    ─    │", "    │  ╰─╯   │"]
        else:
            face = ["     ╱  ▣  ▣  ╲", "    │    ︶    │", "    │  ╰──╯   │"]
        lines = [
            "       ✦  ·  ✧",
            "      ╭──────╮",
            *face,
            "     ╲ ╰──╯  ╱",
            "    ╭╯╲    ╱╰╮",
            "   ╱  ╱│  │╲  ╲",
            "      ╱│  │╲",
            "     ╱─╯  ╰─╲",
            "    ╱_╱    ╲_╲",
        ]
    return "\n".join(lines) + f"\n  [ {action} ]"


def worker_sprite(phase: str, ascii_only: bool = False) -> str:
    """Return a small secondary worker sprite for a GPU work slot."""

    if ascii_only:
        face = "o" if phase not in {"stopped", "error", "stalled"} else "-"
        return f" {face}\n/|\\"
    face = "•" if phase not in {"stopped", "error", "stalled"} else "─"
    return f" {face}\n╱│╲"


def _run_title(run: Dict[str, Any]) -> str:
    run_id = str(run.get("run_id") or "default")
    return run_id if len(run_id) <= 22 else run_id[:19] + "..."


def _slot_run_title(run: Dict[str, Any]) -> str:
    title = _run_title(run)
    return title if len(title) <= 8 else title[:7] + "~"


def render_run_table(runs: List[Dict[str, Any]], selected_id: Optional[str], stale_after: float) -> Any:
    table = Table(expand=True, box=None, padding=(0, 1), show_header=True, header_style="bold cyan")
    for column in ("", "运行", "状态", "进度", "损失", "指标", "GPU"):
        table.add_column(column, no_wrap=True)
    for run in runs:
        run_id = str(run.get("run_id") or "default")
        selected = run_id == selected_id
        metric_name = str(run.get("metric_name") or "IoU")
        gpu_ids = run.get("gpu_ids") or ([run.get("gpu_id")] if run.get("gpu_id") is not None else [])
        gpu_text = ",".join(str(item) for item in gpu_ids) or "—"
        status = PHASE_LABELS.get(phase_for(run, stale_after), "训练中")
        marker = "▶" if selected else " "
        epoch = f"{run.get('epoch', 0)}/{run.get('total_epochs', 0) or '?'}"
        table.add_row(
            marker,
            _run_title(run),
            status,
            f"{progress_percent(run):5.1f}% {epoch}",
            format_number((run.get("metrics") or {}).get("loss"), 5),
            f"{metric_name} {format_number(metric_value(run, metric_name))}",
            gpu_text,
        )
    if not runs:
        table.add_row("", "等待训练上报", "待命", "0.0%", "—", "—", "—")
    return table


def render_detail(run: Optional[Dict[str, Any]], stale_after: float, ascii_only: bool) -> Any:
    if run is None:
        return Panel("暂时没有模型任务\n\n启动训练后，这里会自动出现对应的炼丹炉。", title="当前丹炉", border_style="dim")
    phase = phase_for(run, stale_after)
    metric_name = str(run.get("metric_name") or "IoU")
    values = history_values(run, metric_name)
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(style="cyan", width=10)
    grid.add_column()
    grid.add_row("任务", str(run.get("run_id") or "default"))
    grid.add_row("阶段", PHASE_LABELS.get(phase, phase))
    grid.add_row("进度", f"{progress_bar(progress_percent(run), ascii_only=ascii_only)} {progress_percent(run):.1f}%")
    grid.add_row("预计剩余", format_eta(run.get("eta_seconds")))
    grid.add_row("当前损失", format_number((run.get("metrics") or {}).get("loss"), 6))
    grid.add_row("当前指标", f"{metric_name} {format_number(metric_value(run, metric_name), 6)}")
    grid.add_row("趋势", sparkline(values, ascii_only=ascii_only))
    message = run.get("message")
    if message:
        grid.add_row("提示", str(message))
    return Panel(grid, title="当前丹炉", border_style="cyan")


def render_mentor(runs: List[Dict[str, Any]], active_run_id: Optional[str], stale_after: float, ascii_only: bool) -> Any:
    active = next((run for run in runs if run.get("run_id") == active_run_id), None)
    if active is None and runs:
        active = runs[0]
    phase = phase_for(active, stale_after) if active else "idle"
    subtitle = "主炼丹师 · 始终在线"
    if runs:
        subtitle += f" · 监管 {len(runs)} 个丹炉"
    content = Group(
        Text(mentor_sprite(phase, ascii_only), style="bright_white"),
        Text(f"\n{subtitle}\n动作：{PHASE_LABELS.get(phase, phase)}", style="yellow"),
    )
    return Panel(content, title="导师炼丹主角色", border_style="magenta")


def render_alchemy_slots(
    state: Dict[str, Any], runs: List[Dict[str, Any]], selected_id: Optional[str], ascii_only: bool
) -> Any:
    """Create one small worker station per physical GPU, with run overflow tiles."""

    tiles = []
    slots = gpu_slot_rows(state)
    assigned_run_ids = set()
    for gpu in slots:
        gpu_id = str(gpu.get("id", "?"))
        assigned = []
        for run in runs:
            gpu_ids = run.get("gpu_ids") or ([run.get("gpu_id")] if run.get("gpu_id") is not None else [])
            if gpu_id in {str(item) for item in gpu_ids}:
                assigned.append(run)
                assigned_run_ids.add(str(run.get("run_id")))
        run = assigned[0] if assigned else None
        percent = progress_percent(run) if run else 0.0
        phase = phase_for(run) if run else "idle"
        tile = Text()
        tile.append(worker_sprite(phase, ascii_only) + "\n", style="bright_yellow")
        label = "G" + gpu_id
        if run:
            label += "·" + _slot_run_title(run)
        else:
            label += "·空闲"
        tile.append(label + "\n", style="bold" if run else "dim")
        tile.append(progress_bar(percent, width=6, ascii_only=ascii_only) + f" {percent:.0f}%\n")
        tile.append(PHASE_LABELS.get(phase, phase), style="cyan")
        if assigned and len(assigned) > 1:
            tile.append(f" · {len(assigned)} 个任务共享", style="dim")
        border = "yellow" if run and str(run.get("run_id")) == selected_id else "dim"
        tiles.append(Panel(tile, border_style=border, padding=(0, 1)))

    for run in runs:
        run_id = str(run.get("run_id"))
        if run_id in assigned_run_ids:
            continue
        percent = progress_percent(run)
        phase = phase_for(run)
        tile = Text()
        tile.append(worker_sprite(phase, ascii_only) + "\n", style="bright_yellow")
        tile.append("CPU·" + _slot_run_title(run) + "\n", style="bold")
        tile.append(progress_bar(percent, width=6, ascii_only=ascii_only) + f" {percent:.0f}%\n")
        tile.append(PHASE_LABELS.get(phase, phase), style="cyan")
        border = "yellow" if run_id == selected_id else "dim"
        tiles.append(Panel(tile, border_style=border, padding=(0, 1)))

    if not tiles:
        tiles.append(Panel("等待新的模型任务…", border_style="dim"))
    return Columns(tiles, expand=True, equal=True)


def render_gpu_panel(state: Dict[str, Any], runs: List[Dict[str, Any]]) -> Any:
    hardware = state.get("hardware") if isinstance(state.get("hardware"), dict) else {}
    rows = gpu_rows(state)
    physical_count = hardware.get("count") if isinstance(hardware.get("count"), int) else len(rows)
    counts = gpu_run_counts(runs)
    table = Table(expand=True, box=None, padding=(0, 1), header_style="bold green")
    table.add_column("GPU", style="green")
    table.add_column("型号")
    table.add_column("利用率", justify="right")
    table.add_column("显存", justify="right")
    table.add_column("任务", justify="right")
    for gpu in rows:
        gpu_id = str(gpu.get("id", "?"))
        used = gpu.get("memory_used_mib")
        total = gpu.get("memory_total_mib")
        memory = f"{format_number(used, 0)}/{format_number(total, 0)} MiB" if total is not None else "—"
        utilization = format_number(gpu.get("utilization_percent"), 0)
        table.add_row(gpu_id, str(gpu.get("name") or "unknown")[:18], utilization + "%", memory, str(counts.get(gpu_id, 0)))
    if not rows:
        table.add_row("—", "未发现物理 GPU", "—", "—", "0")
    error = hardware.get("error")
    title = f"物理 GPU · {physical_count} 张"
    if error:
        title += " · 探测提示"
    body = Group(table, Text(str(error), style="yellow") if error else Text("硬件数据每 2 秒自动刷新", style="dim"))
    return Panel(body, title=title, border_style="green")


def build_view(
    state: Dict[str, Any],
    selected_id: Optional[str] = None,
    stale_after: float = 180.0,
    ascii_only: bool = False,
    error: Optional[str] = None,
) -> Any:
    if not RICH_AVAILABLE:
        return "Rich is not installed; run: python -m pip install -e '.[console]'"
    runs = effective_runs(state)
    if selected_id is None:
        selected_id = state.get("active_run_id") or (str(runs[0].get("run_id")) if runs else None)
    selected = next((run for run in runs if str(run.get("run_id")) == str(selected_id)), None)
    hardware = state.get("hardware") if isinstance(state.get("hardware"), dict) else {}
    physical_count = hardware.get("count", len(gpu_rows(state)))
    header = Text()
    header.append("炼丹训练监控", style="bold magenta")
    header.append(f"   模型任务 {len(runs)}   物理 GPU {physical_count}", style="cyan")
    if error:
        header.append(f"   连接异常：{error}", style="bold red")

    layout = Layout(name="root")
    layout.split_column(Layout(header, name="header", size=2), Layout(name="body"), Layout(name="footer", size=2))
    layout["body"].split_row(Layout(name="main", ratio=3), Layout(name="gpu", ratio=2))
    layout["main"].split_column(
        Layout(render_run_table(runs, selected_id, stale_after), name="runs", ratio=2),
        Layout(name="workbench", ratio=8),
    )
    layout["workbench"].split_row(Layout(name="run_detail", ratio=3), Layout(name="mentor", ratio=2))
    layout["run_detail"].split_column(
        Layout(render_detail(selected, stale_after, ascii_only), name="detail", ratio=2),
        Layout(render_alchemy_slots(state, runs, selected_id, ascii_only), name="alchemy", ratio=3),
    )
    layout["mentor"].update(render_mentor(runs, state.get("active_run_id"), stale_after, ascii_only))
    layout["gpu"].update(render_gpu_panel(state, runs))
    footer = "Q 退出   R 刷新   1-9 选择丹炉   +/- 调整历史曲线   A 切换 ASCII"
    if not ascii_only:
        footer += "   建议使用 Windows Terminal 获得完整像素字符效果"
    layout["footer"].update(Text(footer, style="dim"))
    return layout


class MonitorClient:
    def __init__(self, url: str, token: str, timeout: float = 5.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def fetch(self, history_limit: int) -> Dict[str, Any]:
        params = urlencode({"history_limit": max(0, min(500, int(history_limit)))})
        endpoint = f"{self.url}/api/status?{params}"
        headers = {"X-Monitor-Token": self.token} if self.token else {}
        if requests is not None:
            response = requests.get(endpoint, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        else:
            request = Request(endpoint, headers=headers, method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("server returned an invalid status payload")
        return payload


class KeyReader:
    def __enter__(self) -> "KeyReader":
        self._old = None
        if os.name == "nt":
            return self
        if sys.stdin.isatty():
            import termios
            import tty

            self._old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *_: Any) -> None:
        if self._old is not None:
            import termios

            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old)

    def read(self) -> Optional[str]:
        if os.name == "nt":
            import msvcrt

            if not msvcrt.kbhit():
                return None
            key = msvcrt.getwch()
            if key in {"\x00", "\xe0"} and msvcrt.kbhit():
                msvcrt.getwch()
            return key
        if not sys.stdin.isatty():
            return None
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        return sys.stdin.read(1) if ready else None


def run_console(
    *,
    url: str,
    token: str,
    interval: float = 2.0,
    history_limit: int = 120,
    selected_id: Optional[str] = None,
    stale_after: float = 180.0,
    once: bool = False,
    ascii_only: bool = False,
) -> int:
    if not RICH_AVAILABLE:
        print("console mode requires Rich; install with: python -m pip install -e '.[console]'")
        return 2

    client = MonitorClient(url, token)
    console = Console(highlight=False)
    state: Dict[str, Any] = {"runs": [], "hardware": {"count": 0, "gpus": []}}
    error: Optional[str] = None
    if once:
        try:
            state = client.fetch(history_limit)
        except Exception as exc:
            error = str(exc)
        console.print(build_view(state, selected_id, stale_after, ascii_only, error))
        return 0 if error is None else 1

    current_limit = max(20, min(500, history_limit))
    try:
        with KeyReader() as keys:
            with Live(
                build_view(state, selected_id, stale_after, ascii_only, error),
                screen=True,
                refresh_per_second=4,
                console=console,
            ) as live:
                while True:
                    try:
                        state = client.fetch(current_limit)
                        error = None
                    except Exception as exc:
                        error = str(exc)

                    runs = effective_runs(state)
                    if selected_id and not any(str(run.get("run_id")) == str(selected_id) for run in runs):
                        selected_id = None
                    if selected_id is None:
                        selected_id = state.get("active_run_id") or (str(runs[0].get("run_id")) if runs else None)
                    live.update(build_view(state, selected_id, stale_after, ascii_only, error), refresh=True)

                    deadline = time.monotonic() + max(0.2, interval)
                    while time.monotonic() < deadline:
                        key = keys.read()
                        if key:
                            lowered = key.lower()
                            if lowered == "q" or key == "\x1b":
                                return 0
                            if lowered == "r":
                                break
                            if lowered == "a":
                                ascii_only = not ascii_only
                                live.update(build_view(state, selected_id, stale_after, ascii_only, error), refresh=True)
                            elif key in "+=":
                                current_limit = min(500, current_limit + 40)
                            elif key == "-":
                                current_limit = max(20, current_limit - 40)
                            elif key.isdigit() and key != "0":
                                index = int(key) - 1
                                if index < len(runs):
                                    selected_id = str(runs[index].get("run_id"))
                                    live.update(build_view(state, selected_id, stale_after, ascii_only, error), refresh=True)
                        time.sleep(0.05)
    except KeyboardInterrupt:
        return 0
    return 0
