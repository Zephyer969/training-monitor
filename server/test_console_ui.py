from datetime import datetime, timedelta

from console_ui import effective_runs, format_number, gpu_slot_rows, phase_for, progress_percent, sparkline


def test_console_uses_dynamic_runs_and_progress() -> None:
    state = {
        "active_run_id": "model-b",
        "runs": [
            {"run_id": "model-a", "epoch": 2, "total_epochs": 10, "status": "training"},
            {"run_id": "model-b", "epoch": 5, "total_epochs": 10, "status": "training"},
        ],
    }

    runs = effective_runs(state)

    assert len(runs) == 2
    assert progress_percent(runs[1]) == 50.0


def test_console_marks_silent_training_as_stalled() -> None:
    now = datetime.now()
    run = {
        "status": "training",
        "phase": "training",
        "updated_at": (now - timedelta(minutes=5)).isoformat(),
    }

    assert phase_for(run, stale_after=60, now=now) == "stalled"


def test_console_accepts_legacy_root_run_shape() -> None:
    state = {"run_id": "legacy", "status": "training", "epoch": 1, "total_epochs": 4}

    assert [run["run_id"] for run in effective_runs(state)] == ["legacy"]
    assert sparkline([0.4, 0.3, 0.2], ascii_only=True)
    assert format_number(1200, 0) == "1200"


def test_gpu_slots_follow_physical_gpu_count() -> None:
    state = {"hardware": {"count": 3, "gpus": []}}

    assert [row["id"] for row in gpu_slot_rows(state)] == ["0", "1", "2"]
