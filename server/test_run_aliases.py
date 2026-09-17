from run_aliases import RunAliasStore


def test_aliases_and_dismissals_persist(tmp_path):
    path = tmp_path / "monitor.names.json"
    store = RunAliasStore(str(path))
    store.set("/runs/unit", "unit1")
    store.dismiss("/runs/unit")
    assert store.save()

    restored = RunAliasStore(str(path))
    assert restored.get("/runs/unit", "原名") == "unit1"
    assert restored.is_dismissed("/runs/unit")


def test_clearing_alias_and_restoring_run(tmp_path):
    store = RunAliasStore(str(tmp_path / "monitor.names.json"))
    store.set("run-a", "unit1")
    store.set("run-a", "")
    store.dismiss("run-a")
    store.restore("run-a")
    assert store.get("run-a", "run-a") == "run-a"
    assert not store.is_dismissed("run-a")
