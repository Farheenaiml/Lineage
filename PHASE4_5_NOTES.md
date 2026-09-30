# Phase 4 (ML Intelligence) + Phase 5 (Investigation Automation)

Phase 3 is frozen and was not modified: `neo4j_service`, `graph_store`, `graph_sync`, `graph_rag`, `knowledge_graph`, the `graph` and `copilot` routers, and `InvestigationCopilot`. Phases 4 and 5 read the graph through `graph_sync.load_graph()` (Neo4j, or the in-memory fallback) and reuse `graph_rag.retrieve()` and `evidence_gaps()` read-only.

## Files
Backend, new:
- `app/models/automation.py`: `AuditEvent`, `InvestigationReport`, `AlertDraft`; additive tables created by `create_all`
- Services: `ml_intelligence.py`, `case_automation.py`, `audit.py`, `automation_pdf.py`
- Routers: `ml.py`, `automation.py`
- Tests: `test_ml_intelligence.py`, `test_case_automation.py`, `test_phase45_integration.py`

Backend, modified:
- `core/config.py`: `ML_*` thresholds
- `main.py`: routers registered
- `models/__init__.py`
- `routers/geo.py`: audit on location add/edit/delete and direction confirm/revoke only
- `routers/reports.py`: audit on legacy report generation only

Frontend, new: `components/ml/MLIntelligence.tsx`, `screens/CaseAutomation.tsx`, `lib/focus.ts`.
Frontend, modified:
- `lib/api.ts`
- `screens/LineageMap.tsx`: "ML Intelligence" tab, plus a one-time focus handoff from other screens
- `App.tsx`, `components/Sidebar.tsx` and `components/InvestigationLayout.tsx`: "Case Automation" tab and route

## ML (local, deterministic, NumPy only; no new dependencies)
- **Similarity:** Hamming similarity of the stored 64-bit aHash (keyframe hashes for video) gives the score. Stored FaceNet embedding cosine is reported as a separate factor and never changes the score. Wording is always "visually similar"; results never say "the same".
- **Anomalies:** unusual patterns measured against the investigation's own median intervals only:
  - observation bursts: ≥3 consecutive observations with intervals under `ML_BURST_RATIO` × the median
  - rapid propagation: a relationship gap under the ratio × the median gap, from ≥3 timed relationships
  - geographic spread: ≥3 distinct locations more than `ML_GEO_SPREAD_KM` apart within one median interval

  Detectors without enough data return "Insufficient data."
- **Clusters:** single-linkage connected components at `ML_CLUSTER_THRESHOLD`. They include linked sources (with their APPEARS_IN status), platforms, locations and evidence, and make no identity or ownership inference.
- **Scope:** `scope=owner` (the default) compares across the same investigator's investigations only. `scope=investigation` stays inside one case.
- **Provenance:** every result carries model name, version, `computed_at`, score, factors, evidence references and the graph backend. Finding ids are deterministic hashes of their members, so a review stays attached across recomputes. ML writes nothing.

## Automation
- **Workflow:** New / Analyzing / Evidence Collected / Review Required / Report Ready / Closed, mapped onto the existing `Incident.status` codes. It changes only through `PUT /workflow`, which is audited. ML never changes it, and the new report endpoint doesn't either.
- **Timeline:** built from stored timestamps only, labelled OBSERVED / RECORDED / CONFIRMED / INFERRED / UNKNOWN. Items without a timestamp are listed separately as undated.
- **Report:** versioned. Each recommendation cites the gap ids it comes from, and the text avoids accusatory language.
- **Alert draft:** carries "DRAFT — REQUIRES INVESTIGATOR REVIEW". It requires media, evidence and at least one external source, otherwise the request returns 422. Editing resets approval. Approve and export only record the action; nothing is sent.
- **Export:** JSON bundle (summary, timeline, latest report, drafts, audit trail, status legend) or PDF.
- **Audit:** the actor is the authenticated user. Reviews go to `POST /reviews` and never edit the reviewed record.

## Environment
`ML_SIMILARITY_THRESHOLD=0.75`, `ML_CLUSTER_THRESHOLD=0.85`, `ML_ANOMALY_MIN_OBSERVATIONS=4`, `ML_ANOMALY_MIN_RELATIONSHIPS=3`, `ML_BURST_RATIO=0.25`, `ML_GEO_SPREAD_KM=500`. All are optional; the defaults are shown.
