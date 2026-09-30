"""
Phase 5 — Investigation Automation: case summary, evidence-gap analysis, timeline, investigation report, alert-draft
content, export bundle and the investigator-controlled workflow status.

Everything is assembled from stored records through the Phase 3 graph (`graph_sync.load_graph`: Neo4j or fallback)
and the Phase 3 Graph RAG categorisation (`graph_rag.retrieve` / `graph_rag.evidence_gaps`), both used read-only,
plus the Phase 4 ML results. Every item carries the ids of the records it came from.

Integrity rules: nothing is fabricated; missing information is reported as a gap, never filled; statuses are copied
(inferred stays inferred, unknown stays unknown); ML output is labelled analysis; no person/entity is named as
responsible; nothing is sent anywhere; ML never changes the workflow status.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.automation import AuditEvent
from app.models.incident import Incident
from app.models.source import UPLOAD_SOURCE_PLATFORM
from app.services import graph_rag, ml_intelligence
from app.services import knowledge_graph as kg

# --------------------------------------------------------------------------- workflow (investigator-controlled)
# Phase 5 states mapped onto the existing Incident.status codes (no schema change; existing screens keep working).
WORKFLOW = [
    ("new", "New", ("created",)),
    ("analyzing", "Analyzing", ("analyzing", "fingerprinted")),
    ("evidence_collected", "Evidence Collected", ("evidence_building",)),
    ("review_required", "Review Required", ("gap_reviewed",)),
    ("report_ready", "Report Ready", ("report_generated",)),
    ("closed", "Closed", ("closed",)),
]
WORKFLOW_KEYS = [w[0] for w in WORKFLOW]
_CANONICAL = {"new": "created", "analyzing": "analyzing", "evidence_collected": "evidence_building",
              "review_required": "gap_reviewed", "report_ready": "report_generated", "closed": "closed"}
_LABEL = {k: label for k, label, _ in WORKFLOW}

DISCLAIMER = ("This document is an investigative aid built from recorded evidence. It does not establish the identity, "
              "intent or responsibility of any person or entity. Inferences, unknowns and ML analysis are labelled as such "
              "and are not findings of fact.")
ALERT_BANNER = "DRAFT — REQUIRES INVESTIGATOR REVIEW"


def workflow_state(status: str | None) -> str:
    for key, _, codes in WORKFLOW:
        if status in codes:
            return key
    return "new"


def workflow_info(incident: Incident) -> dict:
    key = workflow_state(incident.status)
    return {"state": key, "label": _LABEL[key], "stored_status": incident.status,
            "states": [{"key": k, "label": label} for k, label, _ in WORKFLOW],
            "controlled_by": "investigator", "note": "ML analysis never changes this status."}


def set_workflow(incident: Incident, key: str) -> tuple[str, str]:
    """Returns (old_status, new_status). Caller records the audit event. Only called from the investigator endpoint."""
    if key not in _CANONICAL:
        raise ValueError(f"Unknown workflow state '{key}'. Allowed: {', '.join(WORKFLOW_KEYS)}.")
    old = incident.status
    incident.status = _CANONICAL[key]
    return old, incident.status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _gid(*parts: str) -> str:
    return "gap:" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _code(n: dict) -> str:
    return n["metadata"].get("code") or n["label"]


# --------------------------------------------------------------------------- building blocks
def _media(g: kg.KnowledgeGraph) -> list[dict]:
    out = []
    for m in g.nodes(types=["media"]):
        md = m["metadata"]
        det, fps, ev = [], [], []
        for r in g.connected(m["id"])["relationships"]:
            other = g.get_node(r["target"])
            if r["type"] == "ANALYZED_BY":
                d = other["metadata"]
                det.append({"detection_id": d["record_id"], "model_name": d.get("model_name"),
                            "manipulation_likelihood": d.get("manipulation_likelihood"), "likely_technique": d.get("likely_technique"),
                            "created_at": d.get("created_at"),
                            "note": "A model score, not a finding of fact." + (" Pixel-heuristic fallback, not a trained classifier."
                                                                               if "fallback" in (d.get("model_name") or "").lower() else "")})
            elif r["type"] == "HAS_FINGERPRINT":
                fps.append({"fingerprint_id": other["metadata"]["record_id"], "average_hash": other["metadata"].get("average_hash")})
            elif r["type"] == "SUPPORTED_BY":
                ev.append(other["metadata"]["record_id"])
        out.append({"media_id": md["record_id"], "node_id": m["id"], "filename": md.get("filename"), "kind": md.get("kind"),
                    "uploaded_at": md.get("uploaded_at"), "detections": det, "fingerprints": fps, "evidence_ids": ev})
    return out


def _sources(g: kg.KnowledgeGraph, incident_id: str) -> list[dict]:
    out = []
    for n in g.nodes(types=["source"]):
        sc = ml_intelligence.source_context(g, n["id"], incident_id)
        sc["is_seeded"] = n["metadata"].get("is_seeded")
        sc["similarity"] = n["metadata"].get("similarity")
        out.append(sc)
    return sorted(out, key=lambda s: s["code"] or "")


def _locations(g: kg.KnowledgeGraph) -> list[dict]:
    out = []
    for n in g.nodes(types=["location"]):
        m = n["metadata"]
        links = [{"source_node": r["source"], "source_code": _code(g.get_node(r["source"])), "status": r["status"],
                  "confidence": r["confidence"], "provenance": r["metadata"].get("provenance"), "evidence_id": r.get("evidence_id")}
                 for r in g.connected(n["id"])["relationships"] if r["type"] == "LOCATED_AT"]
        out.append({"location_node_id": n["id"], "map_node_id": m.get("map_node_id"), "label": n["label"],
                    "latitude": m.get("latitude"), "longitude": m.get("longitude"), "city": m.get("city"), "region": m.get("region"),
                    "country": m.get("country"), "tier": m.get("tier"), "confidence": m.get("confidence"), "links": links})
    return out


def _propagation(g: kg.KnowledgeGraph) -> list[dict]:
    out = []
    for r in g.relationships(types=["PROPAGATES_TO", "RELATED_TO"]):
        md = r["metadata"]
        out.append({"relationship_graph_id": r["id"], "relationship_id": md.get("relationship_id"), "type": r["type"],
                    "status": r["status"], "from": md.get("from_code"), "to": md.get("to_code"), "from_node": r["source"],
                    "to_node": r["target"], "relationship_type": md.get("relationship_type"), "confidence": r["confidence"],
                    "basis": md.get("basis"), "timestamp": r["timestamp"], "endpoint_evidence_ids": md.get("endpoint_evidence_ids") or []})
    return out


def _evidence(g: kg.KnowledgeGraph) -> list[dict]:
    return [{"evidence_id": e["metadata"]["record_id"], "node_id": e["id"], "code": e["metadata"].get("code"),
             "item_type": e["metadata"].get("item_type"), "captured_at": e["metadata"].get("captured_at"),
             "source_id": e["metadata"].get("source_id"), "has_file": e["metadata"].get("has_file"), "notes": e["metadata"].get("notes")}
            for e in g.nodes(types=["evidence"])]


def _fact(f: dict) -> dict:
    return {k: f[k] for k in ("statement", "category", "status", "relationship_ids", "node_ids", "evidence_ids", "source_ids", "location_ids")}


def reviewed_targets(db: Session, incident_id: str) -> dict[str, dict]:
    rows = (db.query(AuditEvent).filter(AuditEvent.incident_id == incident_id,
                                        AuditEvent.action.in_(("finding_reviewed", "evidence_reviewed")))
            .order_by(AuditEvent.created_at).all())
    return {r.target_id: {"at": r.created_at.isoformat() + "Z", "by": r.actor_email} for r in rows if r.target_id}


def ml_digest(ml: dict, reviewed: dict | None = None) -> dict:
    """Compact, provenance-preserving view of the three ML analyses for summaries/reports/drafts."""
    reviewed = reviewed or {}

    def item(r: dict) -> dict:
        return {"id": r["id"], "kind": r["kind"], "type": r.get("type"), "score": r["score"], "label": r.get("label") or r.get("title"),
                "explanation": r["explanation"], "model_name": r["provenance"]["model_name"], "model_version": r["provenance"]["model_version"],
                "computed_at": r["provenance"]["computed_at"],
                "evidence_ids": (r.get("evidence_refs") or {}).get("evidence_ids") or r.get("evidence_ids") or [],
                "source_ids": r.get("source_ids") or sorted({s["source_id"] for side in ("media", "match") for s in (r.get(side) or {}).get("sources", [])}
                                                            | {s["source_id"] for s in r.get("sources", [])}),
                "reviewed": reviewed.get(r["id"]), "nature": "ML analysis — an observation, not a fact"}

    return {k: {"status": v["status"], "message": v.get("message"), "model_name": v["provenance"]["model_name"],
                "model_version": v["provenance"]["model_version"], "computed_at": v["computed_at"],
                "disclaimer": v["disclaimer"], "results": [item(r) for r in v["results"]]} for k, v in ml.items()}


# --------------------------------------------------------------------------- gap analysis
def gap_analysis(g: kg.KnowledgeGraph, *, ml: dict | None = None, reviewed: dict | None = None) -> list[dict]:
    """Phase 3 evidence gaps + Phase 5 gaps. Only what the records do NOT contain; nothing is guessed."""
    gaps = []
    for gp in graph_rag.evidence_gaps(g):
        gaps.append({**gp, "id": _gid(gp["kind"], gp["gap"]), "origin": "graph"})
    srcs = sorted(g.nodes(types=["source"]), key=lambda n: n["metadata"].get("observed_at") or "")
    if srcs:
        e = srcs[0]
        gaps.append({"id": _gid("original_source", e["id"]), "kind": "original_source_not_established", "origin": "automation",
                     "gap": f"The original source has not been established. {_code(e)} is only the earliest recorded observation.",
                     "node_ids": [e["id"]]})
    for ev in g.nodes(types=["evidence"]):
        if not ev["metadata"].get("captured_at"):
            gaps.append({"id": _gid("ts_ev", ev["id"]), "kind": "timestamp_unavailable", "origin": "automation",
                         "gap": f"{_code(ev)} has no capture timestamp.", "node_ids": [ev["id"]]})
    for m in g.nodes(types=["media"]):
        if not m["metadata"].get("uploaded_at"):
            gaps.append({"id": _gid("ts_media", m["id"]), "kind": "timestamp_unavailable", "origin": "automation",
                         "gap": f"Media '{m['label']}' has no upload timestamp.", "node_ids": [m["id"]]})
    for r in g.relationships(types=["LOCATED_AT"]):
        if r["status"] != "verified":
            s = g.get_node(r["source"])
            gaps.append({"id": _gid("loc_unverified", r["id"]), "kind": "location_unverified", "origin": "automation",
                         "gap": f"The location of {_code(s)} ({g.get_node(r['target'])['label']}) is {r['status'].replace('_', ' ')}, not verified.",
                         "node_ids": [r["source"], r["target"]], "relationship_id": r["id"]})
    for s in g.nodes(types=["source"]):
        cnt = s["metadata"].get("evidence_count") or 0
        if cnt == 1:
            gaps.append({"id": _gid("corroboration", s["id"]), "kind": "insufficient_corroboration", "origin": "automation",
                         "gap": f"{_code(s)} is supported by a single evidence item; no corroborating evidence is recorded.",
                         "node_ids": [s["id"]]})
    if ml:
        reviewed = reviewed or {}
        for key in ("similarity", "anomalies", "clusters"):
            for r in ml[key]["results"]:
                if r["id"] not in reviewed:
                    gaps.append({"id": _gid("ml_unreviewed", r["id"]), "kind": "ml_finding_unreviewed", "origin": "ml",
                                 "gap": f"ML finding {r['id']} ({r.get('label') or r.get('title')}) has not been reviewed by an investigator.",
                                 "node_ids": [], "finding_id": r["id"]})
            if ml[key]["status"] == "insufficient_data":
                gaps.append({"id": _gid("ml_insufficient", key), "kind": "ml_insufficient_data", "origin": "ml",
                             "gap": f"ML {key}: {ml[key]['message']}", "node_ids": []})
    return gaps


# --------------------------------------------------------------------------- timeline
def timeline(g: kg.KnowledgeGraph) -> dict:
    """Chronological events from stored timestamps only. basis: OBSERVED | RECORDED | CONFIRMED | INFERRED | UNKNOWN."""
    events, undated = [], []

    def add(ts, **e):
        (events if ts else undated).append({"timestamp": ts, **e})

    loc_of = {}
    for r in g.relationships(types=["LOCATED_AT"]):
        loc_of[r["source"]] = {"location_node_id": r["target"], "label": g.get_node(r["target"])["label"],
                               "map_node_id": g.get_node(r["target"])["metadata"].get("map_node_id"), "status": r["status"]}
    for m in _media(g):
        add(m["uploaded_at"], event="Media uploaded to LINEAGE", basis="OBSERVED", source=None, platform=None, location=None,
            node_ids=[m["node_id"]], evidence_ids=m["evidence_ids"], record_id=m["media_id"])
        for d in m["detections"]:
            lik = d["manipulation_likelihood"]
            add(d["created_at"], event=f"Detection by {d['model_name']}: manipulation likelihood "
                + ("not recorded" if lik is None else f"{lik:.0f}%") + " (model score, not a finding)", basis="RECORDED",
                source=None, platform=None, location=None, node_ids=[m["node_id"], f"detection:{d['detection_id']}"], evidence_ids=[],
                record_id=d["detection_id"])
    for s in g.nodes(types=["source"]):
        md = s["metadata"]
        ev = [g.get_node(r["target"])["metadata"]["record_id"] for r in g.connected(s["id"])["relationships"] if r["type"] == "SUPPORTED_BY"]
        add(md.get("observed_at"), event=f"{_code(s)} observed on {md.get('platform') or 'unknown platform'}", basis="OBSERVED",
            source={"code": _code(s), "source_id": md["record_id"], "node_id": s["id"]}, platform=md.get("platform"),
            location=loc_of.get(s["id"]), node_ids=[s["id"]], evidence_ids=ev, record_id=md["record_id"])
    for e in g.nodes(types=["evidence"]):
        md = e["metadata"]
        snode = f"source:{md['source_id']}" if md.get("source_id") and g.has_node(f"source:{md['source_id']}") else None
        add(md.get("captured_at"), event=f"{_code(e)} captured ({(md.get('item_type') or 'evidence').replace('_', ' ')})", basis="OBSERVED",
            source={"code": _code(g.get_node(snode)), "source_id": md["source_id"], "node_id": snode} if snode else None,
            platform=g.get_node(snode)["metadata"].get("platform") if snode else None, location=loc_of.get(snode) if snode else None,
            node_ids=[e["id"]] + ([snode] if snode else []), evidence_ids=[md["record_id"]], record_id=md["record_id"])
    for r in g.relationships(types=["LOCATED_AT"]):
        s = g.get_node(r["source"])
        add(r["timestamp"], event=f"Location recorded for {_code(s)}: {g.get_node(r['target'])['label']} ({r['status'].replace('_', ' ')})",
            basis="RECORDED", source={"code": _code(s), "source_id": s["metadata"]["record_id"], "node_id": s["id"]},
            platform=s["metadata"].get("platform"), location=loc_of.get(s["id"]), node_ids=[r["source"], r["target"]],
            evidence_ids=[r["evidence_id"]] if r.get("evidence_id") else [], record_id=r["metadata"].get("record_id"))
    for p in _propagation(g):
        t = g.get_node(p["to_node"])
        basis = {"confirmed": "CONFIRMED", "inferred": "INFERRED"}.get(p["status"], "UNKNOWN")
        what = {"CONFIRMED": f"Propagation {p['from']} → {p['to']} (direction confirmed by investigator)",
                "INFERRED": f"Propagation {p['from']} → {p['to']} (inferred from timestamps; not confirmed)",
                "UNKNOWN": f"{p['from']} and {p['to']} related ('{p['relationship_type']}'); direction unknown"}[basis]
        add(p["timestamp"], event=what, basis=basis, source={"code": p["to"], "source_id": t["metadata"]["record_id"], "node_id": p["to_node"]},
            platform=t["metadata"].get("platform"), location=loc_of.get(p["to_node"]), node_ids=[p["from_node"], p["to_node"]],
            evidence_ids=p["endpoint_evidence_ids"], record_id=p["relationship_id"], relationship_graph_id=p["relationship_graph_id"],
            status=p["status"])
    events.sort(key=lambda e: e["timestamp"])
    return {"events": events, "undated": undated,
            "legend": {"OBSERVED": "A stored observation/capture/upload time.", "RECORDED": "When LINEAGE or an investigator recorded an analysis or attribute.",
                       "CONFIRMED": "Relationship direction confirmed by an investigator.", "INFERRED": "Direction inferred from timestamps; not confirmed.",
                       "UNKNOWN": "Relationship recorded but its direction is unknown."}}


# --------------------------------------------------------------------------- summary
def build_summary(incident: Incident, db: Session, *, ml: dict | None = None, scope: str = "owner") -> dict:
    with ml_intelligence.graph_memo():      # one graph build/sync per investigation per request
        return _build_summary(incident, db, ml=ml, scope=scope)


def _build_summary(incident: Incident, db: Session, *, ml: dict | None = None, scope: str = "owner") -> dict:
    g, src = ml_intelligence.load_graph(incident, db)
    ml = ml if ml is not None else ml_intelligence.run_all(incident, db, scope=scope)
    reviewed = reviewed_targets(db, incident.id)
    r = graph_rag.retrieve(g, "")          # no intent -> every Phase 3 retrieval handler, facts categorised by stored status
    facts = r["ctx"].facts
    return {
        "investigation": {"id": incident.id, "title": incident.title, "description": incident.description,
                          "created_at": incident.created_at.isoformat() + "Z" if incident.created_at else None,
                          "workflow": workflow_info(incident)},
        "graph_source": src,
        "media": _media(g),
        "detection_results": [d for m in _media(g) for d in m["detections"]],
        "sources": _sources(g, incident.id),
        "platforms": [{"platform": p["label"], "source_count": p["metadata"].get("source_count")} for p in g.nodes(types=["platform"])],
        "locations": _locations(g),
        "propagation": {"relationships": _propagation(g), "paths": r["ctx"].paths},
        "ml_findings": ml_digest(ml, reviewed),
        "evidence": _evidence(g),
        "verified_facts": [_fact(f) for f in facts if f["category"] == "VERIFIED_FACT"],
        "inferences": [_fact(f) for f in facts if f["category"] == "INFERENCE"],
        "unknowns": [_fact(f) for f in facts if f["category"] == "UNKNOWN"],
        "evidence_gaps": gap_analysis(g, ml=ml, reviewed=reviewed),
        "stats": g.stats(), "generated_at": _now(), "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------------- report
_ACTIONS = {
    "source_without_evidence": "Preserve evidence (screenshot/archive with capture time) for {codes} before the content changes or is removed.",
    "location_unverified": "Seek corroborating metadata (e.g. EXIF or platform-provided data) for the recorded location of {codes}; treat it as unverified until then.",
    "source_without_location": "Record a location for {codes} only if metadata or a documented investigator finding supports one; do not estimate.",
    "direction_not_confirmed": "Review timestamps and content to confirm or reject the inferred propagation direction(s) involving {codes}.",
    "direction_unknown": "Examine the related sources {codes} to determine whether a propagation direction can be established.",
    "missing_detection": "Run detection on the media items without a stored result.",
    "missing_fingerprint": "Run fingerprinting on the media items without a stored fingerprint.",
    "insufficient_corroboration": "Collect corroborating evidence for {codes}.",
    "original_source_not_established": "If attribution of the original upload is required, request account and upload records through the appropriate platform legal process or law-enforcement channel. Do not treat the earliest observed source as the originator.",
    "ml_finding_unreviewed": "Review the ML findings listed under ML Intelligence; they are analysis, not evidence, and should be accepted or dismissed by an investigator.",
}


def _recommendations(gaps: list[dict], g: kg.KnowledgeGraph) -> list[dict]:
    by_kind: dict[str, list[dict]] = {}
    for gp in gaps:
        by_kind.setdefault(gp["kind"], []).append(gp)
    out = []
    for kind, template in _ACTIONS.items():
        items = by_kind.get(kind)
        if not items:
            continue
        nodes = [n for gp in items for n in gp.get("node_ids", []) if n.startswith("source:") and g.has_node(n)]
        codes = ", ".join(dict.fromkeys(_code(g.get_node(n)) for n in nodes)) or "the listed items"
        out.append({"action": template.format(codes=codes), "basis_gap_ids": [gp["id"] for gp in items], "kind": kind})
    return out


def build_report(incident: Incident, db: Session, *, user=None, version: int = 1, summary: dict | None = None) -> dict:
    with ml_intelligence.graph_memo():
        return _build_report(incident, db, user=user, version=version, summary=summary)


def _build_report(incident: Incident, db: Session, *, user=None, version: int = 1, summary: dict | None = None) -> dict:
    s = summary or build_summary(incident, db)
    g, _ = ml_intelligence.load_graph(incident, db)
    locs = s["locations"]
    tiers = [l2["status"] for l in locs for l2 in l["links"]]
    anomalies_geo = [a for a in s["ml_findings"]["anomalies"]["results"] if a["type"] == "geographic_spread"]
    earliest = next((f for f in s["verified_facts"] if "earliest recorded observation" in f["statement"]), None)
    return {
        "report_type": "LINEAGE investigation report", "version": version, "generated_at": _now(),
        "generated_by": {"user_id": getattr(user, "id", None), "email": getattr(user, "email", None)} if user else None,
        "case_overview": {
            **s["investigation"], "graph_backend": s["graph_source"]["backend"],
            "counts": {"media": len(s["media"]), "sources": len(s["sources"]), "evidence": len(s["evidence"]),
                       "locations": len(locs), "relationships": len(s["propagation"]["relationships"])},
        },
        "evidence_summary": {"evidence": s["evidence"], "media": s["media"], "detection_results": s["detection_results"]},
        "geographic_findings": {
            "locations": locs,
            "tier_counts": {t: tiers.count(t) for t in sorted(set(tiers))},
            "unlocated_sources": [x["code"] for x in s["sources"] if not x["location"]],
            "unusual_patterns": anomalies_geo,
            "note": "Only verified locations come from preserved metadata; investigator-supplied and inferred locations are not verified.",
        },
        "propagation_findings": {
            "relationships": s["propagation"]["relationships"], "paths": s["propagation"]["paths"],
            "earliest_observed": earliest["statement"] if earliest else None,
            "note": "Earliest observed is not the same as original source. Inferred directions are not confirmed.",
        },
        "ml_findings": s["ml_findings"],
        "facts": {"verified": s["verified_facts"], "inferences": s["inferences"], "unknowns": s["unknowns"]},
        "evidence_gaps": s["evidence_gaps"],
        "recommended_actions": _recommendations(s["evidence_gaps"], g),
        "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------------- alert draft
def alert_sufficiency(summary: dict) -> tuple[bool, list[str]]:
    missing = []
    if not summary["media"]:
        missing.append("No media item is recorded.")
    if not summary["evidence"]:
        missing.append("No evidence item is preserved.")
    if not [x for x in summary["sources"] if x["platform"] and x["platform"] != UPLOAD_SOURCE_PLATFORM]:
        missing.append("No external source (a platform where the content was observed) is recorded.")
    return not missing, missing


def build_alert_content(incident: Incident, summary: dict, tl: dict) -> dict:
    external = [x for x in summary["sources"] if x["platform"] and x["platform"] != UPLOAD_SOURCE_PLATFORM]
    return {
        "banner": ALERT_BANNER,
        "transmission": "not_sent — LINEAGE does not transmit drafts. Approval only records the investigator's decision.",
        "investigation_id": incident.id, "investigation_title": incident.title,
        "media": [{"media_id": m["media_id"], "filename": m["filename"], "fingerprint_ids": [f["fingerprint_id"] for f in m["fingerprints"]],
                   "evidence_ids": m["evidence_ids"]} for m in summary["media"]],
        "observed_platforms": sorted({x["platform"] for x in external}),
        "sources": [{"code": x["code"], "source_id": x["source_id"], "platform": x["platform"], "account": x["account"],
                     "observed_at": x["observed_at"]} for x in external],
        "relevant_locations": [{"label": l["label"], "location_node_id": l["location_node_id"], "tier": l["tier"],
                                "statuses": sorted({k["status"] for k in l["links"]})} for l in summary["locations"]],
        "timeline": [{k: e.get(k) for k in ("timestamp", "event", "basis", "evidence_ids")} for e in tl["events"]],
        "evidence_references": [{"evidence_id": e["evidence_id"], "code": e["code"], "item_type": e["item_type"],
                                 "captured_at": e["captured_at"]} for e in summary["evidence"]],
        "detection_findings": summary["detection_results"],
        "ml_findings": {k: {"model": f"{v['model_name']} {v['model_version']}", "status": v["status"],
                            "results": [{"id": r["id"], "score": r["score"], "label": r["label"], "explanation": r["explanation"]} for r in v["results"]],
                            "disclaimer": v["disclaimer"]} for k, v in summary["ml_findings"].items()},
        "evidence_gaps": [g["gap"] for g in summary["evidence_gaps"] if g["origin"] != "ml"],
        "disclaimer": DISCLAIMER,
    }


def default_alert_texts(summary: dict) -> tuple[str, str]:
    ext = [x for x in summary["sources"] if x["platform"] and x["platform"] != UPLOAD_SOURCE_PLATFORM]
    plats = ", ".join(sorted({x["platform"] for x in ext}))
    summary_text = (f"Investigation '{summary['investigation']['title']}' records {len(summary['media'])} media item(s), "
                    f"{len(summary['evidence'])} preserved evidence item(s) and {len(ext)} external source observation(s) on {plats}. "
                    "Details, statuses and evidence references are listed below.")
    request_text = ("Requesting review of the publicly observed posts listed in this draft and, where lawful, preservation of the "
                    "related platform records for further investigation. This draft does not identify or accuse any person or entity.")
    return summary_text, request_text


# --------------------------------------------------------------------------- export
def export_bundle(incident: Incident, db: Session, *, user, summary: dict, tl: dict, report: dict | None,
                  drafts: list[dict], audit_trail: list[dict]) -> dict:
    return {
        "export_format": "lineage-investigation-export", "export_version": "5.0.0", "exported_at": _now(),
        "exported_by": {"user_id": user.id, "email": user.email},
        "investigation_id": incident.id, "summary": summary, "timeline": tl, "latest_report": report,
        "alert_drafts": drafts, "audit_trail": audit_trail,
        "status_legend": {"confirmed/verified/recorded": "VERIFIED FACT", "inferred/incident_scoped/investigator_supplied": "INFERENCE",
                          "unknown": "UNKNOWN"},
        "disclaimer": DISCLAIMER,
    }
