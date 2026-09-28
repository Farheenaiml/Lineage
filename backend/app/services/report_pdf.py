"""
Renders an IncidentReportPayload to an actual PDF file, using reportlab.
This is what backs the "Download PDF" button in the frontend — not a
placeholder that just re-serves the JSON with a different content type.
"""
import io

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

from app.schemas.report import IncidentReportPayload

NAVY = colors.HexColor("#1F3864")
GREY = colors.HexColor("#595959")


def render_report_pdf(payload: IncidentReportPayload, incident_title: str, incident_id: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("LTitle", parent=styles["Title"], textColor=NAVY, fontSize=22)
    h2_style = ParagraphStyle("LH2", parent=styles["Heading2"], textColor=NAVY, spaceBefore=14)
    body_style = ParagraphStyle("LBody", parent=styles["BodyText"], leading=15)
    meta_style = ParagraphStyle("LMeta", parent=styles["Normal"], textColor=GREY, fontSize=9)

    story = []
    story.append(Paragraph("LINEAGE — Incident Report", title_style))
    story.append(Paragraph(f"Case: {incident_title} &nbsp;&middot;&nbsp; ID: {incident_id}", meta_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=NAVY, thickness=1))
    story.append(Spacer(1, 14))

    story.append(Paragraph("1. Executive Summary", h2_style))
    story.append(Paragraph(payload.summary, body_style))

    story.append(Paragraph("2. Confidence Breakdown", h2_style))
    rows = [["Metric", "Value"]]
    for item in payload.confidence_breakdown:
        value_str = item.note if item.note else f"{item.value:.0f}%"
        rows.append([item.label, value_str])
    table = Table(rows, colWidths=[3.5 * inch, 2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    story.append(Paragraph("3. Evidence Summary", h2_style))
    story.append(Paragraph(
        f"Sources: {payload.source_count} &nbsp;&middot;&nbsp; Evidence items: {payload.evidence_count}",
        body_style,
    ))

    story.append(Paragraph("4. Recommended Next Actions", h2_style))
    for i, action in enumerate(payload.recommended_actions, start=1):
        story.append(Paragraph(f"<b>{i}. {action.title}</b> — {action.detail}", body_style))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CCCCCC"), thickness=0.5))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This report is an investigative lead based on available evidence, not proof of a "
        "person's identity, intent, or responsibility.",
        meta_style,
    ))

    doc.build(story)
    return buf.getvalue()
