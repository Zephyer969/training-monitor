import argparse
import json
import os
import shlex
from pathlib import Path
import secrets
import shutil
import signal
import site
import socket
import subprocess
import sys
import sysconfig
import time
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

from monitor_config import load_desktop_config


DEFAULT_LOG_ROOTS = (
    "/root/mmdetection* /root/mmdetection3d* /root/mmdet3d* /root/mmsegmentation* "
    "/root/mmclassification* /root/mmpretrain* /root/mmselfsup* /root/mmyolo* "
    "/root/mmpose* /root/mmrotate* /root/mmocr* /root/mmaction* /root/mmaction2* "
    "/root/mmagic* /root/mmediting* /root/mmgeneration* /root/mmtracking* /root/mmtrack* "
    "/root/mmrazor* /root/mmhuman3d* /root/mmfewshot* /root/mmdeploy* /root/work_dirs "
    "/root/*/work_dirs /root/autodl-tmp/*/work_dirs /root/workspace/*/work_dirs "
    "/root/autodl-tmp /root/workspace /root/runs"
)


def install_home() -> Path:
    configured = os.getenv("TRAINING_MONITOR_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name != "nt" and os.getuid() == 0 and Path("/root/autodl-tmp").is_dir():
        return Path("/root/autodl-tmp/training-monitor")
    return Path.home() / ".training-monitor"


BASE = install_home()
CONFIG_FILE = BASE / "config.env"
TOKEN_FILE = BASE / "token.txt"
STATE_FILE = BASE / "state.json"
LOG_DIR = BASE / "logs"
BACKEND_PID = BASE / "backend.pid"
WATCHER_PID = BASE / "watcher.pid"


def ensure_base() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BASE, LOG_DIR):
        try:
            path.chmod(0o700)
        except OSError:
            pass


def default_config() -> Dict[str, str]:
    return {
        "PORT": "6006",
        "PUBLIC_URL": "",
        "LOG_ROOTS": DEFAULT_LOG_ROOTS,
        "LOG_TYPE": "auto",
        "AUTO_WATCH": "1",
        "TOTAL_EPOCHS": "0",
        "SCAN_INTERVAL": "10",
        "CORS_ORIGINS": "",
    }


def write_default_config() -> None:
    ensure_base()
    if CONFIG_FILE.exists():
        return
    save_config(default_config())


def read_config() -> Dict[str, str]:
    write_default_config()
    values = default_config()
    for line in CONFIG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def save_config(values: Dict[str, str]) -> None:
    ensure_base()
    text = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    CONFIG_FILE.write_text(text, encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def config_value(key: str, fallback: str = "") -> str:
    return os.getenv(f"TRAINING_MONITOR_{key}", read_config().get(key, fallback))


def http_json_get(url: str, token: str = "", timeout: float = 5.0):
    headers = {"X-Monitor-Token": token} if token else {}
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return int(getattr(response, "status", 200)), payload


def port() -> int:
    return int(config_value("PORT", "6006") or "6006")


def token_init() -> str:
    ensure_base()
    if not TOKEN_FILE.exists() or not TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").strip():
        TOKEN_FILE.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def read_pid(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None
    except OSError:
        return None


def pid_alive(path: Path) -> bool:
    pid = read_pid(path)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_command_contains(path: Path, needle: str) -> bool:
    pid = read_pid(path)
    if pid is None:
        return False
    proc_cmd = Path("/proc") / str(pid) / "cmdline"
    try:
        cmd = proc_cmd.read_text(encoding="utf-8", errors="ignore").replace("\x00", " ")
    except OSError:
        return True
    return needle in cmd


def stop_one(path: Path, name: str, pattern: str = "") -> None:
    pid = read_pid(path)
    if pid is None:
        path.unlink(missing_ok=True)
        return
    if not pid_alive(path):
        path.unlink(missing_ok=True)
        print(f"{name} pid was stale")
        return
    if pattern and not pid_command_contains(path, pattern):
        path.unlink(missing_ok=True)
        print(f"{name} pid was stale")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    path.unlink(missing_ok=True)
    print(f"{name} stopped")


def backend_ready() -> bool:
    try:
        http_json_get(f"http://127.0.0.1:{port()}/api/health", timeout=3)
        return True
    except Exception:
        return False


def backend_running() -> bool:
    return pid_alive(BACKEND_PID) and pid_command_contains(BACKEND_PID, "uvicorn")


def watcher_running() -> bool:
    return pid_alive(WATCHER_PID) and pid_command_contains(WATCHER_PID, "auto_watch")


def spawn(command: List[str], log_path: Path, extra_env: Optional[Dict[str, str]] = None) -> int:
    ensure_base()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    return int(process.pid)


def start(_: argparse.Namespace) -> None:
    cfg = read_config()
    current_token = token_init()
    current_port = int(cfg.get("PORT", "6006") or "6006")

    if backend_running() and backend_ready():
        print(f"server already running, pid={read_pid(BACKEND_PID)}")
    else:
        stop_one(BACKEND_PID, "old server", "uvicorn")
        pid = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(current_port),
            ],
            LOG_DIR / "backend.log",
            {
                "MONITOR_TOKEN": current_token,
                "TRAINING_MONITOR_STATE_FILE": str(STATE_FILE),
                "TRAINING_MONITOR_CORS_ORIGINS": cfg.get("CORS_ORIGINS", ""),
            },
        )
        BACKEND_PID.write_text(str(pid), encoding="utf-8")
        time.sleep(2)
        if backend_ready():
            print(f"server started, pid={pid}, port={current_port}")
        else:
            print(f"server started but health check is not ready yet, pid={pid}, port={current_port}")
            print("run: python3 -m monitorctl_py logs")

    if cfg.get("AUTO_WATCH", "1") == "1":
        auto_watch(argparse.Namespace())


