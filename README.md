# deal-scout-canada

Canadian public-data lanes for the Deal Scout pipeline. Split into two halves:

- **GitHub Actions** (this repo) — fetch/filter deterministically only. No AI, no model calls, no secrets. Each workflow writes its findings to `raw/<lane>.json` and commits it.
- **A daily Claude scheduled task** ("canada-lanes-daily") — triggers the workflows, reads `raw/*.json`, does the actual extraction/screening/scoring, dedupes against and writes to the Deal Scout Airtable base (`appNeNoS4CxQrN3B6`, Early Signals table) via the Airtable MCP tools, runs the Copper novelty check, and DMs the digest to Isabel. It clears each raw file once processed, so `raw/` is just a handoff queue between the two halves.

There is no Anthropic/OpenAI API key anywhere in this pipeline — the scheduled task's own model call *is* the normalization step, replacing what would otherwise be a per-script Haiku/GPT call.

Known gap, accepted: Ontario's registry is closed — no ON incorporation lane.

## Lanes

| Lane | What | Workflow | Raw output |
|------|------|----------|------------|
| C — Cohorts | Diff-scrape 9 accelerator pages ([config](config/cohort_pages.yaml)) | `lane-c-cohorts.yml` | `raw/cohorts.json` |
| A — Grants | Federal G&C CSV filter + ERA/NorthX page diffs + NSERC (experimental) | `lane-a-grants.yml` | `raw/grants.json`, `raw/grant_pages.json`, `raw/nserc.json` |
| B — New corps (BC) | OrgBook BC keyword search on new registrations | `lane-b-orgbook.yml` | `raw/orgbook.json` |
| B — New corps (federal) | CBCA monthly transactions table, keyword-matched | `lane-b-federal.yml` | `raw/corpcan.json` |
| D — Regulatory | Phase 2 — build after A–C are producing (GHG offset registry, BC LCFS, CIPO Y02 patents) | not built yet | — |

Both New Corps sources (BC and federal) are keyword-match only — any new incorporation whose name contains a climate-relevant token becomes a signal, regardless of who founded it. The federal lane originally also swept director names against a pedigree watchlist to catch numbered/generic-named corps with a known founder behind them; that track was dropped 2026-07-17 after a full month's sweep (~7k corps, ~2h runtime) turned up 0 matches, while the keyword track — unrestricted, no founder-list dependency — is what actually produces volume. Nathan's priority is maximum volume from these sources, not pedigree-based curation, so this was the right call.

Volume philosophy: no caps, no quality gate beyond the scheduled task's obvious-garbage judgment and the Copper novelty check. Everything real lands in Airtable; scoring only affects digest sort order. Hydrogen-keyword hits are logged but flagged off-thesis and sort to the bottom.

## Triggering

Every workflow is `workflow_dispatch`-only — no GitHub-native `schedule:` cron. The `canada-lanes-daily` Claude scheduled task is the only trigger, once a day: it runs each workflow via `gh workflow run`, polls briefly, then does the synthesis pass. All four lanes are fast now (seconds to low minutes).

## Required repo secrets

None. Every lane hits public data with no auth.

## Running a lane locally

```
pip install -r requirements.txt
PYTHONPATH=src python -m dealscout.run cohorts
cat raw/cohorts.json
```

Lanes: `cohorts`, `grant-pages`, `grants`, `nserc`, `orgbook`, `corpcan`.

To compute an Airtable dedupe key by hand (stdlib-only, no pip install needed):
```
python3 -m dealscout.dedupe_key "Company Name" [--website https://example.com]
```

## State

- `state/*.json` — CI-owned (page content hashes, seen-ref sets, last-run/last-month dates). Committed by the workflows.
- `state/*_companies.json` — owned by the `canada-lanes-daily` scheduled task (known company lists per cohort page, used to diff for new entrants). Delete either kind of state file to force a re-baseline of that lane.
