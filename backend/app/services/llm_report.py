"""
Optional real LLM integration for the Incident Report's summary paragraph
(TRD §5.4). This is deliberately narrow in scope: the LLM is only ever asked
to write the `summary` string from a structured, pre-computed fact sheet —
never asked to invent the confidence numbers, source counts, or recommended
actions, and never asked to return the whole report JSON itself. That's what
keeps the report's schema deterministic (app/schemas/report.py) even when an
LLM writes the prose inside one field of it.

If ANTHROPIC_API_KEY is not set, or the API call fails for any reason
(network, rate limit, bad key), the caller falls back to the deterministic
template in report_builder.py — this module never raises out to the caller
for anything except a genuinely misconfigured client construction.
"""
from app.core.config import get_settings

settings = get_settings()

PROMPT_TEMPLATE = """You are drafting the executive summary paragraph of a formal digital-forensics \
incident report for a synthetic-media (deepfake) investigation platform called LINEAGE.

Write ONE paragraph (3-5 sentences), plain language, no headers, no bullet points, no markdown. \
State only the facts given below — do not invent any number, date, platform, or account name \
that isn't provided. Do not claim to know the real-world identity of anyone. End by noting that \
real-world attribution has not been established and would require platform- or law-enforcement-level access.

Facts:
- Manipulation signal score: {manipulation_pct}
- Number of investigator-recorded external source entries: {source_count}
- Earliest recorded observation: {earliest_label}
- Number of additional recorded external source entries: {other_count}
- Observation-time range: {propagation_window}

Write only the paragraph, nothing else."""


def generate_summary_with_llm(
    manipulation_pct: str,
    source_count: int,
    earliest_label: str,
    other_count: int,
    propagation_window: str,
) -> str | None:
    """Returns the LLM-written summary, or None if unavailable/failed —
    callers must have a deterministic fallback ready either way."""
    if not settings.ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        prompt = PROMPT_TEMPLATE.format(
            manipulation_pct=manipulation_pct,
            source_count=source_count,
            earliest_label=earliest_label,
            other_count=other_count,
            propagation_window=propagation_window,
        )
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        summary = " ".join(text_blocks).strip()
        return summary or None
    except Exception:
        # Deliberately swallow every failure mode here (bad key, network,
        # rate limit) — this path is a nice-to-have, not load-bearing, and
        # the deterministic fallback is always correct even if less fluent.
        return None
