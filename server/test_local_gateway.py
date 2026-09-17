import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from local_gateway import LocalGateway, is_loopback_bind


def _request(url, token=None, method="GET"):
    headers = {}
    if token is not None:
        headers["X-Monitor-Token"] = token
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


def test_local_gateway_auth_health_and_read_only_snapshot():
    snapshot = {
        "status": "training",
        "history": [{"epoch": index} for index in range(4)],
        "runs": [
            {
                "run_id": "unit1",
                "history": [{"epoch": index} for index in range(3)],
            },
        ],
        "hardware": {"count": 1, "gpus": [{"id": "0"}]},
    }
    gateway = LocalGateway(bind="127.0.0.1", port=0, token="test-token",
                           snapshot_provider=lambda: snapshot)
    gateway.start()
    base = f"http://127.0.0.1:{gateway.port}"
    try:
        status, body = _request(base + "/api/health", token="test-token")
        assert status == 200
        assert body == {"ok": True, "source": "desktop-local"}

        status, body = _request(base + "/api/status?history_limit=1")
        assert status == 401
        assert "token" in body["error"]

        status, body = _request(base + "/api/status?history_limit=1", token="test-token")
        assert status == 200
        assert body["source"] == "desktop-local"
        assert len(body["history"]) == 1
        assert len(body["runs"][0]["history"]) == 1
        assert body["hardware"]["gpus"][0]["id"] == "0"
        assert len(snapshot["history"]) == 4

        status, body = _request(base + "/api/status", token="test-token", method="POST")
        assert status == 405
        assert body["error"] == "read-only local monitor"
    finally:
        gateway.stop()


def test_token_rotation_revokes_old_token_and_persists_new_token():
    with tempfile.TemporaryDirectory() as directory:
        token_file = Path(directory) / "monitor.local.token"
        gateway = LocalGateway(bind="127.0.0.1", port=0, token="old-token",
                               token_file=str(token_file), snapshot_provider=lambda: {})
        gateway.start()
        base = f"http://127.0.0.1:{gateway.port}"
        try:
            new_token = gateway.rotate_token()
            assert new_token != "old-token"
            assert token_file.read_text(encoding="utf-8").strip() == new_token

            status, _ = _request(base + "/api/health", token="old-token")
            assert status == 401
            status, body = _request(base + "/api/health", token=new_token)
            assert status == 200
            assert body["ok"] is True
        finally:
            gateway.stop()


def test_loopback_gateway_only_advertises_loopback_url():
    assert is_loopback_bind("127.0.0.1")
    assert is_loopback_bind("localhost")
    assert not is_loopback_bind("0.0.0.0")
    gateway = LocalGateway(bind="127.0.0.1", port=0, token="test-token")
    gateway.start()
    try:
        assert gateway.access_urls() == [f"http://127.0.0.1:{gateway.port}"]
    finally:
        gateway.stop()
