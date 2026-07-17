"""Entry point: python -m dealscout.run <lane>

Lanes: cohorts | grant-pages | grants | nserc | orgbook | corpcan
Each lane collects signals, dedupes against the Deal Scout base, writes rows.
"""

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("dealscout")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=["cohorts", "grant-pages", "grants",
                                         "nserc", "orgbook", "corpcan"])
    parser.add_argument("--dry-run", action="store_true",
                        help="collect + print, skip the Airtable write")
    parser.add_argument("--skip-directors", action="store_true",
                        help="corpcan: keyword track only (no API sweep)")
    args = parser.parse_args()

    if args.lane == "cohorts":
        from .lanes import page_diff
        signals = page_diff.run("cohort_pages.yaml", "cohorts", "Cohorts",
                                "Accelerator/Fellowship")
    elif args.lane == "grant-pages":
        from .lanes import page_diff
        signals = page_diff.run("grant_pages.yaml", "grant_pages", "Grants",
                                "Grant - Other")
    elif args.lane == "grants":
        from .lanes import grants_gc
        signals = grants_gc.run()
    elif args.lane == "nserc":
        from .lanes import nserc
        signals = nserc.run()
    elif args.lane == "orgbook":
        from .lanes import orgbook_bc
        signals = orgbook_bc.run()
    else:
        from .lanes import corpcan
        signals = corpcan.run(skip_directors=args.skip_directors)

    log.info("%s: %d candidate signals", args.lane, len(signals))
    if args.dry_run:
        for s in signals:
            print(f"  {s.company} | {s.signal_date} | {s.detail[:100]}")
        return

    if signals:
        from .airtable_client import Airtable
        written = Airtable().write_signals(signals)
        log.info("done: %d rows written", written)


if __name__ == "__main__":
    sys.exit(main())
