"""Lane B track 2 (BC) — OrgBook BC keyword search over new registrations.

Purely deterministic: for each climate token, query the v4 topic search
and keep hits newer than the last run (2-day overlap). Directors are not
in OrgBook, so this is keyword-only. Garbage screening (e.g. "Solar Nails
Ltd.") happens later, in the Claude scheduled task that reads raw output —
this module does no model calls.
"""

import datetime as dt
import logging

from .. import state
from ..http_util import session
from .corpcan import load_keywords, match_name  # shared keyword logic

log = logging.getLogger("dealscout")

API = "https://orgbook.gov.bc.ca/api/v4/search/topic"
MAX_PAGES = 10  # per token per run; results are recency-agnostic so we filter


def run() -> list[dict]:
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
                candidates.append({
                    "company": name,
                    "matched_token": hit,
                    "hydrogen": hit == "hydrogen",
                    "registered": reg,
                    "source_url": f"https://orgbook.gov.bc.ca/entity/{sid}",
                    "raw_ref": f"orgbook:{sid}",
                    "jurisdiction": "BC",
                })
            if not data.get("next"):
                break
            page += 1

    st["last_run"] = dt.date.today().isoformat()
    st["seen"] = sorted(seen_ids)[-100000:]
    state.save("orgbook_bc", st)
    log.info("orgbook_bc: %d candidates", len(candidates))
    return candidates
