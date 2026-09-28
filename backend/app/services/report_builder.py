"""
Builds the structured IncidentReportPayload from an incident's real data.
The schema (see app/schemas/report.py) never changes shape — summary,
confidence_breakdown, recommended_actions are always present — even though
the summary's exact wording is assembled from whatever this incident's real
sources/detection results actually are. Swapping in an LLM to phrase the
summary later (TRD §5.4) only touches the `_build_summary` function; the rest
of this file, and every caller of it, stays the same.
"""
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.media import DetectionResult
from app.models.source import Source, EvidenceItem, UPLOAD_SOURCE_PLATFORM
from app.schemas.report import IncidentReportPayload, ConfidenceBreakdownItem, RecommendedAction
from app.services.llm_report import generate_summary_with_llm


def _format_ts(dt) -> str:
    return dt.strftime("%d %b %Y, %I:%M %p").lstrip("0").replace(" 0", " ")


def _build_summary(
    detection: DetectionResult | None,
    sources: list[Source],
    evidence_count: int,
) -> str:
    if not detection and not sources:
        return (
            "No detection results or related sources have been recorded for this "
            "incident yet. Run detection and add sources to generate a complete summary."
        )

    # Try the real LLM path first (TRD §5.4) — only ever handed the already-
    # computed facts below, never asked to invent anything.
    external_sources = [s for s in sources if s.platform != UPLOAD_SOURCE_PLATFORM]
    upload_count = len(sources) - len(external_sources)

    if external_sources:
        earliest, latest = external_sources[0], external_sources[-1]
        window_hours = round((latest.observed_at - earliest.observed_at).total_seconds() / 3600, 1)
        earliest_label = earliest.account_identifier or "an unidentified account"
        other_count = len(external_sources) - 1
        propagation_window = f"approximately {window_hours} hours across {len(external_sources)} recorded external source(s)"
    else:
        earliest_label, other_count, propagation_window = "n/a", 0, "n/a (no sources recorded)"

    manipulation_pct = f"{detection.manipulation_likelihood:.0f}%" if detection else "not yet analyzed"

    llm_summary = None
    if external_sources:
        llm_summary = generate_summary_with_llm(
            manipulation_pct=manipulation_pct,
            source_count=len(external_sources),
            earliest_label=earliest_label,
            other_count=other_count,
            propagation_window=propagation_window,
        )
    if llm_summary:
        return llm_summary

    # Deterministic fallback — always correct, just less fluent than the LLM version.
    parts = []
    if detection:
        parts.append(
            f"Uploaded media received a {detection.manipulation_likelihood:.0f}% "
            f"manipulation-likelihood score from {detection.model_name}."
        )
    if upload_count:
        parts.append(
            f"{upload_count} investigator-submitted media file(s) are preserved. "
            "This does not establish the original posting location."
        )
    if external_sources:
        parts.append(
            f"The investigator recorded {len(external_sources)} external source(s) "
            f"within an observation-time range of roughly {window_hours} hours. "
            f"{earliest_label} has the earliest recorded observation time."
        )
    parts.append(
        "Real-world attribution of the originating account has not been established "
        "and would require platform- or law-enforcement-level access."
    )
    return " ".join(parts)


def build_report_payload(incident: Incident, db: Session) -> IncidentReportPayload:
    sources = (
        db.query(Source).filter(Source.incident_id == incident.id).order_by(Source.observed_at).all()
    )
    evidence_items = db.query(EvidenceItem).filter(EvidenceItem.incident_id == incident.id).all()
    detection = (
        db.query(DetectionResult)
        .join(DetectionResult.media_item)
        .filter_by(incident_id=incident.id)
        .order_by(DetectionResult.created_at.desc())
        .first()
    )

    summary = _build_summary(detection, sources, len(evidence_items))

    breakdown = []
    if detection:
        breakdown.append(ConfidenceBreakdownItem(label="Manipulation detection", value=detection.manipulation_likelihood))
    similarity_scores = [s.similarity_score for s in sources if s.similarity_score is not None]
    if similarity_scores:
        breakdown.append(
            ConfidenceBreakdownItem(
                label="Media similarity across sources",
                value=round(sum(similarity_scores) / len(similarity_scores), 1),
            )
        )
    if len(sources) > 1:
        breakdown.append(ConfidenceBreakdownItem(label="Earliest observed source", value=100.0))
    breakdown.append(
        ConfidenceBreakdownItem(label="Real-world attribution", value=0.0, note="Not established")
    )

    actions = [
        RecommendedAction(
            title="Preserve every piece of collected evidence",
            detail=f"All {len(evidence_items)} evidence item(s) are already saved in the Evidence "
                   f"Locker — do not delete the original file.",
        ),
        RecommendedAction(
            title="File a complaint at cybercrime.gov.in",
            detail="Attach the exported incident report and evidence bundle directly to the complaint form.",
        ),
        RecommendedAction(
            title="Call the 1930 national cybercrime helpline",
            detail="Report the incident by phone for a faster initial response alongside the online complaint.",
        ),
        RecommendedAction(
            title="Request platform takedown citing the applicable takedown-window rule",
            detail="Reference the specific regulation and window explicitly in the takedown request.",
        ),
        RecommendedAction(
            title="Reach out to a support organisation",
            detail="Organisations such as NWM India can help navigate reporting and provide emotional support.",
        ),
    ]

    return IncidentReportPayload(
        summary=summary,
        confidence_breakdown=breakdown,
        recommended_actions=actions,
        source_count=len(sources),
        evidence_count=len(evidence_items),
    )
