"""Read-only host hardware discovery for the training monitor.

The monitor runs on the training host, so the host is the source of truth for
the number of physical GPUs.  The terminal client consumes this snapshot over
the existing authenticated status endpoint; it never needs to guess from the
number of active runs.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from datetime import datetime
import io
import os
import shutil
import subprocess
from threading import RLock
import time
from typing import Any, Optional


_CACHE_LOCK = RLock()
_CACHE: Optional[dict[str, Any]] = None
_CACHE_AT = 0.0
_CACHE_SECONDS = max(0.5, float(os.getenv("TRAINING_MONITOR_HARDWARE_CACHE", "2")))


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _number(value: str, as_int: bool = False) -> Optional[float | int]:
    cleaned = str(value).strip().strip("[]")
    if not cleaned or cleaned.lower() in {"n/a", "na", "not supported", "unknown"}:
        return None
    try:
        parsed = float(cleaned)
    except (TypeError, ValueError):
        return None
    return int(parsed) if as_int else parsed


def _empty_snapshot(error: Optional[str] = None) -> dict[str, Any]:
    return {
        "source": "none",
        "count": 0,
        "gpus": [],
        "updated_at": _now_text(),
        "error": error,
    }


def _read_nvidia_smi() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return _empty_snapshot("nvidia-smi was not found on the training host")

    command = [
        executable,
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _empty_snapshot(f"unable to read GPU status: {exc}")

    if completed.returncode != 0:
        detail = (completed.stderr or "nvidia-smi returned a non-zero exit code").strip()
        return _empty_snapshot(detail[:240])

    gpus: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(completed.stdout or "")):
        if len(row) < 7:
            continue
        gpu_id = str(row[0]).strip()
        name = str(row[1]).strip()
        if not gpu_id:
            continue
        gpus.append(
            {
                "id": gpu_id,
                "name": name,
                "utilization_percent": _number(row[2], as_int=True),
                "memory_used_mib": _number(row[3], as_int=True),
                "memory_total_mib": _number(row[4], as_int=True),
                "temperature_c": _number(row[5], as_int=True),
                "power_w": _number(row[6]),
            }
        )

    if not gpus:
        return _empty_snapshot("nvidia-smi returned no GPU rows")
    return {
        "source": "nvidia-smi",
        "count": len(gpus),
        "gpus": gpus,
        "updated_at": _now_text(),
        "error": None,
    }


def hardware_snapshot(force: bool = False) -> dict[str, Any]:
    """Return a short-lived, read-only snapshot of physical GPU hardware."""

    global _CACHE, _CACHE_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force and _CACHE is not None and now - _CACHE_AT < _CACHE_SECONDS:
            return deepcopy(_CACHE)

    if os.getenv("TRAINING_MONITOR_HARDWARE", "1") == "0":
        snapshot = _empty_snapshot("hardware discovery disabled")
    else:
        snapshot = _read_nvidia_smi()

    with _CACHE_LOCK:
        _CACHE = snapshot
        _CACHE_AT = time.monotonic()
        return deepcopy(snapshot)


def reset_hardware_cache() -> None:
    """Clear the cache for tests and explicit host re-discovery."""

    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE = None
        _CACHE_AT = 0.0
