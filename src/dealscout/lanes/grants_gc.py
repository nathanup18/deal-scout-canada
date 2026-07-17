"""Lane A source 1 — federal Grants & Contributions proactive disclosure.

Streams the combined grants.csv from open.canada.ca (large file) and filters:
target departments/programs, $25k-$2M, for-profit recipients, start date in
window (first run: 12 months back; steady state: since last run with a 45-day
overlap because departments disclose quarterly and late). Fully deterministic
— no model call. Recipient legal names from proactive disclosure are already
vetted by the granting department, so no garbage screen is needed here.
"""

import csv
import datetime as dt
import logging
import os
import tempfile

from .. import state
from ..http_util import session

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


def run() -> list[dict]:
    st = state.load("grants_gc")
    seen: set[str] = set(st.get("seen_refs", []))
    if st.get("last_run"):
        cutoff = (dt.date.fromisoformat(st["last_run"])
                  - dt.timedelta(days=OVERLAP_DAYS)).isoformat()
    else:
        cutoff = (dt.date.today() - dt.timedelta(days=BACKFILL_DAYS)).isoformat()
    log.info("grants_gc: cutoff %s, %d seen refs", cutoff, len(seen))

    candidates: list[dict] = []
    scanned = 0
    csv.field_size_limit(10_000_000)
    # This file is ~2.3GB uncompressed -- loading it into memory (even as one
    # big decoded string) OOM-kills a standard GitHub Actions runner. Stream
    # to a temp file on disk instead, then hand csv.DictReader a real text-mode
    # file handle: it still correctly reassembles quoted fields containing
    # embedded newlines (the csv module pulls further lines from the iterator
    # as needed), same as the in-memory version, just without holding
    # multiple full copies in RAM. Reading resp.raw directly was tried first
    # and rejected -- it closes mid-read under urllib3's connection-pool
    # release behavior.
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
        with session().get(CSV_URL, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=1 << 20):
                tmp.write(chunk)
    try:
        with open(tmp_path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            candidates, scanned = _filter_rows(reader, cutoff, seen)
    finally:
        os.remove(tmp_path)
    log.info("grants_gc: scanned %d rows, %d matches", scanned, len(candidates))
    st["last_run"] = dt.date.today().isoformat()
    st["seen_refs"] = sorted(seen)[-50000:]
    state.save("grants_gc", st)
    return candidates


def _filter_rows(reader, cutoff: str, seen: set[str]) -> tuple[list[dict], int]:
    candidates: list[dict] = []
    scanned = 0
    for row in reader:
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
        candidates.append({
            "company": name,
            "amount": value,
            "signal_date": start,
            "detail": desc[:1200] or f"{prog} award",
            "program": prog or (row.get("owner_org") or ""),
            "jurisdiction": PROVINCES.get(prov, "Federal"),
            "province": prov,
            "source_url": ("https://search.open.canada.ca/grants/?search_text="
                           + name.replace(" ", "%20")),
            "raw_ref": ref or f"gc:{name[:80]}:{start}",
        })
    return candidates, scanned
