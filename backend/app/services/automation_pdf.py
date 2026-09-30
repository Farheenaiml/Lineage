"""Phase 5 PDF export of the investigation report and the alert draft (reportlab, same styling as report_pdf.py)."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

NAVY = colors.HexColor("#1F3864")
GREY = colors.HexColor("#595959")
RED = colors.HexColor("#8A4138")


def _styles():
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=s["Title"], textColor=NAVY, fontSize=20),
        "h2": ParagraphStyle("H2", parent=s["Heading2"], textColor=NAVY, spaceBefore=12),
        "body": ParagraphStyle("B", parent=s["BodyText"], leading=14, fontSize=9.5),
        "meta": ParagraphStyle("M", parent=s["Normal"], textColor=GREY, fontSize=8.5),
        "banner": ParagraphStyle("BN", parent=s["Title"], textColor=RED, fontSize=15),
    }


def _p(text) -> str:
    return escape(str(text if text is not None else "—"))


def _doc(story_fn) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    doc.build(story_fn(_styles()))
    return buf.getvalue()


def _bullets(story, st, items):
    if not items:
        story.append(Paragraph("None recorded.", st["body"]))
    for it in items:
        story.append(Paragraph("• " + it, st["body"]))


def render_investigation_report_pdf(report: dict) -> bytes:
    def story(st):
        ov = report["case_overview"]
        out = [Paragraph("LINEAGE — Investigation Report", st["title"]),
               Paragraph(f"Case: {_p(ov['title'])} · ID: {_p(ov['id'])} · Version {report['version']} · Generated {_p(report['generated_at'])}"
                         + (f" by {_p(report['generated_by']['email'])}" if report.get("generated_by") else ""), st["meta"]),
               Spacer(1, 8), HRFlowable(width="100%", color=NAVY, thickness=1)]
        out.append(Paragraph("1. Case overview", st["h2"]))
        c = ov["counts"]
        out.append(Paragraph(f"Status: {_p(ov['workflow']['label'])}. Media: {c['media']} · Sources: {c['sources']} · Evidence: {c['evidence']} · "
                             f"Locations: {c['locations']} · Relationships: {c['relationships']} · Graph backend: {_p(ov['graph_backend'])}", st["body"]))
        out.append(Paragraph("2. Evidence summary", st["h2"]))
        _bullets(out, st, [f"{_p(e['code'])} [{_p(e['evidence_id'])}] — {_p(e['item_type'])}, captured {_p(e['captured_at'])}"
                           for e in report["evidence_summary"]["evidence"]])
        _bullets(out, st, [f"Detection {_p(d['model_name'])}: {_p(d['manipulation_likelihood'])}% [{_p(d['detection_id'])}] — {_p(d['note'])}"
                           for d in report["evidence_summary"]["detection_results"]])
        out.append(Paragraph("3. Geographic findings", st["h2"]))
        _bullets(out, st, [f"{_p(l['label'])} ({l['latitude']:.4f}, {l['longitude']:.4f}) — " + ", ".join(
            f"{_p(k['source_code'])}: {_p(k['status'])}" for k in l["links"]) for l in report["geographic_findings"]["locations"]])
        out.append(Paragraph(_p(report["geographic_findings"]["note"]), st["meta"]))
        out.append(Paragraph("4. Propagation findings", st["h2"]))
        _bullets(out, st, [f"{_p(r['from'])} {'→' if r['type'] == 'PROPAGATES_TO' else '—'} {_p(r['to'])}: status {_p(r['status'])} [{_p(r['relationship_id'])}]"
                           for r in report["propagation_findings"]["relationships"]])
        out.append(Paragraph(_p(report["propagation_findings"]["note"]), st["meta"]))
        out.append(Paragraph("5. ML findings (analysis, not fact)", st["h2"]))
        for k, v in report["ml_findings"].items():
            out.append(Paragraph(f"<b>{_p(k.title())}</b> — {_p(v['model_name'])} {_p(v['model_version'])}, computed {_p(v['computed_at'])}: "
                                 + (_p(v["message"]) if v["message"] else f"{len(v['results'])} result(s)"), st["body"]))
            _bullets(out, st, [f"[{_p(r['id'])}] score {r['score']:.2f} — {_p(r['explanation'])}" for r in v["results"]])
        out.append(Paragraph("6. Facts by status", st["h2"]))
        for label, key in (("Verified / recorded", "verified"), ("Inferences", "inferences"), ("Unknown", "unknowns")):
            out.append(Paragraph(f"<b>{label}</b>", st["body"]))
            _bullets(out, st, [_p(f["statement"]) for f in report["facts"][key]])
        out.append(Paragraph("7. Evidence gaps", st["h2"]))
        _bullets(out, st, [_p(g["gap"]) for g in report["evidence_gaps"]])
        out.append(Paragraph("8. Recommended investigation actions", st["h2"]))
        _bullets(out, st, [_p(a["action"]) for a in report["recommended_actions"]])
        out += [Spacer(1, 12), HRFlowable(width="100%", color=colors.HexColor("#CCCCCC"), thickness=0.5),
                Paragraph(_p(report["disclaimer"]), st["meta"])]
        return out
    return _doc(story)


def render_alert_draft_pdf(draft: dict) -> bytes:
    def story(st):
        c = draft["content"]
        out = [Paragraph(_p(c["banner"]), st["banner"]),
               Paragraph("LINEAGE — Cyber-department notification draft", st["title"]),
               Paragraph(f"Investigation ID: {_p(c['investigation_id'])} · Draft {_p(draft['id'])} · Status: {_p(draft['status'])}"
                         + (f" (approved {_p(draft['approved_at'])} by {_p(draft.get('approved_by_email'))})" if draft.get("approved_at") else ""), st["meta"]),
               Paragraph(_p(c["transmission"]), st["meta"]), Spacer(1, 6), HRFlowable(width="100%", color=NAVY, thickness=1)]
        out += [Paragraph("Summary", st["h2"]), Paragraph(_p(draft["summary_text"]), st["body"])]
        out.append(Paragraph("Media / evidence references", st["h2"]))
        _bullets(out, st, [f"{_p(m['filename'])} [{_p(m['media_id'])}] fingerprints {_p(', '.join(m['fingerprint_ids']))}" for m in c["media"]]
                 + [f"{_p(e['code'])} [{_p(e['evidence_id'])}] {_p(e['item_type'])}, captured {_p(e['captured_at'])}" for e in c["evidence_references"]])
        out.append(Paragraph("Observed platforms and sources", st["h2"]))
        _bullets(out, st, [f"{_p(s['code'])} {_p(s['platform'])} {_p(s['account'])} observed {_p(s['observed_at'])} [{_p(s['source_id'])}]" for s in c["sources"]])
        out.append(Paragraph("Relevant locations", st["h2"]))
        _bullets(out, st, [f"{_p(l['label'])} — {_p(', '.join(l['statuses']))}" for l in c["relevant_locations"]])
        out.append(Paragraph("Timeline", st["h2"]))
        _bullets(out, st, [f"{_p(e['timestamp'])} [{_p(e['basis'])}] {_p(e['event'])}" for e in c["timeline"]])
        out.append(Paragraph("Detection findings", st["h2"]))
        _bullets(out, st, [f"{_p(d['model_name'])}: {_p(d['manipulation_likelihood'])}% — {_p(d['note'])}" for d in c["detection_findings"]])
        out.append(Paragraph("ML findings (analysis, not fact)", st["h2"]))
        for k, v in c["ml_findings"].items():
            _bullets(out, st, [f"{_p(k)} [{_p(r['id'])}] {r['score']:.2f}: {_p(r['explanation'])}" for r in v["results"]] or [f"{_p(k)}: no result"])
        out.append(Paragraph("Evidence gaps", st["h2"]))
        _bullets(out, st, [_p(g) for g in c["evidence_gaps"]])
        out += [Paragraph("Suggested request", st["h2"]), Paragraph(_p(draft["request_text"]), st["body"]),
                Spacer(1, 10), Paragraph(_p(c["disclaimer"]), st["meta"])]
        return out
    return _doc(story)
