"""Small, dependency-free configuration loader for the desktop monitor.

The desktop client intentionally keeps its configuration separate from the
server's token/config files.  A copied project only needs one local JSON file
containing the SSH destination; credentials remain handled by the normal SSH
prompt or the user's SSH agent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


DEFAULT_INTERVAL = 2.0
DEFAULT_REMOTE_PYTHON = "auto"
DEFAULT_LOCAL_BIND = "0.0.0.0"
DEFAULT_LOCAL_PORT = 8765
DEFAULT_CLOUDFLARE_ENABLED = False
DEFAULT_CLOUDFLARED_PATH = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_paths(explicit: Optional[str]) -> Iterable[Path]:
    if explicit:
        yield Path(explicit).expanduser()
        return
    seen = set()
    values = []
    configured = os.getenv("TRAINING_MONITOR_CONFIG", "").strip()
    if configured:
        values.append(Path(configured).expanduser())
    values.extend((Path.cwd() / "monitor.config.json", _project_root() / "monitor.config.json"))
    for path in values:
        resolved = str(path.absolute())
        if resolved not in seen:
            seen.add(resolved)
            yield path


def _as_roots(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split() if item)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError("log_roots must be a list of paths")


def _as_bool(value: Any, name: str) -> bool:
    """Accept JSON booleans plus friendly environment/config spellings."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on", "是", "开启"}:
        return True
    if text in {"0", "false", "no", "n", "off", "否", "关闭", ""}:
        return False
    raise ValueError(f"{name} 必须是 true 或 false")


def _read_file(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 JSON 格式错误: {path}（第 {exc.lineno} 行）") from exc
    except OSError as exc:
        raise ValueError(f"无法读取配置文件: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件必须是 JSON 对象: {path}")
    return payload


def load_desktop_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load desktop settings, returning safe defaults when no file exists.

    Precedence is command-selected file, ``TRAINING_MONITOR_CONFIG``, the
    current directory, the source checkout, then environment overrides.  The
    function returns plain values so it remains easy to use from the CLI and
    tests without adding a configuration dependency.
    """

    values: Dict[str, Any] = {
        "ssh": "",
        "url": "",
        "remote_python": DEFAULT_REMOTE_PYTHON,
        "interval": DEFAULT_INTERVAL,
        "log_roots": (),
        "names_file": "",
        "local_bind": DEFAULT_LOCAL_BIND,
        "local_port": DEFAULT_LOCAL_PORT,
        "local_token": "",
        "local_token_file": "monitor.local.token",
        "cloudflare_enabled": DEFAULT_CLOUDFLARE_ENABLED,
        "cloudflared_path": DEFAULT_CLOUDFLARED_PATH,
    }
    selected: Optional[Path] = None
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            selected = candidate
            break
    if path and selected is None:
        raise ValueError(f"配置文件不存在: {Path(path).expanduser()}")
    if selected is not None:
        raw = _read_file(selected)
        aliases = {
            "host": "ssh",
            "ssh_host": "ssh",
            "remote_python": "remote_python",
            "python": "remote_python",
            "log_root": "log_roots",
            "log_roots": "log_roots",
            "names_file": "names_file",
            "local_bind": "local_bind",
            "local_host": "local_bind",
            "local_port": "local_port",
            "local_token": "local_token",
            "local_token_file": "local_token_file",
            "cloudflare": "cloudflare_enabled",
            "cloudflare_enabled": "cloudflare_enabled",
            "cloudflared": "cloudflared_path",
            "cloudflared_path": "cloudflared_path",
        }
        for key, value in raw.items():
            normalized = aliases.get(key, key)
            if normalized in values:
                values[normalized] = value
        values["config_path"] = str(selected)

    env_values = {
        "ssh": os.getenv("TRAINING_MONITOR_SSH"),
        "url": os.getenv("TRAINING_MONITOR_URL"),
        "remote_python": os.getenv("TRAINING_MONITOR_REMOTE_PYTHON"),
        "interval": os.getenv("TRAINING_MONITOR_INTERVAL"),
        "log_roots": os.getenv("TRAINING_MONITOR_LOG_ROOTS"),
        "names_file": os.getenv("TRAINING_MONITOR_NAMES_FILE"),
        "local_bind": os.getenv("TRAINING_MONITOR_LOCAL_BIND"),
        "local_port": os.getenv("TRAINING_MONITOR_LOCAL_PORT"),
        "local_token": os.getenv("TRAINING_MONITOR_LOCAL_TOKEN"),
        "local_token_file": os.getenv("TRAINING_MONITOR_LOCAL_TOKEN_FILE"),
        "cloudflare_enabled": os.getenv("TRAINING_MONITOR_CLOUDFLARE_ENABLED"),
        "cloudflared_path": os.getenv("TRAINING_MONITOR_CLOUDFLARED_PATH"),
    }
    for key, value in env_values.items():
        if value not in (None, ""):
            values[key] = value

    values["ssh"] = str(values.get("ssh") or "").strip()
    values["url"] = str(values.get("url") or "").strip()
    values["remote_python"] = str(values.get("remote_python") or DEFAULT_REMOTE_PYTHON).strip()
    if not values["remote_python"]:
        values["remote_python"] = DEFAULT_REMOTE_PYTHON
    try:
        values["interval"] = max(0.5, min(60.0, float(values.get("interval", DEFAULT_INTERVAL))))
    except (TypeError, ValueError) as exc:
        raise ValueError("interval 必须是 0.5 到 60 之间的数字") from exc
    values["log_roots"] = _as_roots(values.get("log_roots"))
    values["names_file"] = str(values.get("names_file") or "").strip()
    values["local_bind"] = str(values.get("local_bind") or DEFAULT_LOCAL_BIND).strip()
    values["local_token"] = str(values.get("local_token") or "").strip()
    values["local_token_file"] = str(values.get("local_token_file") or "monitor.local.token").strip()
    values["cloudflare_enabled"] = _as_bool(
        values.get("cloudflare_enabled", DEFAULT_CLOUDFLARE_ENABLED),
        "cloudflare_enabled",
    )
    values["cloudflared_path"] = str(values.get("cloudflared_path") or DEFAULT_CLOUDFLARED_PATH).strip()
    try:
        values["local_port"] = int(values.get("local_port", DEFAULT_LOCAL_PORT))
    except (TypeError, ValueError) as exc:
        raise ValueError("local_port 必须是 1 到 65535 之间的端口") from exc
    if not 1 <= values["local_port"] <= 65535:
        raise ValueError("local_port 必须是 1 到 65535 之间的端口")
    return values
