"""
Phase 5 — Investigation Automation API. Nothing here sends anything outside LINEAGE, and nothing edits evidence.

GET   /incidents/{id}/automation/summary                     structured case summary
GET   /incidents/{id}/automation/gaps                        evidence-gap analysis
GET   /incidents/{id}/automation/timeline                    chronological events (OBSERVED / RECORDED / CONFIRMED / INFERRED / UNKNOWN)
POST  /incidents/{id}/automation/reports                     generate a new report version (audited)
GET   /incidents/{id}/automation/reports                     list versions      GET .../reports/latest     GET .../reports/{rid}/pdf
POST  /incidents/{id}/automation/alert-drafts                generate a reviewable draft (422 if evidence is insufficient)
GET   /incidents/{id}/automation/alert-drafts                list               PATCH .../alert-drafts/{did}   (edit free text)
POST  /incidents/{id}/automation/alert-drafts/{did}/approve  record approval (does NOT send)
GET   /incidents/{id}/automation/alert-drafts/{did}/export   ?format=json|pdf (does NOT send)
GET   /incidents/{id}/automation/export                      ?format=json|pdf full investigation export
GET   /incidents/{id}/workflow      PUT /incidents/{id}/workflow   investigator-controlled status
POST  /incidents/{id}/reviews                                record an evidence / finding review (audit only)
GET   /incidents/{id}/audit                                  audit trail
"""
import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.automation import AlertDraft, InvestigationReport
from app.models.source import EvidenceItem
from app.models.user import User
from app.routers.incidents import _get_owned_incident
from app.services import audit, case_automation as ca
from app.services.automation_pdf import render_alert_draft_pdf, render_investigation_report_pdf
from app.services.ml_intelligence import graph_memo, load_graph as cached_load_graph

router = APIRouter(prefix="/incidents", tags=["automation"])
log = logging.getLogger("uvicorn.error")


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _render_pdf(render, payload) -> bytes:
    """PDF rendering failures become a clear 500 message (details go to the server log, never to the client)."""
    try:
        return render(payload)
    except Exception:  # noqa: BLE001
        log.exception("PDF rendering failed")
        raise HTTPException(status_code=500, detail="PDF generation failed. The JSON export is still available.")


