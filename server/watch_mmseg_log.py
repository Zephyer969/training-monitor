import argparse
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from openmmlab_log import (
    choose_primary_metric,
    infer_total_epochs,
    parse_eta_seconds,
    parse_line_metrics,
    parse_openmmlab_history,
)
from training_monitor import TrainingMonitor


EPOCH_STEP_RE = re.compile(
    r"Epoch(?:\([^)]*\))?\s*\[\s*\d+(?:\s*/\s*\d+)?\s*\]"
    r"\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]",
    re.I,
)
ITER_STEP_RE = re.compile(
    r"Iter(?:\([^)]*\))?\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]",
    re.I,
)


def parse_latest(log_path: Path) -> Optional[Tuple[int, float, Optional[int]]]:
    latest = parse_latest_metrics(log_path)
    if latest is None or "mIoU" not in latest[1]:
        return None
    return latest[0], latest[1]["mIoU"], latest[2]


def parse_latest_metrics(log_path: Path) -> Optional[Tuple[int, Dict[str, float], Optional[int], str]]:
    total_epochs, rows = parse_openmmlab_history(log_path, 0)
    del total_epochs
    if not rows:
        return None
    latest = rows[-1]
    epoch = latest[1]
    metrics = latest[4]
    latest_eta = latest[3]
    primary_metric = choose_primary_metric(metrics)
    return epoch, metrics, latest_eta, primary_metric


def parse_mmseg_line_metrics(line: str) -> Dict[str, float]:
    return parse_line_metrics(line)


def parse_latest_step(log_path: Path) -> Optional[Tuple[int, int]]:
    """Read the latest visible step counter without changing the log file."""

    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        match = EPOCH_STEP_RE.search(line) or ITER_STEP_RE.search(line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def default_run_id(log_path: Path) -> str:
    """Use a concise stable experiment name instead of exposing the full path."""

    if log_path.parent.name and log_path.parent.parent.name:
        return f"{log_path.parent.parent.name}/{log_path.parent.name}"
    return log_path.stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--server-url", default="http://127.0.0.1:6006")
    parser.add_argument("--token", default=os.getenv("MONITOR_TOKEN", ""))
    parser.add_argument("--total-epochs", type=int, default=0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--gpu-id", default=os.getenv("TRAINING_MONITOR_GPU_ID", ""))
    args = parser.parse_args()

    log_path = Path(args.log_path)
    total_epochs = infer_total_epochs(log_path, args.total_epochs)
    run_id = args.run_id.strip() or default_run_id(log_path)
    monitor = TrainingMonitor(args.server_url, token=args.token)
    last_sent: Optional[Tuple[int, Dict[str, float], Optional[int]]] = None

    while True:
        latest_metrics = parse_latest_metrics(log_path)
        latest = None
        if latest_metrics is not None:
            epoch, metrics, eta_seconds, primary_metric = latest_metrics
            latest = (epoch, metrics, eta_seconds)
        if latest is not None and latest != last_sent:
            epoch, metrics, eta_seconds = latest
            iou = metrics[primary_metric]
            step_data = parse_latest_step(log_path)
            monitor.log(
                run_id=run_id,
                gpu_id=args.gpu_id or None,
                epoch=epoch,
                total_epochs=total_epochs,
                iou=iou,
                metric_name=primary_metric,
                metrics=metrics,
                eta_seconds=eta_seconds,
                step=step_data[0] if step_data else None,
                total_steps=step_data[1] if step_data else None,
                status="finished" if total_epochs > 0 and epoch >= total_epochs else "training",
            )
            print(
                f"sent run={run_id}, epoch={epoch}/{total_epochs}, "
                f"{primary_metric}={iou:.4f}, eta_seconds={eta_seconds}",
                flush=True,
            )
            last_sent = latest

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
