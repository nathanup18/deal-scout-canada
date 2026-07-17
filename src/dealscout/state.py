"""Per-lane state persisted as JSON files committed back to the repo by CI."""

import json
import pathlib

STATE_DIR = pathlib.Path(__file__).resolve().parents[2] / "state"


def load(name: str) -> dict:
    path = STATE_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save(name: str, data: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))
