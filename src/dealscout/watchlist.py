"""Director-pedigree watchlist: config names + Airtable founder names, with
fuzzy matching (accent folding, initials). The agent adjudicates borderline
matches downstream, so borderline hits are flagged, not dropped.
"""

import logging
import pathlib

import yaml

from .models import fold

log = logging.getLogger("dealscout")

CONFIG = pathlib.Path(__file__).resolve().parents[2] / "config" / "watchlist.yaml"


class Watchlist:
    def __init__(self, airtable_founders: list[str] | None = None):
        data = yaml.safe_load(CONFIG.read_text()) or {}
        self.people = {}  # folded full name -> display info
        for p in data.get("people", []):
            self.people[fold(p["name"])] = f"{p['name']} — {p.get('affiliation', '')}"
        for name in airtable_founders or []:
            key = fold(name)
            self.people.setdefault(key, f"{name} — prior Deal Scout signal")
        # index: folded last name -> [(folded full, display)]
        self.by_last: dict[str, list[tuple[str, str]]] = {}
        for full, display in self.people.items():
            parts = full.split()
            if len(parts) >= 2:
                self.by_last.setdefault(parts[-1], []).append((full, display))
        log.info("watchlist: %d names", len(self.people))

    def match(self, first: str, last: str) -> tuple[str, str] | None:
        """Returns (display, confidence) — confidence 'exact' or 'borderline'."""
        full = fold(f"{first} {last}")
        if full in self.people:
            return self.people[full], "exact"
        candidates = self.by_last.get(fold(last), [])
        f0 = fold(first)[:1]
        for cand_full, display in candidates:
            if f0 and cand_full.split()[0][:1] == f0:
                return display, "borderline"
        return None
