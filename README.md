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
| B — New corps (federal) | CBCA monthly transactions table — **every** new incorporation, not keyword-filtered | `lane-b-federal.yml` | `raw/corpcan.json` |
| D — Regulatory | Phase 2 — build after A–C are producing (GHG offset registry, BC LCFS, CIPO Y02 patents) | not built yet | — |

Volume philosophy (Nathan, 2026-07-17): maximum volume from these sources, not pedigree- or keyword-based pre-curation. The federal incorporation lane passes through every new corporation each month — thousands of rows — except bare numbered corps with no chosen name ("1234567 Canada Inc."), which carry zero distinguishing information regardless of volume goals. The keyword match is still computed and carried through as a scoring signal, it just no longer gates inclusion.

BC (OrgBook) stays keyword-scoped, not by choice but because its public search API has no way to list new registrations without a text query — every ordering/date-filter parameter was tried and none work, and BC doesn't publish a bulk incorporations feed the way the federal government does. Going keyword-free there would need a different data source (e.g. OpenCorporates' bulk BC dataset, likely paid/licensed) — a separate project, not a quick change.

The federal lane originally also swept director names against a pedigree watchlist to catch numbered/generic-named corps with a known founder behind them; that track was dropped 2026-07-17 (a full month's sweep, ~7k corps/~2h runtime, turned up 0 matches) in favor of just passing everything through.

Airtable holds all of this uncapped. Only the Slack digest to Isabel is capped (top 15 per lane per day, by score) so it stays readable when a big batch lands — that's a readability limit on one Slack message, not a quality gate on what gets logged. Everything not in a given day's top 15 is still written to Airtable, still stamped processed, and stays permanently findable there. Hydrogen-keyword hits are logged but flagged off-thesis and sort to the bottom (and can't occupy a top-15 digest slot).

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
