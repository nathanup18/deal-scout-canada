"""Entry point: python -m dealscout.run <lane>

Lanes: cohorts | grant-pages | grants | nserc | orgbook | corpcan

Each lane does ONLY deterministic fetch/filter/dedupe work and writes its
findings to raw/<lane>.json. No model calls happen here — a Claude
scheduled task reads raw/*.json, does extraction/screening/scoring, writes
to Airtable, checks Copper, and sends the Isabel digest. That task also
clears each raw file (writes []/{}) once processed and commits the
clearing, so raw/ acts as a simple handoff queue.
"""

import argparse
import json
import logging
import pathlib
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("dealscout")

RAW_DIR = pathlib.Path(__file__).resolve().parents[2] / "raw"

# CLI lane name -> raw/state file basename. Kept separate because the CLI
# arg "grant-pages" would otherwise produce raw/grant-pages.json, mismatched
# against the underscored state/grant_pages*.json convention used everywhere
# else (and in the scheduled task's own instructions).
RAW_NAMES = {"cohorts": "cohorts", "grant-pages": "grant_pages", "grants": "grants",
             "nserc": "nserc", "orgbook": "orgbook", "corpcan": "corpcan"}


def _write_raw(lane: str, data) -> None:
    RAW_DIR.mkdir(exist_ok=True)
    path = RAW_DIR / f"{RAW_NAMES[lane]}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))
    log.info("wrote %s", path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=["cohorts", "grant-pages", "grants",
                                         "nserc", "orgbook", "corpcan"])
    args = parser.parse_args()

    if args.lane == "cohorts":
        from .lanes import page_diff
        result = page_diff.run("cohort_pages.yaml", "cohorts")
        count = len(result)
    elif args.lane == "grant-pages":
        from .lanes import page_diff
        result = page_diff.run("grant_pages.yaml", "grant_pages")
        count = len(result)
    elif args.lane == "grants":
        from .lanes import grants_gc
        result = grants_gc.run()
        count = len(result)
    elif args.lane == "nserc":
        from .lanes import nserc
        result = nserc.run()
        count = len(result)
    elif args.lane == "orgbook":
        from .lanes import orgbook_bc
        result = orgbook_bc.run()
        count = len(result)
    else:
        from .lanes import corpcan
        result = corpcan.run()
        count = len(result)

    log.info("%s: %d raw candidates", args.lane, count)
    _write_raw(args.lane, result)


if __name__ == "__main__":
    sys.exit(main())
