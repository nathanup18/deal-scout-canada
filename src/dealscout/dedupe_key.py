"""CLI: compute the Early Signals dedupe key for a candidate.

Used by the daily Claude scheduled task so key computation (accent
folding, legal-suffix stripping) is never re-derived by hand — it always
matches models.Signal.dedupe_key() exactly.

    python -m dealscout.dedupe_key "Solar Grid Technologies Ltée"
    python -m dealscout.dedupe_key "Example Corp" --website https://www.example.com/about
"""

import argparse

from .models import Signal


def main():
    p = argparse.ArgumentParser()
    p.add_argument("company")
    p.add_argument("--website", default="")
    args = p.parse_args()
    s = Signal(company=args.company, source_lane="", signal_type="",
               jurisdiction="", signal_date="", website=args.website)
    print(s.dedupe_key())


if __name__ == "__main__":
    main()