def stop_all(_: argparse.Namespace) -> None:
    stop_one(WATCHER_PID, "watcher", "auto_watch")
    stop_one(BACKEND_PID, "server", "uvicorn")


def restart(args: argparse.Namespace) -> None:
    stop_all(args)
    start(args)


def auto_watch(_: argparse.Namespace) -> None:
    cfg = read_config()
    current_token = token_init()
    if watcher_running():
        print(f"watcher already running, pid={read_pid(WATCHER_PID)}")
        return
    stop_one(WATCHER_PID, "old watcher", "auto_watch")
    roots = cfg.get("LOG_ROOTS", DEFAULT_LOG_ROOTS).split()
    pid = spawn(
        [
            sys.executable,
            "-m",
            "auto_watch",
            "--server-url",
            f"http://127.0.0.1:{cfg.get('PORT', '6006')}",
            "--total-epochs",
            cfg.get("TOTAL_EPOCHS", "0"),
            "--interval",
            cfg.get("SCAN_INTERVAL", "10"),
            "--roots",
            *roots,
        ],
        LOG_DIR / "watcher.log",
        {"MONITOR_TOKEN": current_token},
    )
    WATCHER_PID.write_text(str(pid), encoding="utf-8")
    print("auto training log detection started")


def watch_file(args: argparse.Namespace) -> None:
    path = Path(args.path).expanduser()
    if not path.is_file():
        raise SystemExit(f"file not found: {path}")
    start(args)
    stop_one(WATCHER_PID, "old watcher", "auto_watch")
    current_token = token_init()
    pid = spawn(
        [
            sys.executable,
            "-m",
            "auto_watch",
            "--server-url",
            f"http://127.0.0.1:{port()}",
            "--total-epochs",
            str(args.total_epochs or config_value("TOTAL_EPOCHS", "0")),
            "--interval",
            "5",
            "--roots",
            str(path),
        ],
        LOG_DIR / "watcher.log",
        {"MONITOR_TOKEN": current_token},
    )
    WATCHER_PID.write_text(str(pid), encoding="utf-8")
    print(f"watching: {path}")


def status(_: argparse.Namespace) -> None:
    current_token = token_init()
    try:
        status_code, payload = http_json_get(
            f"http://127.0.0.1:{port()}/api/status",
            token=current_token,
            timeout=5,
        )
        print("HTTP", status_code)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    except Exception as exc:
        print("server unavailable:", exc)
    if STATE_FILE.exists():
        print("local cached state:")
        print(json.dumps(json.loads(STATE_FILE.read_text(encoding="utf-8")), ensure_ascii=False, indent=2))


