from desktop_ui import demo_state, effective_gateway_bind, mentor_phase, station_models
from pixel_window import prioritize_runs


def test_cloudflare_forces_desktop_relay_to_loopback():
    assert effective_gateway_bind("0.0.0.0", True) == "127.0.0.1"
    assert effective_gateway_bind("192.168.1.20", True) == "127.0.0.1"
    assert effective_gateway_bind("0.0.0.0", False) == "0.0.0.0"


def test_live_runs_are_displayed_before_terminal_runs_without_losing_retention():
    runs = [
        {"run_id": "finished-first", "status": "finished"},
        {"run_id": "training-a", "status": "training"},
        {"run_id": "validating-b", "status": "training", "phase": "validating"},
        {"run_id": "stopped-last", "status": "stopped"},
    ]
    ordered = prioritize_runs(runs)
    assert [run["run_id"] for run in ordered] == [
        "training-a", "validating-b", "finished-first", "stopped-last"
    ]
    assert {run["run_id"] for run in ordered} == {run["run_id"] for run in runs}


def test_shared_gpu_and_multi_gpu_jobs_remain_visible():
    state = {"hardware": {"count": 3}, "runs": [
        {"run_id": "ddp", "gpu_ids": [0, 1]},
        {"run_id": "shared", "gpu_ids": [0]},
        {"run_id": "cpu", "gpu_ids": []},
        {"run_id": "unknown", "gpu_ids": [9]},
    ]}
    rows = station_models(state)
    assert [[run["run_id"] for run in jobs] for _, jobs in rows] == [
        ["ddp", "shared"], ["ddp"], [], ["cpu", "unknown"]]


def test_mentor_keeps_working_when_another_job_stops():
    assert mentor_phase([{"status": "stopped"}, {"status": "training"}]) == "training"
    assert mentor_phase([{"status": "paused"}]) == "paused"
    assert mentor_phase([]) == "idle"


def test_demo_hardware_changes_do_not_create_fake_models_on_idle_gpus():
    for count in (0, 1, 4, 8):
        state = demo_state(count, 12)
        assert len(station_models(state)) == count
        assert state["hardware"]["source"] == "demo"
    assert demo_state(1, 12, "finished")["runs"][0]["epoch"] == 100
