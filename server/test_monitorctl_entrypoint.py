import unittest
from argparse import Namespace
from unittest.mock import patch

import monitorctl_py


class TrainMotEntrypointTests(unittest.TestCase):
    def test_explicit_target_is_forwarded_to_desktop(self):
        captured = {}

        class FakeParser:
            def parse_args(self, values):
                captured["values"] = values
                return Namespace(func=lambda args: captured.setdefault("args", args))

        with patch.object(monitorctl_py, "setup_parser", return_value=FakeParser()):
            monitorctl_py.train_mot_main(["user@server", "--interval", "5"])

        self.assertEqual(
            captured["values"],
            ["desktop", "--ssh", "user@server", "--interval", "5"],
        )

    def test_target_is_required(self):
        with self.assertRaises(SystemExit):
            monitorctl_py.train_mot_main(["--interval", "5"])

    def test_ssh_option_cannot_override_explicit_target(self):
        with self.assertRaises(SystemExit):
            monitorctl_py.train_mot_main(["user@server", "--ssh", "other@server"])


if __name__ == "__main__":
    unittest.main()
