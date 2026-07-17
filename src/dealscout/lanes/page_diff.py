"""Generic diff-scrape engine used by lane C (cohorts) and lane A's
provincial funder pages (ERA, CICE).

State per page: content hash + last extracted company list. On change,
Haiku re-extracts and the list diff becomes signals. first_run: 'recent'
ingests only companies the page marks as current-cohort/recent; 'none'
just sets the baseline.
"""

import datetime as dt
import hashlib
import logging
import pathlib

import yaml

from .. import haiku, state
from ..http_util import fetch, page_text, session
from ..models import Signal

log = logging.getLogger("dealscout")

CONFIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"


def _signal(org: str, page: dict, comp: dict, screened: dict, lane: str,
            signal_type: str) -> Signal | None:
    name = comp["name"].strip()
    verdict = screened.get(name, {})
    if verdict and not verdict.get("keep", True):
        log.info("garbage skip (%s): %s — %s", org, name, verdict.get("reason", ""))
        return None
    detail = comp.get("description") or verdict.get("one_liner") or ""
    return Signal(
        company=name,
        source_lane=lane,
        signal_type=signal_type,
        jurisdiction=page.get("jurisdiction", "Other"),
        signal_date=dt.date.today().isoformat(),
        detail=f"{org}: {detail}".strip(": "),
        program=org,
        source_url=page["url"],
        raw_ref=f"pagediff:{org}",
        website=comp.get("website", ""),
    )


def run(config_file: str, state_name: str, lane: str, signal_type: str) -> list[Signal]:
    cfg = yaml.safe_load((CONFIG_DIR / config_file).read_text())
    st = state.load(state_name)
    sess = session()
    signals: list[Signal] = []

    for page in cfg["pages"]:
        org, url = page["org"], page["url"]
        try:
            html = fetch(sess, url)
        except Exception as e:
            log.error("FETCH FAILED %s (%s): %s — fix the URL in %s",
                      org, url, e, config_file)
            continue
        text = page_text(html, include_attrs=page.get("include_attrs", False))
        digest = hashlib.sha256(text.encode()).hexdigest()
        entry = st.get(url, {})

        if entry.get("hash") == digest:
            log.info("%s: unchanged", org)
            continue

        companies = haiku.extract_companies(org, text, page.get("diff_mode", "list"))
        names_now = sorted({c["name"].strip() for c in companies if c.get("name")})

        if not entry:  # first run
            if page.get("first_run", "recent") == "recent":
                fresh = [c for c in companies if c.get("recent")]
            else:
                fresh = []
            log.info("%s: baseline %d companies, %d recent ingested",
                     org, len(names_now), len(fresh))
        else:
            known = set(entry.get("companies", []))
            fresh = [c for c in companies if c["name"].strip() not in known]
            log.info("%s: %d new of %d", org, len(fresh), len(names_now))

        if fresh:
            screened = haiku.screen_candidates(
                [{"name": c["name"], "description": c.get("description", "")}
                 for c in fresh],
                context=f"Newly listed on {org} ({url})")
            for comp in fresh:
                sig = _signal(org, page, comp, screened, lane, signal_type)
                if sig:
                    signals.append(sig)

        st[url] = {"hash": digest, "companies": names_now,
                   "checked": dt.date.today().isoformat()}

    state.save(state_name, st)
    return signals
