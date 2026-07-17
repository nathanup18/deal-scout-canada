"""Lane A source 4 — NSERC Alliance awards, industry partner as the lead.

EXPERIMENTAL: NSERC's awards search is an ASP form; this hits the results
endpoint directly and parses what it can. Failures are logged loudly and
never kill the weekly grants run.
"""

import datetime as dt
import logging
import re

from bs4 import BeautifulSoup

from .. import state
from ..http_util import fetch, session
from ..models import Signal

log = logging.getLogger("dealscout")

SEARCH_URL = ("https://www.nserc-crsng.gc.ca/ase-oro/Results-Resultats_eng.asp"
              "?ID=6&Exclusive=true&AllText={kw}&FiscalYear={fy}&Program=Alliance")

CLIMATE_KEYWORDS = ["carbon", "climate", "clean energy", "battery", "emission",
                    "renewable", "biofuel", "electrification"]


def run() -> list[Signal]:
    st = state.load("nserc")
    seen: set[str] = set(st.get("seen", []))
    sess = session()
    fy = dt.date.today().year
    signals: list[Signal] = []
    for kw in CLIMATE_KEYWORDS:
        for year in (fy, fy - 1):
            url = SEARCH_URL.format(kw=kw.replace(" ", "+"), fy=year)
            try:
                html = fetch(sess, url, timeout=60)
            except Exception as e:
                log.warning("nserc fetch failed (%s %s): %s", kw, year, e)
                continue
            soup = BeautifulSoup(html, "html.parser")
            # Result rows carry partner org names; parse defensively.
            for row in soup.select("table tr"):
                cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                if len(cells) < 3:
                    continue
                blob = " | ".join(cells)
                partners = re.findall(
                    r"([A-Z][\w&.\- ]{3,60}(?:Inc|Ltd|Corp|Limited|Technologies|"
                    r"Energy|Systems)\.?)", blob)
                for partner in partners:
                    key = f"{partner}:{year}:{kw}"
                    if key in seen:
                        continue
                    seen.add(key)
                    signals.append(Signal(
                        company=partner.strip(),
                        source_lane="Grants",
                        signal_type="Grant - Other",
                        jurisdiction="Federal",
                        signal_date=dt.date.today().isoformat(),
                        detail=f"NSERC Alliance industry partner ({kw}): {blob[:600]}",
                        program="NSERC Alliance",
                        source_url=url,
                        raw_ref=f"nserc:{key[:200]}",
                    ))
    st["seen"] = sorted(seen)[-20000:]
    state.save("nserc", st)
    log.info("nserc: %d candidate partners", len(signals))
    return signals
