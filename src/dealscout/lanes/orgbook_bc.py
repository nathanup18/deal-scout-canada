"""Lane B track 2 (BC) — OrgBook BC keyword search over new registrations.

Daily: for each climate token, query the v4 topic search and keep hits whose
registration_date is newer than the last run (2-day overlap). Directors are
not in OrgBook, so this is keyword-only.
"""

import datetime as dt
import logging

import yaml

from .. import haiku, state
from ..http_util import session
from ..models import Signal, fold
from .corpcan import load_keywords, match_name  # shared keyword logic

log = logging.getLogger("dealscout")

API = "https://orgbook.gov.bc.ca/api/v4/search/topic"
MAX_PAGES = 10  # per token per run; results are recency-agnostic so we filter


def run() -> list[Signal]:
    st = state.load("orgbook_bc")
    if st.get("last_run"):
        cutoff = (dt.date.fromisoformat(st["last_run"])
                  - dt.timedelta(days=2)).isoformat()
    else:
        cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    kw = load_keywords()
    sess = session()
    seen_ids: set[str] = set(st.get("seen", []))
    candidates: list[dict] = []

    for token in kw["substring"] + kw["word"] + kw["hydrogen"]:
        page = 1
        while page <= MAX_PAGES:
            resp = sess.get(API, params={"q": token, "page": page}, timeout=60)
            if resp.status_code != 200:
                log.warning("orgbook %s p%d: HTTP %d", token, page, resp.status_code)
                break
            data = resp.json()
            for r in data.get("results", []):
                sid = r.get("source_id", "")
                names = [n["text"] for n in r.get("names", []) if n.get("text")]
                if not names or sid in seen_ids:
                    continue
                reg = ""
                for a in r.get("attributes", []):
                    if a.get("type") == "registration_date":
                        reg = (a.get("value") or "")[:10]
                if not reg or reg < cutoff:
                    continue
                name = names[0]
                hit = match_name(name, kw)
                if not hit:
                    continue
                seen_ids.add(sid)
                candidates.append({"name": name, "source_id": sid,
                                   "registered": reg, "hydrogen": hit == "hydrogen",
                                   "token": hit})
            if not data.get("next"):
                break
            page += 1

    screened = haiku.screen_candidates(
        [{"name": c["name"], "description": f"new BC corp, keyword '{c['token']}'"}
         for c in candidates],
        context="Newly registered BC corporations matching climate keywords")

    signals = []
    for c in candidates:
        v = screened.get(c["name"], {})
        if v and not v.get("keep", True):
            log.info("garbage skip: %s — %s", c["name"], v.get("reason", ""))
            continue
        signals.append(Signal(
            company=c["name"].title() if c["name"].isupper() else c["name"],
            source_lane="New Corps",
            signal_type="Other",
            jurisdiction="BC",
            signal_date=c["registered"],
            detail=(f"New BC registration (keyword: {c['token']}). "
                    + (v.get("one_liner") or "")),
            source_url=f"https://orgbook.gov.bc.ca/entity/{c['source_id']}",
            raw_ref=f"orgbook:{c['source_id']}",
            location="BC",
            hydrogen=c["hydrogen"],
        ))
    st["last_run"] = dt.date.today().isoformat()
    st["seen"] = sorted(seen_ids)[-100000:]
    state.save("orgbook_bc", st)
    log.info("orgbook_bc: %d signals", len(signals))
    return signals
