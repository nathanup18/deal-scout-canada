"""Lane B (federal) — Corporations Canada monthly incorporations.

Discovery: the monthly transactions publication page (stable URL, latest
month) lists every new CBCA certificate as an HTML table: corp number,
name, province, effective date.

Track 1 (director match): pull directors for every new corp via the
Federal Corporation API and match the pedigree watchlist. This surfaces
numbered corps. ~7k corps/month at a 55/min throttle ≈ 2h in CI.
Track 2 (keyword match): climate tokens in the corporation name.

The API key travels as the user_key query parameter (per the ISED API
Store subscription page). NEVER log request URLs — they contain the key.
"""

import datetime as dt
import logging
import os
import pathlib
import re
import time

import yaml

from .. import haiku, state
from ..airtable_client import Airtable
from ..http_util import fetch, page_text, session
from ..models import Signal, fold
from ..watchlist import Watchlist

log = logging.getLogger("dealscout")

MONTHLY_URL = ("https://ised-isde.canada.ca/site/corporations-canada/en/"
               "data-services/monthly-transactions/certificates-incorporation-cbca")
DIRECTORS_URL = "https://ised-isde.api.canada.ca/corporations/api/v2/corporations/{num}/directors"
CORP_SEARCH_URL = "https://ised-isde.canada.ca/cbr-rec/en/search/results?search={num}"
CALLS_PER_MIN = 55  # Public Plan allows 60/min
CONFIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"

PROVINCES = {"BC": "BC", "AB": "AB", "ON": "ON", "QC": "QC"}


def load_keywords() -> dict:
    return yaml.safe_load((CONFIG_DIR / "keywords.yaml").read_text())


def match_name(name: str, kw: dict) -> str | None:
    """Returns the matched token, 'hydrogen' for hydrogen tokens, or None."""
    folded = fold(name)
    words = set(re.split(r"[^a-z0-9]+", folded))
    for token in kw["hydrogen"]:
        if token in folded:
            return "hydrogen"
    for token in kw["substring"]:
        if token in folded:
            return token
    for token in kw["word"]:
        if token in words:
            return token
    return None


def _parse_monthly(html: str) -> tuple[str, list[dict]]:
    """(month label, [{number, name, province, date}]) from the CBCA table."""
    import html as htmllib
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    label = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    corps = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) >= 4 and re.match(r"\d{5,}", cells[0]):
            corps.append({"number": cells[0], "name": cells[1],
                          "province": cells[2], "date": cells[3]})
    return label, corps


class DirectorClient:
    def __init__(self):
        self.key = os.environ.get("CORPCAN_API_KEY")
        if not self.key:
            raise RuntimeError("CORPCAN_API_KEY is not set")
        self.sess = session()
        self.sess.headers["Accept-Language"] = "en"
        self._last = 0.0

    def directors(self, corp_number: str) -> list[dict]:
        num = corp_number.split("-")[0].strip()
        wait = (60.0 / CALLS_PER_MIN) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self.sess.get(DIRECTORS_URL.format(num=num),
                                 params={"user_key": self.key}, timeout=60)
        except Exception as e:
            log.warning("directors lookup failed for %s: %s", num, type(e).__name__)
            return []
        if resp.status_code == 429:
            time.sleep(65)
            return self.directors(corp_number)
        if resp.status_code != 200:
            log.warning("directors %s: HTTP %d", num, resp.status_code)
            return []
        data = resp.json()
        if isinstance(data, dict):
            for key in ("directors", "_embedded"):
                if key in data:
                    inner = data[key]
                    return inner.get("directors", inner) if isinstance(inner, dict) else inner
        return data if isinstance(data, list) else []


def run(skip_directors: bool = False) -> list[Signal]:
    st = state.load("corpcan")
    sess = session()
    html = fetch(sess, MONTHLY_URL, timeout=120)
    label, corps = _parse_monthly(html)
    if label and label == st.get("last_month"):
        log.info("corpcan: %s already processed", label)
        return []
    log.info("corpcan: %s — %d new corporations", label or "(unknown month)", len(corps))

    kw = load_keywords()
    signals: list[Signal] = []
    keyword_hits = []
    for c in corps:
        hit = match_name(c["name"], kw)
        if hit and not re.match(r"^\d{7,8} CANADA (INC|LTD|CORP)", c["name"].upper()):
            keyword_hits.append((c, hit))

    screened = haiku.screen_candidates(
        [{"name": c["name"], "description": f"new federal corp, keyword '{h}'"}
         for c, h in keyword_hits],
        context="Newly incorporated federal (CBCA) corporations matching climate keywords")

    matched_numbers = set()
    for c, hit in keyword_hits:
        v = screened.get(c["name"], {})
        if v and not v.get("keep", True):
            log.info("garbage skip: %s — %s", c["name"], v.get("reason", ""))
            continue
        matched_numbers.add(c["number"])
        signals.append(Signal(
            company=c["name"].title() if c["name"].isupper() else c["name"],
            source_lane="New Corps",
            signal_type="Other",
            jurisdiction="Federal",
            signal_date=c["date"],
            detail=(f"New CBCA incorporation (keyword: {hit}, {c['province']}). "
                    + (v.get("one_liner") or "")),
            source_url=CORP_SEARCH_URL.format(num=c["number"].split("-")[0]),
            raw_ref=f"cbca:{c['number']}",
            location=c["province"],
            hydrogen=hit == "hydrogen",
        ))

    if not skip_directors:
        wl = Watchlist(airtable_founders=Airtable().founder_names())
        client = DirectorClient()
        checked = 0
        for c in corps:
            if c["number"] in matched_numbers:
                continue
            checked += 1
            if checked % 500 == 0:
                log.info("director sweep: %d/%d", checked, len(corps))
            for d in client.directors(c["number"]):
                first = d.get("firstName") or d.get("first_name") or ""
                last = d.get("lastName") or d.get("last_name") or ""
                if not last:
                    continue
                m = wl.match(first, last)
                if not m:
                    continue
                display, confidence = m
                note = ("WATCHLIST MATCH" if confidence == "exact"
                        else "borderline watchlist match — adjudicate")
                signals.append(Signal(
                    company=c["name"],
                    source_lane="New Corps",
                    signal_type="Other",
                    jurisdiction="Federal",
                    signal_date=c["date"],
                    detail=(f"New CBCA incorporation, {note}: director "
                            f"{first} {last} ≈ {display} ({c['province']})"),
                    source_url=CORP_SEARCH_URL.format(num=c["number"].split("-")[0]),
                    raw_ref=f"cbca:{c['number']}",
                    director_names=f"{first} {last} — {display} [{confidence}]",
                    founder=f"{first} {last}",
                    location=c["province"],
                ))
                break

    st["last_month"] = label
    state.save("corpcan", st)
    log.info("corpcan: %d signals", len(signals))
    return signals
