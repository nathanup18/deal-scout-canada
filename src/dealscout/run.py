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


def _write_raw(lane: str, data) -> None:
    RAW_DIR.mkdir(exist_ok=True)
    path = RAW_DIR / f"{lane}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))
    log.info("wrote %s", path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=["cohorts", "grant-pages", "grants",
                                         "nserc", "orgbook", "corpcan"])
    parser.add_argument("--skip-directors", action="store_true",
                        help="corpcan: keyword track only (no API sweep)")
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
        result = corpcan.run(skip_directors=args.skip_directors)
        count = len(result["keyword_hits"]) + len(result["director_hits"])

    log.info("%s: %d raw candidates", args.lane, count)
    _write_raw(args.lane, result)


if __name__ == "__main__":
    sys.exit(main())
