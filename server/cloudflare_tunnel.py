"""Small optional Cloudflare Quick Tunnel wrapper for the desktop relay.

The desktop monitor remains the owner of SSH collection and local state.  This
module only manages a local ``cloudflared tunnel --url`` child process and
extracts the temporary HTTPS address that Cloudflare prints.  No training
server credentials or remote files are involved.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional


QUICK_TUNNEL_URL = re.compile(
    r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.trycloudflare\.com"
)


def extract_quick_tunnel_url(text: str) -> str:
    """Return the first official Quick Tunnel URL found in one output line."""

    match = QUICK_TUNNEL_URL.search(str(text or ""))
    return match.group(0).rstrip(".,);]>") if match else ""


def build_quick_tunnel_command(executable: str, port: int) -> list[str]:
    """Build the dependency-free command used by the desktop launcher."""

    value = int(port)
    if not 1 <= value <= 65535:
        raise ValueError("Cloudflare Tunnel 目标端口必须是 1 到 65535 之间")
    return [str(executable), "tunnel", "--url", f"http://127.0.0.1:{value}"]


def resolve_cloudflared(configured: str = "") -> str:
    """Find an explicitly configured binary, PATH entry, or bundled local copy."""

    requested = str(configured or "").strip()
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(requested)
        if found:
            return found
        return ""

    found = shutil.which("cloudflared")
    if found:
        return found

    project_root = Path(__file__).resolve().parent.parent
    for candidate in (
        Path.cwd() / "cloudflared.exe",
        Path.cwd() / "tools" / "cloudflared.exe",
        project_root / "cloudflared.exe",
        project_root / "tools" / "cloudflared.exe",
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


class CloudflareQuickTunnel:
    """Manage one temporary HTTPS tunnel to the local monitor gateway."""

    def __init__(
        self,
        port: int,
        executable: str = "",
        on_update: Optional[Callable[["CloudflareQuickTunnel"], None]] = None,
    ) -> None:
        self.port = int(port)
        self.requested_executable = str(executable or "").strip()
        self.on_update = on_update
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._public_url = ""
        self._error = ""
        self._status = "未启动"

    @property
    def public_url(self) -> str:
        with self._lock:
            return self._public_url

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _notify(self) -> None:
        callback = self.on_update
        if callback is None:
            return
        try:
            callback(self)
        except Exception:
            # A UI callback must never terminate the tunnel reader thread.
            return

    def _set_state(
        self,
        *,
        public_url: Optional[str] = None,
        error: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        with self._lock:
            if public_url is not None:
                self._public_url = public_url
            if error is not None:
                self._error = error
            if status is not None:
                self._status = status
        self._notify()

    def start(self) -> bool:
        """Start the tunnel without opening another console window."""

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return True
            self._stop.clear()

        executable = resolve_cloudflared(self.requested_executable)
        if not executable:
            requested = self.requested_executable or "cloudflared"
            self._set_state(
                error=f"未找到 {requested}。请先安装 cloudflared，或在配置中填写 cloudflared_path。",
                status="未启动",
            )
            return False

        try:
            process = subprocess.Popen(
                build_quick_tunnel_command(executable, self.port),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if os.name == "nt" else 0),
            )
        except (OSError, ValueError) as exc:
            self._set_state(
                error=f"cloudflared 启动失败：{type(exc).__name__}",
                status="启动失败",
            )
            return False

        with self._lock:
            self._process = process
            self._public_url = ""
            self._error = ""
            self._status = "正在生成 HTTPS 地址…"
            self._reader = threading.Thread(
                target=self._read_output,
                args=(process,),
                name="training-monitor-cloudflare",
                daemon=True,
            )
            reader = self._reader
        self._notify()
        reader.start()
        return True

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        stream = process.stdout
        if stream is not None:
            try:
                for line in iter(stream.readline, ""):
                    if self._stop.is_set():
                        break
                    public_url = extract_quick_tunnel_url(line)
                    if public_url:
                        self._set_state(
                            public_url=public_url,
                            error="",
                            status="公网 HTTPS 地址已就绪",
                        )
            except (OSError, ValueError):
                # The process may close its pipe while the desktop is exiting.
                pass

        if self._stop.is_set():
            return
        code = process.poll()
        if code is not None and not self.public_url:
            self._set_state(
                error=f"cloudflared 已退出（退出码 {code}）",
                status="启动失败",
            )
        elif code is not None:
            self._set_state(
                public_url="",
                error="公网隧道已停止，请重新启动电脑面板。",
                status="公网隧道已停止",
            )

    def stop(self) -> None:
        """Stop the child process when the desktop window closes."""

        self._stop.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self._set_state(public_url="", status="已停止")
