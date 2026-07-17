# deal-scout-canada

Canadian public-data lanes for the Deal Scout pipeline. Split into two halves:

- **GitHub Actions** (this repo) — fetch/filter deterministically only. No AI, no model calls, mostly no secrets at all. Each workflow writes its findings to `raw/<lane>.json` and commits it.
- **A daily Claude scheduled task** ("canada-lanes-daily") — triggers the workflows, reads `raw/*.json`, does the actual extraction/screening/scoring, dedupes against and writes to the Deal Scout Airtable base (`appNeNoS4CxQrN3B6`, Early Signals table) via the Airtable MCP tools, runs the Copper novelty check, and DMs the digest to Isabel. It clears each raw file once processed, so `raw/` is just a handoff queue between the two halves.

There is no Anthropic/OpenAI API key anywhere in this pipeline — the scheduled task's own model call *is* the normalization step, replacing what would otherwise be a per-script Haiku/GPT call.

Known gap, accepted: Ontario's registry is closed — no ON incorporation lane.

## Lanes

| Lane | What | Workflow | Raw output |
|------|------|----------|------------|
| C — Cohorts | Diff-scrape 9 accelerator pages ([config](config/cohort_pages.yaml)) | `lane-c-cohorts.yml` | `raw/cohorts.json` |
| A — Grants | Federal G&C CSV filter + ERA/CICE page diffs + NSERC (experimental) | `lane-a-grants.yml` | `raw/grants.json`, `raw/grant_pages.json`, `raw/nserc.json` |
| B — New corps (BC) | OrgBook BC keyword search on new registrations | `lane-b-orgbook.yml` | `raw/orgbook.json` |
| B — New corps (federal) | CBCA monthly transactions table; keyword track + director watchlist sweep via the Federal Corporation API (60/min plan limit, throttled to 55) | `lane-b-federal.yml` | `raw/corpcan.json` |
| D — Regulatory | Phase 2 — build after A–C are producing (GHG offset registry, BC LCFS, CIPO Y02 patents) | not built yet | — |

Volume philosophy: no caps, no quality gate beyond the scheduled task's obvious-garbage judgment and the Copper novelty check. Everything real lands in Airtable; scoring only affects digest sort order. Hydrogen-keyword hits are logged but flagged off-thesis and sort to the bottom.

## Triggering

Every workflow is `workflow_dispatch`-only — no GitHub-native `schedule:` cron. The `canada-lanes-daily` Claude scheduled task is the only trigger, once a day: it runs each workflow via `gh workflow run`, polls briefly (bounded — it does not block on the federal lane's once-a-month ~2h director sweep; that lane's output just gets picked up the following day), then does the synthesis pass.

## Required repo secret

Only one, on `lane-b-federal.yml`:

| Secret | Source |
|--------|--------|
| `CORPCAN_API_KEY` | ISED API Store → ActiveImpactInvestments app → user key |

Sent as a `user_key` query parameter; request URLs are never logged for that reason. No other workflow needs a secret — they hit public data with no auth.

## Running a lane locally

```
pip install -r requirements.txt
PYTHONPATH=src python -m dealscout.run cohorts
cat raw/cohorts.json
```

Lanes: `cohorts`, `grant-pages`, `grants`, `nserc`, `orgbook`, `corpcan` (`--skip-directors` skips the 2h federal director sweep).

To compute an Airtable dedupe key by hand (stdlib-only, no pip install needed):
```
python3 -m dealscout.dedupe_key "Company Name" [--website https://example.com]
```

## State

- `state/*.json` — CI-owned (page content hashes, seen-ref sets, last-run/last-month dates). Committed by the workflows.
- `state/*_companies.json` — owned by the `canada-lanes-daily` scheduled task (known company lists per cohort page, used to diff for new entrants). Delete either kind of state file to force a re-baseline of that lane.

## Watchlist

`config/watchlist.yaml` — director-pedigree names (Canadian climate anchor company alumni, researched 2026-07), used for the federal incorporation director-match track. The daily scheduled task tops this up with new Founder/PI names from Airtable after each run, so CI never needs Airtable access. Top up further from Specter searches 41846/41847 when the Specter connector is restored.
