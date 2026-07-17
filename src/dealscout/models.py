"""Normalized signal row, shared by every lane."""

import re
import unicodedata
from dataclasses import dataclass

LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|incorporee|inc|ltd|ltee|limited|corp|corporation|"
    r"co|company|societe|society|ulc|llp|lp)\b\.?", re.I)


def fold(text: str) -> str:
    """Lowercase + strip accents (décarbon -> decarbon)."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def normalize_name(name: str) -> str:
    """Match the Deal Scout base's name:<...> dedupe convention."""
    s = fold(name)
    s = LEGAL_SUFFIXES.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def domain_of(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", (url or "").strip().lower())
    return m.group(1) if m else ""


@dataclass
class Signal:
    company: str
    source_lane: str          # Grants | New Corps | Cohorts | Regulatory
    signal_type: str          # existing Signal Type select choice
    jurisdiction: str         # Federal | BC | AB | ON | QC | Other
    signal_date: str          # ISO date the signal occurred
    detail: str = ""
    amount: float | None = None
    program: str = ""
    source_url: str = ""
    raw_ref: str = ""
    director_names: str = ""
    founder: str = ""
    location: str = ""
    website: str = ""
    hydrogen: bool = False    # off-thesis, logged anyway, sorts to bottom

    def dedupe_key(self) -> str:
        dom = domain_of(self.website)
        return f"dom:{dom}" if dom else f"name:{normalize_name(self.company)}"
