from pathlib import Path

from watch_mmseg_log import default_run_id, parse_latest_step


def test_log_watcher_extracts_step_and_concise_run_id(tmp_path: Path) -> None:
    log_path = tmp_path / "upernet" / "20260916_141552" / "20260916_141552.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "2026-09-16 - Epoch(train) [42][384/4096]  loss: 0.3024\n",
        encoding="utf-8",
    )

    assert parse_latest_step(log_path) == (384, 4096)
    assert default_run_id(log_path) == "upernet/20260916_141552"
