"""Lane B (federal) — Corporations Canada monthly incorporations.

Discovery: the monthly transactions publication page (stable URL, latest
month) lists every new CBCA certificate as an HTML table: corp number,
name, province, effective date.

Track 1 (director match): pull directors for every new corp via the
Federal Corporation API and match the static pedigree watchlist
(config/watchlist.yaml — deterministic string matching, no model call).
This surfaces numbered corps. ~7k corps/month at a 55/min throttle ≈ 2h.
Track 2 (keyword match): climate tokens in the corporation name — flagged
here, garbage-screened later by the Claude scheduled task.

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

from .. import state
from ..http_util import fetch, session
from ..models import fold
from ..watchlist import Watchlist

log = logging.getLogger("dealscout")

MONTHLY_URL = ("https://ised-isde.canada.ca/site/corporations-canada/en/"
               "data-services/monthly-transactions/certificates-incorporation-cbca")
DIRECTORS_URL = "https://ised-isde.api.canada.ca/corporations/api/v2/corporations/{num}/directors"
CORP_SEARCH_URL = "https://ised-isde.canada.ca/cbr-rec/en/search/results?search={num}"
CALLS_PER_MIN = 55  # Public Plan allows 60/min
CONFIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"


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


def run(skip_directors: bool = False) -> dict:
    """Returns {"keyword_hits": [...], "director_hits": [...]}."""
    st = state.load("corpcan")
    sess = session()
    html = fetch(sess, MONTHLY_URL, timeout=120)
    label, corps = _parse_monthly(html)
    if label and label == st.get("last_month"):
        log.info("corpcan: %s already processed", label)
        return {"keyword_hits": [], "director_hits": []}
    log.info("corpcan: %s — %d new corporations", label or "(unknown month)", len(corps))

    kw = load_keywords()
    keyword_hits = []
    matched_numbers = set()
    for c in corps:
        hit = match_name(c["name"], kw)
        if hit and not re.match(r"^\d{7,8} CANADA (INC|LTD|CORP)", c["name"].upper()):
            matched_numbers.add(c["number"])
            keyword_hits.append({
                "company": c["name"],
                "matched_token": hit,
                "hydrogen": hit == "hydrogen",
                "corp_number": c["number"],
                "province": c["province"],
                "date": c["date"],
                "source_url": CORP_SEARCH_URL.format(num=c["number"].split("-")[0]),
                "raw_ref": f"cbca:{c['number']}",
            })

    director_hits = []
    if not skip_directors:
        wl = Watchlist()  # static config/watchlist.yaml only — no live Airtable read in CI
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
                director_hits.append({
                    "company": c["name"],
                    "corp_number": c["number"],
                    "province": c["province"],
                    "date": c["date"],
                    "director_first": first,
                    "director_last": last,
                    "watchlist_match": display,
                    "confidence": confidence,
                    "source_url": CORP_SEARCH_URL.format(num=c["number"].split("-")[0]),
                    "raw_ref": f"cbca:{c['number']}",
                })
                break

    st["last_month"] = label
    state.save("corpcan", st)
    log.info("corpcan: %d keyword hits, %d director hits",
              len(keyword_hits), len(director_hits))
    return {"keyword_hits": keyword_hits, "director_hits": director_hits}
