from types import SimpleNamespace

import hardware


def test_hardware_snapshot_parses_all_physical_nvidia_gpus(monkeypatch) -> None:
    hardware.reset_hardware_cache()
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "nvidia-smi.exe")
    monkeypatch.setattr(
        hardware.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                "0, NVIDIA RTX A6000, 72, 1000, 49140, 55, 180.5\n"
                "1, NVIDIA RTX A6000, 18, 800, 49140, 49, 120.0\n"
            ),
            stderr="",
        ),
    )

    snapshot = hardware.hardware_snapshot(force=True)

    assert snapshot["source"] == "nvidia-smi"
    assert snapshot["count"] == 2
    assert [gpu["id"] for gpu in snapshot["gpus"]] == ["0", "1"]
    assert snapshot["gpus"][0]["utilization_percent"] == 72
    assert snapshot["gpus"][0]["power_w"] == 180.5


def test_hardware_discovery_can_be_disabled(monkeypatch) -> None:
    hardware.reset_hardware_cache()
    monkeypatch.setenv("TRAINING_MONITOR_HARDWARE", "0")

    snapshot = hardware.hardware_snapshot(force=True)

    assert snapshot["count"] == 0
    assert snapshot["gpus"] == []
    assert snapshot["source"] == "none"
    assert "disabled" in snapshot["error"]

    monkeypatch.delenv("TRAINING_MONITOR_HARDWARE", raising=False)
    hardware.reset_hardware_cache()
