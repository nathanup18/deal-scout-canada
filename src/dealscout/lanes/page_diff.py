"""Generic diff-scrape engine used by lane C (cohorts) and lane A's
provincial funder pages (ERA, CICE).

This module does ONLY deterministic work: fetch, hash, diff. It has no
model calls. When a page's content hash changes, the page's extracted
text is written to raw/<state_name>.json for the Claude scheduled task
to read, extract company names from, and screen — that synthesis step
happens outside CI entirely.

State ownership is split on purpose so CI and the scheduled task never
write the same file:
  state/<name>.json           — CI-owned: {url: {hash, checked}}
  state/<name>_companies.json — Claude-owned: {url: [known company names]}
    (read here only, to decide first_run behavior; the scheduled task
    updates it after each processing pass)
"""

import datetime as dt
import hashlib
import logging
import pathlib

import yaml

from .. import state
from ..http_util import fetch, page_text, session

log = logging.getLogger("dealscout")

CONFIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"


def run(config_file: str, state_name: str) -> dict:
    """Returns {url: {org, jurisdiction, first_run, diff_mode, text}} for
    every page whose content changed since last run. Also written to
    raw/<state_name>.json by the caller (run.py)."""
    cfg = yaml.safe_load((CONFIG_DIR / config_file).read_text())
    st = state.load(state_name)
    known_companies = state.load(f"{state_name}_companies")  # Claude-owned, read-only here
    sess = session()
    changed: dict = {}

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

        log.info("%s: changed, queuing for synthesis (%d chars)", org, len(text))
        changed[url] = {
            "org": org,
            "url": url,
            "jurisdiction": page.get("jurisdiction", "Other"),
            "first_run": page.get("first_run", "recent") if url not in known_companies else "diff",
            "diff_mode": page.get("diff_mode", "list"),
            "known_companies": known_companies.get(url, []),
            "text": text[:150_000],
        }
        st[url] = {"hash": digest, "checked": dt.date.today().isoformat()}

    state.save(state_name, st)
    return changed