# ------------------------------------------------------------------ summary / gaps / timeline
@router.get("/{incident_id}/automation/summary")
def summary(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ca.build_summary(_get_owned_incident(incident_id, db, current_user), db)


@router.get("/{incident_id}/automation/gaps")
def gaps(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    s = ca.build_summary(inc, db)
    return {"investigation_id": inc.id, "gaps": s["evidence_gaps"], "count": len(s["evidence_gaps"]), "generated_at": s["generated_at"]}


@router.get("/{incident_id}/automation/timeline")
def get_timeline(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    g, src = cached_load_graph(inc, db)
    return {"investigation_id": inc.id, "graph_source": src, **ca.timeline(g)}


# ------------------------------------------------------------------ reports
def _report_out(r: InvestigationReport) -> dict:
    return {"id": r.id, "incident_id": r.incident_id, "version": r.version, "generated_at": _iso(r.generated_at),
            "generated_by": r.generated_by, "report": json.loads(r.report_json)}


@router.post("/{incident_id}/automation/reports", status_code=201)
def generate_report(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    version = (db.query(func.max(InvestigationReport.version)).filter(InvestigationReport.incident_id == inc.id).scalar() or 0) + 1
    rep = ca.build_report(inc, db, user=current_user, version=version)
    row = InvestigationReport(incident_id=inc.id, version=version, generated_by=current_user.id,
                              generated_at=datetime.utcnow(), report_json=json.dumps(rep, default=str))
    db.add(row)
    db.flush()
    audit.record(db, inc.id, current_user, "report_generated", target_type="report", target_id=row.id,
                 details={"version": version}, commit=False)
    db.commit()           # the workflow status is NOT changed here — the investigator sets it
    return _report_out(row)


@router.get("/{incident_id}/automation/reports")
def list_reports(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    rows = db.query(InvestigationReport).filter(InvestigationReport.incident_id == inc.id).order_by(InvestigationReport.version.desc()).all()
    return [{"id": r.id, "version": r.version, "generated_at": _iso(r.generated_at), "generated_by": r.generated_by} for r in rows]


def _latest(inc_id: str, db: Session) -> InvestigationReport | None:
    return (db.query(InvestigationReport).filter(InvestigationReport.incident_id == inc_id)
            .order_by(InvestigationReport.version.desc()).first())


@router.get("/{incident_id}/automation/reports/latest")
def latest_report(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    r = _latest(inc.id, db)
    if not r:
        raise HTTPException(status_code=404, detail="No investigation report yet — generate one first.")
    return _report_out(r)


@router.get("/{incident_id}/automation/reports/{report_id}/pdf")
def report_pdf(incident_id: str, report_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    r = db.query(InvestigationReport).filter(InvestigationReport.id == report_id, InvestigationReport.incident_id == inc.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found.")
    return Response(_render_pdf(render_investigation_report_pdf, json.loads(r.report_json)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="investigation-report-{inc.id[:8]}-v{r.version}.pdf"'})


# ------------------------------------------------------------------ alert drafts
def _users(db: Session, ids) -> dict:
    ids = [i for i in ids if i]
    return {u.id: u.email for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}


def _draft_out(d: AlertDraft, db: Session) -> dict:
    emails = _users(db, [d.created_by, d.approved_by])
    return {"id": d.id, "incident_id": d.incident_id, "status": d.status, "banner": ca.ALERT_BANNER,
            "content": json.loads(d.content_json), "summary_text": d.summary_text, "request_text": d.request_text,
            "created_by": d.created_by, "created_by_email": emails.get(d.created_by), "created_at": _iso(d.created_at),
            "updated_at": _iso(d.updated_at), "approved_by": d.approved_by, "approved_by_email": emails.get(d.approved_by),
            "approved_at": _iso(d.approved_at), "exported_at": _iso(d.exported_at), "sent": False}


def _get_draft(inc_id: str, draft_id: str, db: Session) -> AlertDraft:
    d = db.query(AlertDraft).filter(AlertDraft.id == draft_id, AlertDraft.incident_id == inc_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Alert draft not found.")
    return d


@router.post("/{incident_id}/automation/alert-drafts", status_code=201)
def create_draft(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    with graph_memo():                    # one graph build/sync for the summary and the timeline
        s = ca.build_summary(inc, db)
        ok, missing = ca.alert_sufficiency(s)
        if not ok:
            raise HTTPException(status_code=422, detail={"message": "Insufficient evidence for an alert draft.", "missing": missing})
        g, _ = cached_load_graph(inc, db)
        content = ca.build_alert_content(inc, s, ca.timeline(g))
    summary_text, request_text = ca.default_alert_texts(s)
    now = datetime.utcnow()
    d = AlertDraft(incident_id=inc.id, status="draft", content_json=json.dumps(content, default=str), summary_text=summary_text,
                   request_text=request_text, created_by=current_user.id, created_at=now, updated_at=now)
    db.add(d)
    db.flush()
    audit.record(db, inc.id, current_user, "alert_draft_generated", target_type="alert_draft", target_id=d.id, commit=False)
    db.commit()
    return _draft_out(d, db)


@router.get("/{incident_id}/automation/alert-drafts")
def list_drafts(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    rows = db.query(AlertDraft).filter(AlertDraft.incident_id == inc.id).order_by(AlertDraft.created_at.desc()).all()
    return [_draft_out(d, db) for d in rows]


class DraftEdit(BaseModel):
    summary_text: str | None = Field(default=None, max_length=5000)
    request_text: str | None = Field(default=None, max_length=5000)


@router.patch("/{incident_id}/automation/alert-drafts/{draft_id}")
def edit_draft(incident_id: str, draft_id: str, payload: DraftEdit, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    d = _get_draft(inc.id, draft_id, db)
    changed = [k for k in ("summary_text", "request_text") if getattr(payload, k) is not None]
    if not changed:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    for k in changed:
        setattr(d, k, getattr(payload, k))
    was_approved = d.status == "approved"
    d.status, d.approved_by, d.approved_at, d.updated_at = "draft", None, None, datetime.utcnow()   # edits require re-approval
    audit.record(db, inc.id, current_user, "alert_draft_edited", target_type="alert_draft", target_id=d.id,
                 details={"fields": changed, "approval_reset": was_approved}, commit=False)
    db.commit()
    return _draft_out(d, db)


@router.post("/{incident_id}/automation/alert-drafts/{draft_id}/approve")
def approve_draft(incident_id: str, draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    d = _get_draft(inc.id, draft_id, db)
    d.status, d.approved_by, d.approved_at = "approved", current_user.id, datetime.utcnow()
    audit.record(db, inc.id, current_user, "alert_draft_approved", target_type="alert_draft", target_id=d.id,
                 details={"sent": False, "note": "Approval records the investigator's decision only; nothing was transmitted."}, commit=False)
    db.commit()
    return _draft_out(d, db)


@router.get("/{incident_id}/automation/alert-drafts/{draft_id}/export")
def export_draft(incident_id: str, draft_id: str, format: Literal["json", "pdf"] = "json",
                 db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    d = _get_draft(inc.id, draft_id, db)
    d.exported_at = datetime.utcnow()
    audit.record(db, inc.id, current_user, "alert_draft_exported", target_type="alert_draft", target_id=d.id,
                 details={"format": format, "sent": False}, commit=False)
    db.commit()
    out = _draft_out(d, db)
    name = f"alert-draft-{inc.id[:8]}-{d.id[:8]}"
    if format == "pdf":
        return Response(_render_pdf(render_alert_draft_pdf, out), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return JSONResponse(out, headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


# ------------------------------------------------------------------ full export
@router.get("/{incident_id}/automation/export")
def export_investigation(incident_id: str, format: Literal["json", "pdf"] = "json",
                         db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    with graph_memo():                    # one graph build/sync for summary, report and timeline
        return _export(inc, format, db, current_user)


def _export(inc, format: str, db: Session, current_user: User):
    s = ca.build_summary(inc, db)
    latest = _latest(inc.id, db)
    report = json.loads(latest.report_json) if latest else None
    name = f"lineage-investigation-{inc.id[:8]}"
    if format == "pdf":
        rep = report or ca.build_report(inc, db, user=current_user, version=0, summary=s)   # version 0 = unsaved, export-only
        content = _render_pdf(render_investigation_report_pdf, rep)
        _audit_export(db, inc, current_user, format, latest)
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    g, _ = cached_load_graph(inc, db)
    drafts = [_draft_out(d, db) for d in db.query(AlertDraft).filter(AlertDraft.incident_id == inc.id).all()]
    _audit_export(db, inc, current_user, format, latest)
    bundle = ca.export_bundle(inc, db, user=current_user, summary=s, tl=ca.timeline(g), report=report, drafts=drafts,
                              audit_trail=audit.list_events(db, inc.id))
    return JSONResponse(json.loads(json.dumps(bundle, default=str)), headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


def _audit_export(db: Session, inc, user: User, format: str, latest) -> None:
    audit.record(db, inc.id, user, "investigation_exported", target_type="incident", target_id=inc.id,
                 details={"format": format, "report_version": latest.version if latest else None})


# ------------------------------------------------------------------ workflow status
class WorkflowIn(BaseModel):
    state: str
    note: str | None = Field(default=None, max_length=1000)


@router.get("/{incident_id}/workflow")
def get_workflow(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ca.workflow_info(_get_owned_incident(incident_id, db, current_user))


@router.put("/{incident_id}/workflow")
def put_workflow(incident_id: str, payload: WorkflowIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    try:
        old, new = ca.set_workflow(inc, payload.state)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    audit.record(db, inc.id, current_user, "status_changed", target_type="incident", target_id=inc.id,
                 details={"from": old, "to": new, "state": payload.state, "note": payload.note}, commit=False)
    db.commit()
    return ca.workflow_info(inc)


# ------------------------------------------------------------------ reviews + audit
class ReviewIn(BaseModel):
    target_type: Literal["evidence", "ml_finding", "report_finding", "gap"]
    target_id: str = Field(..., min_length=1, max_length=200)
    decision: Literal["reviewed", "accepted", "dismissed", "needs_follow_up"] = "reviewed"
    note: str | None = Field(default=None, max_length=2000)


@router.post("/{incident_id}/reviews", status_code=201)
def record_review(incident_id: str, payload: ReviewIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Records that an investigator reviewed something. The reviewed record itself is never modified."""
    inc = _get_owned_incident(incident_id, db, current_user)
    if payload.target_type == "evidence":
        if not db.query(EvidenceItem).filter(EvidenceItem.id == payload.target_id, EvidenceItem.incident_id == inc.id).first():
            raise HTTPException(status_code=404, detail="Evidence item not found in this investigation.")
        action = "evidence_reviewed"
    else:
        if payload.target_type == "ml_finding" and payload.target_id.split(":")[0] not in ("similarity", "anomaly", "cluster"):
            raise HTTPException(status_code=422, detail="Unknown ML finding id.")
        action = "finding_reviewed"
    ev = audit.record(db, inc.id, current_user, action, target_type=payload.target_type, target_id=payload.target_id,
                      details={"decision": payload.decision, "note": payload.note})
    return audit.to_dict(ev)


@router.get("/{incident_id}/audit")
def get_audit(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inc = _get_owned_incident(incident_id, db, current_user)
    return {"investigation_id": inc.id, "events": audit.list_events(db, inc.id)}
