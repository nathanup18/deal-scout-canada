"""Writes normalized signals into the Deal Scout base (Early Signals table).

All writes go by field ID, not name. Dedupe follows the base's existing
convention: dom:<domain> when a website is known, else name:<normalized name>.
"""

import datetime as dt
import logging
import os
import time

import requests

from .models import Signal, normalize_name

log = logging.getLogger("dealscout")

BASE_ID = "appNeNoS4CxQrN3B6"
TABLE_ID = "tblif65ZnRqM2ip0S"
API = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}"

F = {
    "company": "fldwJ5rlXtzCvwrio",
    "founder": "fldCV8rPKwkaTT6Ps",
    "signal_type": "fldFAp9Ml5PWrkegm",
    "detail": "fldjeJJe8jdgBJQlm",
    "amount": "fldyN0an0Uzh9yQNZ",
    "signal_date": "fldekBunrXWIUeGd1",
    "location": "fldtTL6VB5I1lTfj6",
    "website": "fldWag9dPEeQm1NfW",
    "source_url": "fldVmVEFn7J9ZsrnX",
    "date_seen": "fldWZ1uxPLYL8cRbg",
    "status": "fldh0Q0MMdd9soTfh",
    "dedupe_key": "fldAu0fxzzV6DetlK",
    "source_lane": "fld5O8oZ5TpZ1G106",
    "jurisdiction": "fldiABmaNTvGXts3u",
    "raw_ref": "fldTMwdEolPThr5G7",
    "director_names": "fldQVfwM8sGMKgjhp",
    "program": "fldFprIteYyJBEqiA",
}


class Airtable:
    def __init__(self):
        key = os.environ.get("AIRTABLE_API_KEY")
        if not key:
            raise RuntimeError("AIRTABLE_API_KEY is not set")
        self.sess = requests.Session()
        self.sess.headers["Authorization"] = f"Bearer {key}"
        self._last = 0.0

    def _request(self, method: str, **kwargs):
        for attempt in range(4):
            wait = 0.25 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            resp = self.sess.request(method, API, timeout=60, **kwargs)
            if resp.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Airtable rate limit persisted")

    def _list_all(self, fields: list[str]) -> list[dict]:
        records, offset = [], None
        while True:
            params = [("pageSize", "100"), ("returnFieldsByFieldId", "true")]
            params += [("fields[]", f) for f in fields]
            if offset:
                params.append(("offset", offset))
            data = self._request("GET", params=params)
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                return records

    def existing_identity(self) -> tuple[set[str], set[str]]:
        """(dedupe keys, normalized company names) already in the base."""
        keys, names = set(), set()
        for r in self._list_all([F["dedupe_key"], F["company"]]):
            f = r.get("fields", {})
            if f.get(F["dedupe_key"]):
                keys.add(f[F["dedupe_key"]].strip().lower())
            if f.get(F["company"]):
                names.add(normalize_name(f[F["company"]]))
        return keys, names

    def founder_names(self) -> list[str]:
        """Founder/PI names already logged — feeds the lane B watchlist."""
        out = []
        for r in self._list_all([F["founder"]]):
            raw = r.get("fields", {}).get(F["founder"], "")
            for part in raw.replace(";", ",").split(","):
                name = part.split("(")[0].strip()
                if len(name.split()) >= 2:
                    out.append(name)
        return out

    def write_signals(self, signals: list[Signal]) -> int:
        """Dedupe against the identity map, then batch-insert. Returns rows written."""
        keys, names = self.existing_identity()
        today = dt.date.today().isoformat()
        rows = []
        for s in signals:
            key = s.dedupe_key()
            norm = normalize_name(s.company)
            if key in keys or (norm and norm in names):
                log.info("dedupe skip: %s", s.company)
                continue
            keys.add(key)
            names.add(norm)
            detail = s.detail
            if s.hydrogen:
                detail = "[HYDROGEN — off-thesis, logged for visibility] " + detail
            fields = {
                F["company"]: s.company[:250],
                F["signal_type"]: s.signal_type,
                F["detail"]: detail[:5000],
                F["signal_date"]: s.signal_date,
                F["source_url"]: s.source_url,
                F["date_seen"]: today,
                F["status"]: "New",
                F["dedupe_key"]: key,
                F["source_lane"]: s.source_lane,
                F["jurisdiction"]: s.jurisdiction,
                F["raw_ref"]: s.raw_ref[:250],
                F["program"]: s.program[:250],
            }
            if s.amount is not None:
                fields[F["amount"]] = s.amount
            if s.founder:
                fields[F["founder"]] = s.founder[:250]
            if s.location:
                fields[F["location"]] = s.location[:250]
            if s.website:
                fields[F["website"]] = s.website
            if s.director_names:
                fields[F["director_names"]] = s.director_names[:5000]
            rows.append(fields)

        for i in range(0, len(rows), 10):
            batch = [{"fields": f} for f in rows[i:i + 10]]
            self._request("POST", json={"records": batch, "typecast": True})
        log.info("wrote %d/%d signals (rest deduped)", len(rows), len(signals))
        return len(rows)
