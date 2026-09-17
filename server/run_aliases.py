"""Local display-name aliases and manual dismissals for read-only runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional, Set


DEFAULT_ALIAS_FILE = "monitor.names.json"


def _default_path() -> Path:
    configured = os.getenv("TRAINING_MONITOR_NAMES_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / DEFAULT_ALIAS_FILE


class RunAliasStore:
    """Persist friendly labels and hidden terminal runs on the local machine.

    The monitor never sends these values to the training host.  Keeping them
    in a small local JSON file lets a read-only SSH monitor remember the
    operator's labels and manual cleanup choices between restarts.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path).expanduser() if path else _default_path()
        self.aliases: Dict[str, str] = {}
        self.dismissed: Set[str] = set()
        self.load()

    def load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        values = payload.get("aliases", payload)
        if isinstance(values, dict):
            self.aliases = {
                str(key).strip(): str(value).strip()
                for key, value in values.items()
                if str(key).strip() and str(value).strip()
            }
        dismissed = payload.get("dismissed", [])
        if isinstance(dismissed, list):
            self.dismissed = {str(value).strip() for value in dismissed if str(value).strip()}

    def get(self, run_id: object, fallback: str = "") -> str:
        key = str(run_id or "").strip()
        return self.aliases.get(key, "") or fallback

    def set(self, run_id: object, label: str) -> None:
        key = str(run_id or "").strip()
        if not key:
            return
        value = str(label or "").strip()
        if value:
            self.aliases[key] = value
        else:
            self.aliases.pop(key, None)

    def is_dismissed(self, run_id: object) -> bool:
        return str(run_id or "").strip() in self.dismissed

    def dismiss(self, run_id: object) -> None:
        key = str(run_id or "").strip()
        if key:
            self.dismissed.add(key)

    def restore(self, run_id: object) -> None:
        self.dismissed.discard(str(run_id or "").strip())

    def save(self) -> bool:
        payload = {
            "version": 1,
            "aliases": dict(sorted(self.aliases.items())),
            "dismissed": sorted(self.dismissed),
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
            return True
        except OSError:
            try:
                temporary.unlink()
            except OSError:
                pass
            return False
