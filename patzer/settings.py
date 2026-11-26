"""Per-user settings, stored outside the project so personal paths never end up in git."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

SETTINGS_PATH = Path.home() / ".patzer" / "settings.json"


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def find_stockfish() -> str | None:
    """Look for Stockfish: $STOCKFISH_PATH, then the saved setting, then PATH."""
    candidates = [os.environ.get("STOCKFISH_PATH"),
                  load_settings().get("stockfish_path"),
                  shutil.which("stockfish")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def remember_stockfish(path: str) -> None:
    settings = load_settings()
    settings["stockfish_path"] = str(path)
    save_settings(settings)
