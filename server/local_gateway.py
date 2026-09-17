"""Read-only HTTP relay from the desktop monitor to phone clients.

The desktop process owns the SSH collector and the local display-name state.
This relay exposes only the latest desktop snapshot, so a phone never needs
the training server address, SSH credentials, or a second collector.
"""

from __future__ import annotations

from copy import deepcopy
import hmac
import ipaddress
import json
import os
import secrets
import socket
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlsplit


DEFAULT_LOCAL_BIND = "0.0.0.0"
DEFAULT_LOCAL_PORT = 8765
DEFAULT_LOCAL_TOKEN_FILE = "monitor.local.token"
MAX_HISTORY = 500


def _persist_local_token(path: Path, value: str) -> None:
    """Persist a relay token with a same-directory atomic replace.

    Keeping the temporary file beside the target makes ``os.replace`` atomic
    on the supported desktop platforms and avoids leaving a partially written
    token if the process is interrupted during rotation.
    """

    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(value + "\n")
            temporary = Path(handle.name)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(str(temporary), str(path))
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def load_or_create_local_token(configured: str = "", token_file: Optional[str] = None) -> str:
    """Return a configured token or persist a random local relay token."""

    value = str(configured or "").strip()
    if value:
        return value

    path = Path(token_file or DEFAULT_LOCAL_TOKEN_FILE).expanduser()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing

    value = secrets.token_urlsafe(24)
    _persist_local_token(path, value)
    return value


def is_loopback_bind(bind: str) -> bool:
    """Whether a relay bind value accepts connections only from this host."""

    value = str(bind or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def local_ipv4_addresses() -> list[str]:
    """List usable local IPv4 addresses for the phone connection dialog."""

    addresses = set()
    names = {socket.gethostname(), socket.getfqdn()}
    for name in names:
        try:
            infos = socket.getaddrinfo(name, None, socket.AF_INET)
        except OSError:
            continue
        for info in infos:
            address = str(info[4][0])
            if address and not address.startswith("127.") and address != "0.0.0.0":
                addresses.add(address)
    return sorted(addresses)


def _history_limit(path: str) -> int:
    try:
        value = int(parse_qs(urlsplit(path).query).get("history_limit", [120])[0])
    except (TypeError, ValueError):
        value = 120
    return max(0, min(MAX_HISTORY, value))


def trim_snapshot(snapshot: Dict[str, Any], history_limit: int) -> Dict[str, Any]:
    """Trim a copied desktop snapshot without mutating the GUI state."""

    payload = deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    if not isinstance(payload.get("runs"), list):
        payload["runs"] = []

    if history_limit:
        payload["history"] = list(payload.get("history") or [])[-history_limit:]
    else:
        payload["history"] = []
    for run in payload["runs"]:
        if not isinstance(run, dict):
            continue
        run["history"] = (list(run.get("history") or [])[-history_limit:]
                           if history_limit else [])
    return payload


class _RelayServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class LocalGateway:
    """Small authenticated read-only relay bound to the desktop machine."""

    def __init__(
        self,
        bind: str = DEFAULT_LOCAL_BIND,
        port: int = DEFAULT_LOCAL_PORT,
        token: str = "",
        token_file: Optional[str] = None,
        snapshot_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.bind = str(bind or DEFAULT_LOCAL_BIND).strip()
        self._token = str(token or "").strip()
        self.token_file = Path(token_file).expanduser() if token_file else None
        self._token_lock = threading.RLock()
        self.snapshot_provider = snapshot_provider or (lambda: {})
        self._thread: Optional[threading.Thread] = None
        self._server = self._make_server(int(port))
        self.port = int(self._server.server_address[1])

    @property
    def token(self) -> str:
        with self._token_lock:
            return self._token

    def rotate_token(self) -> str:
        """Revoke the current phone token and return a newly generated one.

        The in-memory token is changed only after the optional persistence has
        succeeded, so a filesystem failure never leaves the relay in a state
        that cannot be recovered after a restart.
        """

        value = secrets.token_urlsafe(24)
        if self.token_file is not None:
            _persist_local_token(self.token_file, value)
        with self._token_lock:
            self._token = value
        return value

    def _make_server(self, port: int) -> _RelayServer:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "TrainingMonitorLocal/1"

            def log_message(self, *_: Any) -> None:
                return

            def _authorized(self) -> bool:
                presented = self.headers.get("X-Monitor-Token", "")
                token = gateway.token
                return bool(token) and hmac.compare_digest(presented, token)

            def _json(self, status: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "X-Monitor-Token, Content-Type")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler name
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "X-Monitor-Token, Content-Type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
                path = urlsplit(self.path).path.rstrip("/") or "/"
                if path not in {"/api/status", "/api/health"}:
                    self._json(404, {"error": "not found"})
                    return
                if not self._authorized():
                    self._json(401, {"error": "invalid local monitor token"})
                    return
                if path == "/api/health":
                    self._json(200, {"ok": True, "source": "desktop-local"})
                    return
                try:
                    snapshot = gateway.snapshot_provider()
                    payload = trim_snapshot(snapshot, _history_limit(self.path))
                    payload["source"] = "desktop-local"
                    self._json(200, payload)
                except Exception as exc:  # pragma: no cover - defensive relay boundary
                    self._json(503, {"error": "desktop snapshot unavailable", "detail": str(exc)[:160]})

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
                self._json(405, {"error": "read-only local monitor"})

        return _RelayServer((self.bind, port), Handler)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="training-monitor-local-gateway",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None  # type: ignore[assignment]

    def access_urls(self) -> list[str]:
        if is_loopback_bind(self.bind):
            return [f"http://127.0.0.1:{self.port}"]
        try:
            bound_ip = ipaddress.ip_address(self.bind)
        except ValueError:
            bound_ip = None
        if bound_ip is not None and bound_ip.version == 4 and not bound_ip.is_unspecified:
            return [f"http://{self.bind}:{self.port}"]
        addresses = local_ipv4_addresses()
        if not addresses:
            addresses = ["127.0.0.1"]
        return [f"http://{address}:{self.port}" for address in addresses]

    def connection_details(self, public_url: str = "", tunnel_status: str = "") -> str:
        urls = "\n".join(self.access_urls())
        if is_loopback_bind(self.bind):
            local_intro = "本机回环地址（Cloudflare 模式仅供隧道访问）："
        else:
            local_intro = "本地面板地址（选择手机能访问的地址）："
        details = (
            "手机 App 只连接这台电脑的本地同步接口。\n\n"
            f"{local_intro}\n"
            f"{urls}\n\n"
            "本地同步 Token：\n"
            f"{self.token}"
        )
        if public_url:
            details += (
                "\n\n外网手机地址（HTTPS）：\n"
                f"{public_url}\n"
                "手机不在同一网络时使用这个地址。"
            )
        elif tunnel_status and tunnel_status != "未启动":
            details += f"\n\n外网隧道状态：\n{tunnel_status}"
        details += (
            "\n\n不要填写 127.0.0.1、训练服务器地址或 SSH 密码。"
            "电脑面板关闭后，手机同步也会停止。"
        )
        return details
