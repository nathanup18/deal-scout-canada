"""Claude Haiku normalization: page -> company list, candidate -> screened signal.

The only quality gate besides Copper novelty is the obvious-garbage filter
here (nail salons, holding companies, etc). Everything else gets logged.
"""

import json
import logging
import os

import anthropic

log = logging.getLogger("dealscout")

MODEL = "claude-haiku-4-5-20251001"


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic()


def _json_call(system: str, user: str, tool_schema: dict) -> dict:
    client = _client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[{"name": "emit", "description": "Emit the result.",
                "input_schema": tool_schema}],
        tool_choice={"type": "tool", "name": "emit"},
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Haiku returned no tool call")


COMPANIES_SCHEMA = {
    "type": "object",
    "properties": {"companies": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "website": {"type": "string"},
            "recent": {"type": "boolean"},
        },
        "required": ["name", "recent"],
    }}},
    "required": ["companies"],
}


def extract_companies(org: str, page_text: str, mode: str) -> list[dict]:
    """Full company list from a portfolio page ('list') or companies named in
    posts ('news'). `recent` = joined/announced in the last ~6 months as far
    as the page shows (cohort year tags, post dates)."""
    system = (
        "You extract startup company names from accelerator/funder web pages "
        "for a venture pipeline. Return every distinct company the page lists "
        "or announces. Exclude the accelerator itself, sponsors, universities, "
        "government bodies, and navigation junk. description: one line from "
        "the page if present, else empty. website: only if a company URL is "
        "explicitly in the content. recent: true only if the page shows the "
        "company was added/announced/funded within roughly the last 6 months "
        "(cohort year 2026, dated post, 'new cohort' section); false or when "
        "unclear, false.")
    user = f"Source: {org} ({mode} page). Page content:\n\n{page_text[:150000]}"
    return _json_call(system, user, COMPANIES_SCHEMA).get("companies", [])


SCREEN_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "keep": {"type": "boolean"},
            "reason": {"type": "string"},
            "one_liner": {"type": "string"},
        },
        "required": ["name", "keep"],
    }}},
    "required": ["results"],
}


def screen_candidates(candidates: list[dict], context: str) -> dict[str, dict]:
    """Obvious-garbage filter only. keep=false ONLY for clearly non-venture
    entities. Returns {input name -> result}."""
    if not candidates:
        return {}
    system = (
        "You are a lenient relevance filter for a climate-tech deal pipeline. "
        "Mark keep=false ONLY for obvious garbage: consumer/local service "
        "businesses whose name merely contains a keyword (e.g. 'Solar Nails "
        "Ltd.' is a nail salon), real-estate numbered holdcos, shell/estate "
        "entities, government bodies. When in doubt, keep=true — a human "
        "digest downstream does the real screening. one_liner: what the "
        "company plausibly does, one short line, from the info given only.")
    out: dict[str, dict] = {}
    for i in range(0, len(candidates), 25):
        chunk = candidates[i:i + 25]
        user = f"Context: {context}\nCandidates:\n{json.dumps(chunk, ensure_ascii=False)}"
        for r in _json_call(system, user, SCREEN_SCHEMA).get("results", []):
            out[r["name"]] = r
    return out
