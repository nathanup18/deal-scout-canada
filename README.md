# deal-scout-canada

Canadian public-data lanes for the Deal Scout pipeline. GitHub Actions crons
ingest four signal lanes, normalize with Claude Haiku, dedupe against the
Deal Scout Airtable base (`appNeNoS4CxQrN3B6`, Early Signals table), and write
rows. The daily digest run (Claude scheduled task) picks up unsent rows, does
the Copper novelty check and thesis scoring, and DMs Isabel.

Known gap, accepted: Ontario's registry is closed — no ON incorporation lane.

## Lanes

| Lane | What | Cron | Module |
|------|------|------|--------|
| C — Cohorts | Diff-scrape 9 accelerator pages ([config](config/cohort_pages.yaml)) | weekly Mon | `lanes/page_diff.py` |
| A — Grants | Federal G&C CSV filter + ERA/CICE page diffs + NSERC (experimental) | weekly Tue | `lanes/grants_gc.py` |
| B — New corps (BC) | OrgBook BC keyword search on new registrations | daily | `lanes/orgbook_bc.py` |
| B — New corps (federal) | CBCA monthly transactions table; keyword track + director watchlist sweep via the Federal Corporation API (60/min plan limit, throttled to 55) | monthly day 3 | `lanes/corpcan.py` |
| D — Regulatory | Phase 2 — build after A–C are producing (GHG offset registry, BC LCFS, CIPO Y02 patents) | — | not built yet |

Volume philosophy: no caps, no quality gate beyond the obvious-garbage screen
in `haiku.py` and the Copper novelty check downstream. Everything lands in
Airtable; scoring only affects digest sort order. Hydrogen-keyword hits are
logged but flagged off-thesis and sort to the bottom.

## Required repo secrets

| Secret | Source |
|--------|--------|
| `AIRTABLE_API_KEY` | Airtable PAT with write access to `appNeNoS4CxQrN3B6` |
| `ANTHROPIC_API_KEY` | console.anthropic.com — Haiku normalization |
| `CORPCAN_API_KEY` | ISED API Store → ActiveImpactInvestments app → user key |

The Corporations Canada key is sent as a `user_key` query parameter; request
URLs are never logged for that reason.

## Running locally

```
pip install -r requirements.txt
PYTHONPATH=src python -m dealscout.run cohorts --dry-run
```

Lanes: `cohorts`, `grant-pages`, `grants`, `nserc`, `orgbook`, `corpcan`
(`--skip-directors` skips the 2h federal director sweep).

## State

`state/*.json` (page hashes, extracted company lists, seen-ref sets, last-run
dates) is committed back to the repo by each workflow. Delete a lane's state
file to force a full re-baseline.

## Watchlist

`config/watchlist.yaml` — director-pedigree names (Canadian climate anchor
company alumni, researched 2026-07). Founder/PI names from the Airtable base
are merged in at runtime. Top up from Specter searches 41846/41847 when the
Specter connector is restored.