def console(args: argparse.Namespace) -> None:
    try:
        from console_ui import run_console
    except ImportError as exc:
        raise SystemExit(
            "console mode requires the optional dependency; install with: "
            "python -m pip install -e '.[console]'"
        ) from exc

    url = args.url or f"http://127.0.0.1:{port()}"
    token = args.token
    if not token and url.rstrip("/").lower() in {
        f"http://127.0.0.1:{port()}".lower(),
        f"http://localhost:{port()}".lower(),
    }:
        token = token_init()
    raise SystemExit(
        run_console(
            url=url,
            token=token,
            interval=args.interval,
            history_limit=args.history_limit,
            selected_id=args.run_id,
            stale_after=args.stale_after,
            once=args.once,
            ascii_only=args.ascii,
        )
    )


def desktop(args: argparse.Namespace) -> None:
    try:
        from desktop_ui import run_desktop
    except ImportError as exc:
        raise SystemExit(
            "桌面模式需要 Pillow 和 Tk。源码直连模式请先运行: "
            "py -3 -m pip install 'pillow>=10.0'\n" + str(exc)
        ) from exc
    try:
        desktop_config = load_desktop_config(args.config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    url = args.url or desktop_config.get("url", "")
    interval = args.interval if args.interval is not None else desktop_config["interval"]
    ssh = args.ssh if args.ssh is not None else desktop_config["ssh"]
    remote_python = args.remote_python or desktop_config["remote_python"]
    log_roots = tuple(args.log_root) if args.log_root is not None else desktop_config["log_roots"]
    names_path = args.names_file or desktop_config.get("names_file") or None
    local_bind = args.local_bind if args.local_bind is not None else desktop_config["local_bind"]
    local_port = args.local_port if args.local_port is not None else desktop_config["local_port"]
    local_token = args.local_token if args.local_token is not None else desktop_config["local_token"]
    local_token_file = args.local_token_file if args.local_token_file is not None else desktop_config["local_token_file"]
    cloudflare_enabled = (args.cloudflare if args.cloudflare is not None
                          else desktop_config.get("cloudflare_enabled", False))
    cloudflared_path = (args.cloudflared_path if args.cloudflared_path is not None
                        else desktop_config.get("cloudflared_path", ""))
    if local_token_file and not os.path.isabs(os.path.expanduser(local_token_file)):
        config_path = desktop_config.get("config_path")
        base_dir = Path(config_path).expanduser().parent if config_path else Path.cwd()
        local_token_file = str(base_dir / local_token_file)
    if not args.demo and not url:
        if not ssh:
            raise SystemExit(
                "未配置训练服务器。请复制 monitor.config.example.json 为 "
                "monitor.config.json，并填写 ssh；或运行 desktop --ssh user@host"
            )
        from direct_monitor import DirectClient
        client = DirectClient(host=ssh, python=remote_python, interval=interval, roots=log_roots)
        run_desktop('', '', interval=interval, client=client, names_path=names_path,
                    local_bind=local_bind, local_port=local_port, local_token=local_token,
                    local_token_file=local_token_file,
                    cloudflare_enabled=cloudflare_enabled, cloudflared_path=cloudflared_path,
                    local_gateway_enabled=not args.no_local_gateway)
        return
    token = args.token
    if not args.demo and not token and url.rstrip("/") in {
        f"http://127.0.0.1:{port()}", f"http://localhost:{port()}"
    }:
        token = token_init()
    run_desktop(url, token, demo=args.demo, gpu_count=args.gpus, interval=interval,
                names_path=names_path, local_bind=local_bind, local_port=local_port,
                local_token=local_token, local_token_file=local_token_file,
                cloudflare_enabled=cloudflare_enabled, cloudflared_path=cloudflared_path,
                local_gateway_enabled=not args.no_local_gateway)


def detect_public_url() -> str:
    cfg = read_config()
    if cfg.get("PUBLIC_URL"):
        return cfg["PUBLIC_URL"]
    autodl_key = f"AutoDLService{cfg.get('PORT', '6006')}URL"
    autodl_url = os.getenv(autodl_key) or os.getenv("AutoDLServiceURL")
    if autodl_url:
        return autodl_url
    try:
        ip = subprocess.check_output(
            ["hostname", "-I"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).split()[0]
        return f"http://{ip}:{cfg.get('PORT', '6006')}"
    except Exception:
        try:
            return f"http://{socket.gethostbyname(socket.gethostname())}:{cfg.get('PORT', '6006')}"
        except Exception:
            return f"http://SERVER_IP:{cfg.get('PORT', '6006')}"


def connection(_: argparse.Namespace) -> None:
    print(f"server port: {port()}")
    print(f"backend url: {detect_public_url()}")
    print(f"access token: {token_init()}")


def rotate_token(args: argparse.Namespace) -> None:
    ensure_base()
    TOKEN_FILE.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
    print("token rotated")
    restart(args)
    connection(args)


def config_cmd(args: argparse.Namespace) -> None:
    cfg = read_config()
    if args.config_action == "show":
        print(CONFIG_FILE.read_text(encoding="utf-8"), end="")
    elif args.config_action == "path":
        print(CONFIG_FILE)
    elif args.config_action == "set":
        cfg[args.key] = args.value
        save_config(cfg)
        print(f"saved {args.key}")


def prompt_value(label: str, current: str) -> str:
    value = input(f"{label} [{current}]: ").strip()
    return value or current


def setup(_: argparse.Namespace) -> None:
    cfg = read_config()
    cfg["PORT"] = prompt_value("Port", cfg.get("PORT", "6006"))
    cfg["PUBLIC_URL"] = prompt_value("Public URL", cfg.get("PUBLIC_URL") or detect_public_url())
    cfg["LOG_ROOTS"] = prompt_value("Log roots", cfg.get("LOG_ROOTS", DEFAULT_LOG_ROOTS))
    cfg["LOG_TYPE"] = prompt_value("Log type auto/openmmlab/yolo", cfg.get("LOG_TYPE", "auto"))
    cfg["AUTO_WATCH"] = prompt_value("Auto watch 1/0", cfg.get("AUTO_WATCH", "1"))
    cfg["CORS_ORIGINS"] = prompt_value("CORS origins, usually empty", cfg.get("CORS_ORIGINS", ""))
    save_config(cfg)
    print(f"saved: {CONFIG_FILE}")
    connection(_)


def logs(_: argparse.Namespace) -> None:
    for label, path in (("backend log", LOG_DIR / "backend.log"), ("watcher log", LOG_DIR / "watcher.log")):
        print(f"{label}: {path}")
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-80:]
            print("\n".join(lines))
        print()


def diagnose(_: argparse.Namespace) -> None:
    cfg = read_config()
    command = [
        sys.executable,
        "-m",
        "auto_watch",
        "--server-url",
        f"http://127.0.0.1:{cfg.get('PORT', '6006')}",
        "--total-epochs",
        cfg.get("TOTAL_EPOCHS", "0"),
        "--roots",
        *cfg.get("LOG_ROOTS", DEFAULT_LOG_ROOTS).split(),
        "--once",
    ]
    raise SystemExit(subprocess.call(command, env={**os.environ, "MONITOR_TOKEN": token_init()}))


def user_bin_dir() -> Path:
    return Path(site.USER_BASE) / ("Scripts" if os.name == "nt" else "bin")


def shell_profiles() -> List[Path]:
    if os.name == "nt":
        return []
    return [
        Path.home() / ".bashrc",
        Path.home() / ".profile",
        Path.home() / ".bash_profile",
        Path.home() / ".zshrc",
    ]


def path_has_user_bin() -> bool:
    user_bin = os.path.normcase(str(user_bin_dir()))
    scripts_dir = os.path.normcase(str(python_scripts_dir()))
    path_dirs = os.getenv("PATH", "").split(os.pathsep)
    if os.name == "nt":
        path_dirs += windows_user_path().split(os.pathsep)
    normalized = {os.path.normcase(path) for path in path_dirs}
    return (
        user_bin in normalized
        or scripts_dir in normalized
        or os.path.normcase(str(Path.home() / "bin")) in normalized
    )


def python_scripts_dir() -> Path:
    configured = sysconfig.get_path("scripts")
    if configured:
        return Path(configured)
    return user_bin_dir()


def windows_user_path() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
    except OSError:
        return ""


def ensure_windows_path() -> List[Path]:
    if os.name != "nt":
        return []

    scripts_dir = python_scripts_dir()
    current_entries = os.environ.get("PATH", "").split(os.pathsep)
    user_entries = windows_user_path().split(os.pathsep)
    normalized = {os.path.normcase(entry) for entry in current_entries + user_entries if entry}
    if os.path.normcase(str(scripts_dir)) in normalized:
        return []

    try:
        import winreg

        new_entries = [entry for entry in user_entries if entry]
        new_entries.append(str(scripts_dir))
        new_value = os.pathsep.join(new_entries)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_value)
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(scripts_dir)
        return [scripts_dir]
    except OSError:
        return []


