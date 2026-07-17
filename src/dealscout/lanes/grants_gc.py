"""Lane A source 1 — federal Grants & Contributions proactive disclosure.

Streams the combined grants.csv from open.canada.ca (large file) and filters:
target departments/programs, $25k–$2M, for-profit recipients, start date in
window (first run: 12 months back; steady state: since last run with a 45-day
overlap because departments disclose quarterly and late).
"""

import csv
import datetime as dt
import io
import logging

from .. import state
from ..http_util import session
from ..models import Signal

log = logging.getLogger("dealscout")

CSV_URL = ("https://open.canada.ca/data/dataset/432527ab-7aac-45b5-81d6-7597107a7013/"
           "resource/1d15a62f-5656-49ad-8c88-f40ce689d831/download/grants.csv")

# owner_org prefixes on open.canada.ca (english-french compound codes)
DEPARTMENTS = {"nrc", "nrc-cnrc", "nrcan", "nrcan-rncan", "ec", "eccc",
               "ised", "ised-isde", "ic", "aafc", "aafc-aac"}
BACKFILL_DAYS = 365
OVERLAP_DAYS = 45
MIN_VALUE, MAX_VALUE = 25_000, 2_000_000

FOR_PROFIT_HINTS = ("inc", "ltd", "ltee", "corp", "limited", "incorporated", "ulc")


def _looks_for_profit(row: dict) -> bool:
    rtype = (row.get("recipient_type") or "").strip().upper()
    if rtype:
        return rtype == "F"
    name = (row.get("recipient_legal_name") or "").lower()
    return any(name.rstrip(".").endswith(h) for h in FOR_PROFIT_HINTS)


def _dept_match(row: dict) -> bool:
    org = (row.get("owner_org") or "").strip().lower()
    if org and (org in DEPARTMENTS or org.split("-")[0] in DEPARTMENTS):
        return True
    prog = (row.get("prog_name_en") or "").lower()
    return any(k in prog for k in ("irap", "energy innovation", "clean growth",
                                   "agri", "sustainable development technology"))


PROVINCES = {"BC": "BC", "AB": "AB", "ON": "ON", "QC": "QC"}


def run() -> list[Signal]:
    st = state.load("grants_gc")
    seen: set[str] = set(st.get("seen_refs", []))
    if st.get("last_run"):
        cutoff = (dt.date.fromisoformat(st["last_run"])
                  - dt.timedelta(days=OVERLAP_DAYS)).isoformat()
    else:
        cutoff = (dt.date.today() - dt.timedelta(days=BACKFILL_DAYS)).isoformat()
    log.info("grants_gc: cutoff %s, %d seen refs", cutoff, len(seen))

    signals: list[Signal] = []
    scanned = 0
    csv.field_size_limit(10_000_000)
    with session().get(CSV_URL, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        resp.raw.decode_content = True  # transparently gunzip the stream
        wrapper = io.TextIOWrapper(resp.raw, encoding="utf-8", errors="replace",
                                   newline="")
        for row in csv.DictReader(wrapper):
            scanned += 1
            start = (row.get("agreement_start_date") or "").strip()[:10]
            if not start or start < cutoff:
                continue
            try:
                value = float(row.get("agreement_value") or 0)
            except ValueError:
                continue
            if not (MIN_VALUE <= value <= MAX_VALUE):
                continue
            if not _dept_match(row) or not _looks_for_profit(row):
                continue
            country = (row.get("recipient_country") or "CA").strip().upper()
            if country not in ("CA", "CAN", ""):
                continue
            ref = (row.get("ref_number") or "").strip()
            if ref and ref in seen:
                continue
            seen.add(ref)

            name = (row.get("recipient_legal_name") or "").strip()
            if not name:
                continue
            prog = (row.get("prog_name_en") or "").strip()
            desc = (row.get("description_en") or "").strip()
            prov = (row.get("recipient_province") or "").strip().upper()
            signals.append(Signal(
                company=name,
                source_lane="Grants",
                signal_type="Grant - Other",
                jurisdiction=PROVINCES.get(prov, "Federal"),
                signal_date=start,
                detail=desc[:1200] or f"{prog} award",
                amount=value,
                program=prog or (row.get("owner_org") or ""),
                source_url="https://search.open.canada.ca/grants/?search_text="
                           + name.replace(" ", "%20"),
                raw_ref=ref or f"gc:{name[:80]}:{start}",
                location=prov,
            ))
    log.info("grants_gc: scanned %d rows, %d matches", scanned, len(signals))
    st["last_run"] = dt.date.today().isoformat()
    st["seen_refs"] = sorted(seen)[-50000:]
    state.save("grants_gc", st)
    return signals
