"""Lane B (federal) — Corporations Canada monthly incorporations.

Discovery: the monthly transactions publication page (stable URL, latest
month) lists every new CBCA certificate as an HTML table: corp number,
name, province, effective date.

Volume-first per Nathan (2026-07-17): every new corp is a candidate,
not just keyword matches. The only thing excluded is a bare numbered
corp with no chosen name ("1234567 Canada Inc.") -- those carry zero
distinguishing information regardless of volume philosophy, nothing
for the scheduled task to screen or score. matched_token/hydrogen are
still computed and carried through as scoring signal, they just no
longer gate inclusion. (The director-pedigree track was dropped the
same day after a full month's sweep, ~7k corps/~2h runtime, turned up
0 watchlist matches.) This lane needs no API key or secret -- it's a
plain public HTML page.
"""

import datetime as dt
import logging
import pathlib
import re

import yaml

from .. import state
from ..http_util import fetch, session
from ..models import fold

log = logging.getLogger("dealscout")

MONTHLY_URL = ("https://ised-isde.canada.ca/site/corporations-canada/en/"
               "data-services/monthly-transactions/certificates-incorporation-cbca")
CORP_SEARCH_URL = "https://ised-isde.canada.ca/cbr-rec/en/search/results?search={num}"
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


def run() -> list[dict]:
    st = state.load("corpcan")
    sess = session()
    html = fetch(sess, MONTHLY_URL, timeout=120)
    label, corps = _parse_monthly(html)
    if label and label == st.get("last_month"):
        log.info("corpcan: %s already processed", label)
        return []
    log.info("corpcan: %s — %d new corporations", label or "(unknown month)", len(corps))

    kw = load_keywords()
    candidates = []
    for c in corps:
        if re.match(r"^\d{7,8} CANADA (INC|LTD|CORP)", c["name"].upper()):
            continue  # bare numbered corp, no chosen name -- nothing to screen or score
        hit = match_name(c["name"], kw)
        candidates.append({
            "company": c["name"],
            "matched_token": hit,          # None if no keyword matched -- still a candidate
            "hydrogen": hit == "hydrogen",
            "date": c["date"],
            "jurisdiction": "Federal",
            "province": c["province"],
            "source_url": CORP_SEARCH_URL.format(num=c["number"].split("-")[0]),
            "raw_ref": f"cbca:{c['number']}",
        })

    st["last_month"] = label
    state.save("corpcan", st)
    log.info("corpcan: %d candidates (%d keyword-matched)", len(candidates),
              sum(1 for c in candidates if c["matched_token"]))
    return candidates