def launcher_paths() -> List[Path]:
    paths = [user_bin_dir() / "training-monitor"]
    home_bin = Path.home() / "bin" / "training-monitor"
    if home_bin not in paths:
        paths.append(home_bin)
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        paths.append(Path("/usr/local/bin/training-monitor"))
    return paths


def launcher_script() -> str:
    return (
        "#!/usr/bin/env bash\n"
        f'exec {shlex.quote(sys.executable)} -m monitorctl_py "$@"\n'
    )


def ensure_launcher_files() -> List[Path]:
    written: List[Path] = []
    content = launcher_script()
    for path in launcher_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            current = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
            if current != content:
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)
                written.append(path)
        except OSError:
            continue
    return written


def write_shell_profile_exports() -> List[Path]:
    if os.name == "nt":
        return []

    line = 'export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"'
    marker = "training-monitor/bin-path"
    changed: List[Path] = []
    profiles = shell_profiles()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        profiles = [Path("/etc/profile.d/training-monitor.sh")] + profiles

    for profile in profiles:
        try:
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.touch(exist_ok=True)
            text = profile.read_text(encoding="utf-8", errors="ignore")
            if marker not in text:
                with profile.open("a", encoding="utf-8") as file:
                    file.write(f"\n# {marker}\n{line}\n")
                changed.append(profile)
        except OSError:
            continue
    return changed


