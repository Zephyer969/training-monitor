import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor_config import load_desktop_config


class MonitorConfigTests(unittest.TestCase):
    def test_missing_file_keeps_dependency_free_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=True):
                with patch("monitor_config.Path.cwd", return_value=Path(directory)):
                    with patch("monitor_config._project_root", return_value=Path(directory)):
                        config = load_desktop_config()
        self.assertEqual(config["ssh"], "")
        self.assertEqual(config["remote_python"], "auto")
        self.assertEqual(config["interval"], 2.0)
        self.assertEqual(config["log_roots"], ())
        self.assertEqual(config["local_bind"], "0.0.0.0")
        self.assertEqual(config["local_port"], 8765)
        self.assertEqual(config["local_token"], "")
        self.assertFalse(config["cloudflare_enabled"])
        self.assertEqual(config["cloudflared_path"], "")

    def test_file_and_environment_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.config.json"
            path.write_text(json.dumps({
                "ssh": "file@host",
                "remote_python": "/opt/conda/bin/python",
                "interval": 4,
                "log_roots": ["/data/work_dirs"],
                "local_bind": "127.0.0.1",
                "local_port": 9876,
                "local_token": "phone-token",
                "cloudflare_enabled": True,
                "cloudflared_path": "tools/cloudflared.exe",
            }), encoding="utf-8")
            with patch.dict(os.environ, {"TRAINING_MONITOR_SSH": "env@host"}, clear=True):
                config = load_desktop_config(str(path))
        self.assertEqual(config["ssh"], "env@host")
        self.assertEqual(config["remote_python"], "/opt/conda/bin/python")
        self.assertEqual(config["interval"], 4.0)
        self.assertEqual(config["log_roots"], ("/data/work_dirs",))
        self.assertEqual(config["local_bind"], "127.0.0.1")
        self.assertEqual(config["local_port"], 9876)
        self.assertEqual(config["local_token"], "phone-token")
        self.assertTrue(config["cloudflare_enabled"])
        self.assertEqual(config["cloudflared_path"], "tools/cloudflared.exe")

    def test_invalid_json_and_interval_are_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON"):
                load_desktop_config(str(path))
            path.write_text(json.dumps({"interval": "fast"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "interval"):
                load_desktop_config(str(path))

    def test_cloudflare_enabled_rejects_ambiguous_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.config.json"
            path.write_text(json.dumps({"cloudflare_enabled": "sometimes"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cloudflare_enabled"):
                load_desktop_config(str(path))


if __name__ == "__main__":
    unittest.main()
