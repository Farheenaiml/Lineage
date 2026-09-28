"""
Walks an incident's real evidence graph (sources + relationships + detection
result) and classifies facts into known / unresolved / evidence_needed. This
is deliberately rule-based, not an LLM call — per TRD §5.5, the honesty
boundary that makes LINEAGE's core differentiator credible should be
something you can point to as logic, not something a language model might
phrase inconsistently between runs.

The unresolved / evidence_needed categories are largely fixed statements
about the structural limits of public evidence (real-world identity, IP/
device access, etc.) — those don't change per case, only the "known" column
does, since that's the only part actually derived from this incident's data.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.media import DetectionResult
from app.models.source import Source, UPLOAD_SOURCE_PLATFORM
from app.models.report import AttributionGapEntry


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%d %b %Y, %I:%M %p").lstrip("0").replace(" 0", " ")


def build_attribution_gap(incident: Incident, db: Session) -> list[AttributionGapEntry]:
    sources: list[Source] = (
        db.query(Source).filter(Source.incident_id == incident.id).order_by(Source.observed_at).all()
    )
    latest_detection: DetectionResult | None = (
        db.query(DetectionResult)
        .join(DetectionResult.media_item)
        .filter_by(incident_id=incident.id)
        .order_by(DetectionResult.created_at.desc())
        .first()
    )

    known: list[str] = []
    if latest_detection:
        if "fallback" in (latest_detection.model_name or "").lower():
            known.append(
                f"The pixel-heuristic fallback returned a "
                f"{latest_detection.manipulation_likelihood:.0f}% manipulation-likelihood score; "
                "this is not a trained deepfake-classifier conclusion."
            )
        else:
            known.append(
                f"The detection model returned a "
                f"{latest_detection.manipulation_likelihood:.0f}% manipulation-likelihood score."
            )

    external_sources = [s for s in sources if s.platform != UPLOAD_SOURCE_PLATFORM]
    upload_count = len(sources) - len(external_sources)
    if upload_count:
        known.append(
            f"{upload_count} investigator-submitted media file(s) are preserved in this case. "
            + (
                "No external source has been recorded; a submission alone does not establish "
                "where the media was originally posted."
                if not external_sources
                else "A submission alone does not establish where the media was originally posted."
            )
        )

    if external_sources:
        known.append(
            f"{len(external_sources)} external source(s) have been recorded by the investigator; "
            "their content and posting details have not been independently verified."
        )
        earliest = external_sources[0]
        earliest_label = earliest.account_identifier or "an unidentified account"
        known.append(
            f"Among the recorded external sources, {earliest_label} ({earliest.platform}) "
            f"has the earliest observation time: {_format_ts(earliest.observed_at)}."
        )
        if len(external_sources) > 1:
            others = ", ".join(
                s.account_identifier or s.platform for s in external_sources[1:]
            )
            known.append(
                f"Other investigator-recorded external source(s): {others}. "
                "No repost relationship is inferred unless it was explicitly recorded."
            )
            window = external_sources[-1].observed_at - external_sources[0].observed_at
            hours = round(window.total_seconds() / 3600, 1)
            known.append(
                f"Observation-time range for recorded external sources: "
                f"{_format_ts(external_sources[0].observed_at)} \u2013 "
                f"{_format_ts(external_sources[-1].observed_at)} "
                f"(approximately {hours} hours)."
            )

    earliest_handle = (
        external_sources[0].account_identifier or external_sources[0].platform
        if external_sources
        else "the original posting account"
    )

    unresolved = [
        f"The real-world identity of the person behind {earliest_handle}.",
        f"Whether {earliest_handle} created the manipulated media or obtained it from elsewhere."
        if external_sources
        else "Where the uploaded media was originally posted and who created or altered it.",
        "IP address, device, or login information for the originating account.",
        "Whether the account is genuine, compromised, or operated anonymously via VPN.",
    ]

    evidence_needed = [
        "Account registration & login records — obtainable only via platform legal request or law-enforcement order.",
        "IP / session logs tied to the upload — obtainable only via authorized investigation.",
        "Platform-side original upload metadata (device, timestamp, source IP).",
        "Cross-reference with any prior reports linked to the same account.",
    ]

    entries: list[AttributionGapEntry] = []
    for statement in known:
        entries.append(AttributionGapEntry(incident_id=incident.id, category="known", statement=statement))
    for statement in unresolved:
        entries.append(AttributionGapEntry(incident_id=incident.id, category="unresolved", statement=statement))
    for statement in evidence_needed:
        entries.append(
            AttributionGapEntry(incident_id=incident.id, category="evidence_needed", statement=statement)
        )
    return entries