def ensure_command_access() -> None:
    if os.name == "nt":
        ensure_windows_path()
        return
    if os.getenv("TRAINING_MONITOR_SKIP_PATH_BOOTSTRAP") == "1":
        return
    if shutil.which("training-monitor"):
        return

    written = ensure_launcher_files()
    changed_profiles = write_shell_profile_exports()
    if not written and not changed_profiles:
        return

    print("training-monitor command is not in the current PATH yet.")
    if written:
        print("created launcher:")
        for path in written:
            print(f"- {path}")
    if changed_profiles:
        print("updated shell profiles:")
        for profile in changed_profiles:
            print(f"- {profile}")
    print("open a new shell, or run:")
    print(f'export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"')


def fix_path(_: argparse.Namespace) -> None:
    user_bin = user_bin_dir()
    user_bin.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        changed = ensure_windows_path()
        scripts_dir = python_scripts_dir()
        print(f"script directory: {scripts_dir}")
        if changed:
            print("updated user PATH. Open a new terminal, then run: training-monitor status")
        elif path_has_user_bin():
            print("PATH is already configured.")
        else:
            print("Could not update PATH automatically. Add this directory to PATH manually.")
        return

    ensure_launcher_files()
    changed = write_shell_profile_exports()

    print(f"script directory: {user_bin}")
    if changed:
        print("updated shell profiles:")
        for profile in changed:
            print(f"- {profile}")
        print('run now: export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"')
        print("or reopen your terminal.")
    elif path_has_user_bin():
        print("PATH is already configured.")
    else:
        print("shell profile already contains PATH setting, but current terminal has not loaded it.")
        print('run now: export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"')


def doctor(_: argparse.Namespace) -> None:
    command_path = shutil.which("training-monitor")
    user_bin = user_bin_dir()
    home_bin = Path.home() / "bin"
    print("Training Monitor diagnosis")
    print(f"python: {sys.executable}")
    print(f"python version: {sys.version.split()[0]}")
    print(f"install home: {BASE}")
    print(f"script directory: {user_bin}")
    if os.name == "nt":
        print(f"python scripts directory: {python_scripts_dir()}")
    print(f"fallback directory: {home_bin}")
    print(f"training-monitor command: {command_path or 'not found in PATH'}")
    print(f"script directory in PATH: {'yes' if path_has_user_bin() else 'no'}")
    print(f"config file: {CONFIG_FILE}")
    print()
    if not command_path:
        print("recommended fix:")
        if os.name == "nt":
            print("py -m monitorctl_py fix-path")
            print("then open a new terminal")
        else:
            print("python3 -m monitorctl_py fix-path")
            print('export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"')
    print("module command always works after pip install:")
    print("python3 -m monitorctl_py connection")


def setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="training-monitor")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("start").set_defaults(func=start)
    sub.add_parser("stop").set_defaults(func=stop_all)
    sub.add_parser("restart").set_defaults(func=restart)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("connection").set_defaults(func=connection)
    sub.add_parser("token-init").set_defaults(func=lambda args: print(token_init()))
    sub.add_parser("token").set_defaults(func=lambda args: print(token_init()))
    sub.add_parser("rotate-token").set_defaults(func=rotate_token)
    sub.add_parser("setup").set_defaults(func=setup)
    sub.add_parser("auto-watch").set_defaults(func=auto_watch)
    sub.add_parser("auto-mmseg").set_defaults(func=auto_watch)
    sub.add_parser("diagnose").set_defaults(func=diagnose)
    sub.add_parser("doctor").set_defaults(func=doctor)
    sub.add_parser("fix-path").set_defaults(func=fix_path)
    sub.add_parser("logs").set_defaults(func=logs)

    console_parser = sub.add_parser("console", help="open the dynamic terminal alchemy dashboard")
    console_parser.add_argument("--url", default=os.getenv("TRAINING_MONITOR_URL", ""))
    console_parser.add_argument(
        "--token",
        default=os.getenv("TRAINING_MONITOR_TOKEN", os.getenv("MONITOR_TOKEN", "")),
    )
    console_parser.add_argument("--interval", type=float, default=2.0)
    console_parser.add_argument("--history-limit", type=int, default=120)
    console_parser.add_argument("--run-id", default=None)
    console_parser.add_argument("--stale-after", type=float, default=180.0)
    console_parser.add_argument("--once", action="store_true")
    console_parser.add_argument("--ascii", action="store_true")
    console_parser.set_defaults(func=console)

    desktop_parser = sub.add_parser("desktop", help="open the mentor alchemy desktop window")
    desktop_parser.add_argument("--config", default=None, help="desktop JSON config (default: monitor.config.json)")
    desktop_parser.add_argument("--url", default=None)
    desktop_parser.add_argument("--token", default=os.getenv("TRAINING_MONITOR_TOKEN", os.getenv("MONITOR_TOKEN", "")))
    desktop_parser.add_argument("--demo", action="store_true", help="use clearly labeled simulated data")
    desktop_parser.add_argument("--gpus", type=int, choices=range(33), default=4, help="demo GPU count (0-32)")
    desktop_parser.add_argument("--interval", type=float, default=None)
    desktop_parser.add_argument("--ssh", default=None, help='SSH host or user@host; automatically discover active training logs')
    desktop_parser.add_argument("--remote-python", default=None, help='remote Python executable, or auto (python3/python)')
    desktop_parser.add_argument("--log-root", action='append', default=None, help='optional additional log directory or file')
    desktop_parser.add_argument("--names-file", default=None, help='local JSON file for friendly run names and dismissals')
    desktop_parser.add_argument(
        "--local-bind", default=None,
        help='desktop relay bind address (default: 0.0.0.0; Cloudflare mode forces 127.0.0.1)',
    )
    desktop_parser.add_argument("--local-port", type=int, default=None, help='desktop relay port (default: 8765)')
    desktop_parser.add_argument("--local-token", default=None, help='token for phone clients; blank uses local token file')
    desktop_parser.add_argument("--local-token-file", default=None, help='local file for the generated phone token')
    desktop_parser.add_argument("--no-local-gateway", action="store_true", help='disable the phone relay')
    desktop_parser.add_argument("--cloudflare", dest="cloudflare", action="store_true", default=None,
                                help='start a temporary Cloudflare HTTPS tunnel for the phone relay')
    desktop_parser.add_argument("--no-cloudflare", dest="cloudflare", action="store_false",
                                help='do not start the Cloudflare tunnel')
    desktop_parser.add_argument("--cloudflared-path", default=None,
                                help='optional path to cloudflared/cloudflared.exe')
    desktop_parser.set_defaults(func=desktop)

    watch = sub.add_parser("watch-file")
    watch.add_argument("path")
    watch.add_argument("total_epochs", nargs="?", type=int)
    watch.set_defaults(func=watch_file)

    watch_mmseg = sub.add_parser("watch-mmseg")
    watch_mmseg.add_argument("path")
    watch_mmseg.add_argument("total_epochs", nargs="?", type=int)
    watch_mmseg.set_defaults(func=watch_file)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_action")
    config_sub.add_parser("show").set_defaults(func=config_cmd)
    config_sub.add_parser("path").set_defaults(func=config_cmd)
    config_set = config_sub.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.set_defaults(func=config_cmd)
    return parser


def main() -> None:
    ensure_command_access()
    parser = setup_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
