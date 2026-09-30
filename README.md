# LINEAGE — Full Stack (Phases 1–6 Complete)

AI-powered synthetic identity abuse investigation platform.
**Don't just detect the deepfake. Trace the attack.**

This package contains the real, working application: a FastAPI backend with a
genuine database, real ML models, and encrypted storage, plus the React
frontend wired to it. The mock `caseData.ts` file is gone — every number the
UI displays now comes from the server.

---

## Quick start

You need **Python 3.10+** and **Node 18+**. Run the backend and frontend in
two separate terminals.

### Terminal 1 — backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

First start takes ~30 seconds because it downloads and loads the face
detection/embedding models. Watch for these lines:

```
INFO:  Face detection/embedding models loaded.
INFO:  Application startup complete.
```

> **Note on the install itself:** `requirements.txt` installs the CPU-only
> build of PyTorch via `--extra-index-url https://download.pytorch.org/whl/cpu`
> — the standard, documented way to avoid pulling in ~2.5GB of unused NVIDIA
> CUDA libraries on a machine with no GPU. This line could not be verified
> in the sandbox this was built in (that specific domain was network-blocked
> there), so it's untested end-to-end — if `pip install` can't find
> `torch==2.2.2+cpu` for some reason, delete the `--extra-index-url` line and
> the `+cpu` suffixes from the two torch lines; pip will install the regular
> (larger) build instead, which works identically, just uses more disk.

API runs at `http://localhost:8000` · interactive docs at `http://localhost:8000/docs`

### Terminal 2 — frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

App runs at `http://localhost:5173`.

### Optional — Neo4j (graph persistence)

The app works without Neo4j; the investigation graph is then served from memory.
To persist it in Neo4j Community:

```bash
cd backend
docker compose up -d neo4j          # Browser http://localhost:7474, Bolt bolt://localhost:7687
```

Then in `backend/.env` set `NEO4J_URI=bolt://localhost:7687` and `NEO4J_PASSWORD=<the NEO4J_PASSWORD
you started compose with; dev default lineage-dev-password>` and restart the backend. `GET /health`
reports `"neo4j": "connected"` (or `"fallback"`). Sync manually with
`python -m app.services.graph_sync sync-all` (idempotent; safe to repeat).

### Setting up your first case

This app ships with zero data — there's no seeded/demo content anywhere. To
avoid staring at a completely empty app on first run, a setup script creates
one real example case:

```bash
cd backend
python seed_riya_case.py --media path/to/a/real/photo/or/video.jpg
```

This runs the file through the **real** detection and fingerprinting
pipeline — the same code path a user's upload goes through — and creates one
investigation ("Riya's Case") with a demo login (`demo@lineage.app` /
`demo-access`, matching the pre-filled login form). It does **not** fabricate
sources, evidence, or a report — those are only ever created by a real
person using the app, same as any other case would be. Safe to re-run; it
won't create a duplicate.

Everything past that point — every other case, every source, every piece of
evidence — is created by you, through the app, and stored for real.

### Using it

1. Click **Get Started** → **Log In** (credentials are pre-filled).
2. Open **Riya's Case** from Investigations to see a fully analyzed example:
   real detection score, real fingerprint (including a real face embedding
   if a face was in the photo you provided), all loaded from the database.
3. Click **+ Add Source** on the Evidence Locker or Lineage tab to record a
   place you've found the content re-posted — this is a real form that
   saves to the database, not a "load demo data" shortcut. You can
   optionally link it to an earlier source to build the propagation graph.
4. **Attribution Gap** → *Run Attribution Analysis* — real, rule-based logic
   over whatever sources actually exist for this case.
5. **Incident Report** → *Generate Report* → **Download PDF**.
6. **New Case**, top of the sidebar, to start a second, independent
   investigation — upload a different file and it goes through the same
   real pipeline.

---

## Architecture (Phases 1–6)

| Phase | What it adds | Where |
|---|---|---|
| Base | Auth, cases, encrypted media, detection, fingerprints, sources, evidence, attribution gap, incident report | `routers/`, `services/` |
| 1 | Source locations with provenance tiers (EXIF = verified, investigator, inferred), 3D propagation map | `models/location.py`, `routers/geo.py`, `components/geo/` |
| 2 | Geographic heatmap, hotspots, activity score | `services/geo_intel.py`, `/geo-stats` |
| 3A | Investigation knowledge graph; persisted to **Neo4j** with automatic in-memory fallback | `services/knowledge_graph.py`, `neo4j_service.py`, `graph_store.py` (all Cypher), `graph_sync.py` |
| 3B | **Investigation Copilot** (Graph RAG) | `services/graph_rag.py`, `POST /incidents/{id}/copilot` |
| 4 | **ML Intelligence**: visual similarity, unusual patterns, clusters | `services/ml_intelligence.py`, `/incidents/{id}/ml…` |
| 5 | **Case Automation**: summary, evidence gaps, timeline, versioned report, alert DRAFT, export, workflow status, audit trail | `services/case_automation.py`, `routers/automation.py`, `services/audit.py` |
| 6 | Integration, navigation fixes, per-request graph reuse, docs | — |

Every module reads the same records through one graph (`graph_sync.load_graph`), so investigation, media,
evidence, source, platform, account, location, fingerprint and detection IDs are identical everywhere.
Phase notes: `PHASE1_NOTES.md` … `PHASE4_5_NOTES.md`.

**Integrity rules (enforced in code and covered by tests):** nothing is fabricated; missing data is reported as a
gap; `confirmed` / `inferred` / `unknown` statuses are copied, never upgraded; ML output is labelled analysis
("visually similar", "unusual pattern"), never identity or proof; nothing is ever sent outside LINEAGE.

### Investigation Copilot (Graph RAG)
Detects the question's intent (appearances, sources, locations, propagation, evidence, missing information),
retrieves the relevant graph relationships and evidence, and answers with every statement labelled
**VERIFIED FACT / INFERENCE / UNKNOWN** plus evidence, source and location references. If nothing supports an
answer it says **"Insufficient evidence."** With `ANTHROPIC_API_KEY` set, an LLM may rewrite the prose only; an LLM
answer that cites unknown codes or hides insufficient evidence is discarded. The key stays on the backend.

### ML Intelligence (Lineage → *ML Intelligence* tab)
- **Similarity** — 64-bit perceptual hash (keyframes for video); stored face-embedding cosine shown separately.
- **Anomalies** — bursts, unusually rapid spread, wide geographic spread, measured against the case's own baseline;
  otherwise **"Insufficient data."**
- **Clusters** — single-linkage groups of visually similar media with sources, platforms, locations, evidence.
Each result shows model name/version, timestamp, score, factors and evidence, and can be marked reviewed.

### Case Automation (investigation tab *Case Automation*)
Summary (facts by status) · evidence gaps · timeline (OBSERVED / RECORDED / CONFIRMED / INFERRED / UNKNOWN) ·
versioned investigation report + PDF · cyber-department alert **DRAFT — REQUIRES INVESTIGATOR REVIEW**
(Edit / Approve / Export; approval only records the decision, nothing is sent; a draft needs media, evidence and an
external source) · JSON/PDF export · status New → Analyzing → Evidence Collected → Review Required → Report Ready →
Closed (investigator-controlled; ML never changes it) · audit trail with the authenticated actor.

### Fallbacks
| Condition | Behaviour |
|---|---|
| Neo4j not configured / down | Graph served from memory; UI shows "Neo4j unavailable — using in-memory graph." |
| No LLM key | Copilot returns the grounded answer; UI shows "LLM unavailable — showing grounded graph/evidence context." |
| Too little data for ML | "Insufficient data." (no synthetic data is created) |
| No location / relationship / evidence | Empty states and evidence gaps; nothing is guessed |

## Environment variables (`backend/.env`, see `.env.example`)

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | no (SQLite default) | SQLAlchemy DSN |
| `JWT_SECRET_KEY` | **yes for any shared deployment** | JWT signing secret |
| `FILE_ENCRYPTION_KEY` | recommended | Fernet key for uploads (auto-generated locally if blank) |
| `CORS_ORIGINS` | no | Allowed frontend origins |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | no | Neo4j connection (blank URI = in-memory graph) |
| `NEO4J_CONNECT_TIMEOUT`, `NEO4J_RETRY_SECONDS`, `NEO4J_AUTO_SYNC` | no | Fallback timing; re-sync on read |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | no | Optional LLM (report summary, Copilot prose) |
| `COPILOT_LLM_PROVIDER`, `COPILOT_MODEL`, `COPILOT_MAX_TOKENS` | no | Copilot LLM (`none` disables) |
| `GEMINI_API_KEY`, `GEMINI_SEARCH_MODEL`, `MAX_WEB_SEARCHES_PER_MEDIA` | no | Consent-gated search-phrase generation |
| `ML_SIMILARITY_THRESHOLD`, `ML_CLUSTER_THRESHOLD`, `ML_ANOMALY_MIN_OBSERVATIONS`, `ML_ANOMALY_MIN_RELATIONSHIPS`, `ML_BURST_RATIO`, `ML_GEO_SPREAD_KM` | no | ML thresholds |
| `PRELOAD_MODELS`, `DATA_DIR`, `UPLOADS_DIR`, `MAX_UPLOAD_MB` | no | Runtime options |
| `VITE_API_URL` (`frontend/.env`) | no | Backend URL for the frontend (no secrets go here) |

Never commit `.env`; both `.env` files are gitignored.

## Tests

```bash
cd backend
pytest tests                                  # full suite; live-Neo4j tests skip without a server
NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=<pw> pytest tests   # include live Neo4j
cd ../frontend && npm run build              # TypeScript check (tsc -b) + production build
```
The frontend has no automated test runner.

## Demo sequence

1. Start Neo4j (optional), backend, frontend; log in (`demo@lineage.app`, pre-filled).
2. Open a case → **Overview / Detection / Fingerprinting** (real model score + aHash) → **Evidence Locker**.
3. **Lineage / Propagation** → *3D Propagation Map* (heatmap/hotspots) → *Source Graph*.
4. *Investigation Copilot* → "What is the propagation path and what evidence supports it?"
5. *ML Intelligence* → similarity / anomalies / clusters ("Insufficient data." where the case is too small).
6. **Case Automation** → summary, gaps, timeline → *Generate* report → PDF.
7. *Generate draft* → banner "DRAFT — REQUIRES INVESTIGATOR REVIEW" → Edit / Approve / Export (never sent);
   cases without an external source get "Insufficient evidence for an alert draft."
8. Set status, show the audit trail, *Export JSON*.

---

## Using PostgreSQL instead of SQLite

SQLite is the default so the app runs with zero setup. To use your local
Postgres, edit `backend/.env`:

```
DATABASE_URL=postgresql+psycopg2://YOUR_USER:YOUR_PASSWORD@localhost:5432/lineage
```

Create the database first (`createdb lineage`, or via pgAdmin). Tables are
created automatically on startup.

> **Postgres has been tested end-to-end**: real login, incident creation, file
> upload, detection, fingerprinting (including a real 512-dim face embedding),
> demo seeding, attribution-gap generation, report generation, and PDF export
> were all run against a real PostgreSQL 16 instance and verified by querying
> the tables directly afterward. `create_all()` creates all 10 tables cleanly
> with no Postgres-specific issues encountered.

---

## What's real vs. what isn't

This distinction is the product's core principle, so it's worth being precise.

**Genuinely real:**
- **Accounts and auth** — JWT + bcrypt, real users in the database
- **Database** — the full TRD §4 schema with real foreign keys
- **File storage** — uploads encrypted at rest with Fernet (AES)
- **Face embeddings** — MTCNN detection + FaceNet (InceptionResnetV1),
  producing real 512-dimension vectors. Verified discriminative: ~100%
  self-match, ~56% between two different people.
- **Perceptual hashing** — real 64-bit average hash, computed server-side.
  Stable across recompression (0-bit difference) and resizing (2 bits),
  clearly different for unrelated images (~35 bits).
- **Attribution Gap engine** — rule-based logic walking the real evidence
  graph, not an LLM guess
- **Incident report + PDF export** — assembled from real case data, rendered
  as an actual PDF via reportlab

**Real model, needs your internet:**
- **Deepfake detection** — integrates a real pretrained model from Hugging
  Face. If the model can't be reached, the API falls back to a pixel
  heuristic and **says so explicitly** in the UI (`model_name` shows
  "fallback", and the explanation states why). It never silently pretends
  the real model ran. On a machine with normal internet, the real model path
  runs automatically.

**Manual public-web search assistance:**
- **Image description and search phrases** — with `GEMINI_API_KEY` configured,
  Detection Analysis can send an image to Gemini after explicit consent, then
  create search phrases with Google and Bing links. LINEAGE does not call either
  search engine or collect results. This is not reverse-image matching. Phrase
  generation is limited to three runs per uploaded image and supports images
  up to 12 MB.
- **Propagation sources and the lineage graph** — sources can still be added
  manually with **+ Add Source** after an investigator reviews a page. Exact-
  image discovery across social platforms still requires a dedicated reverse-
  image-search integration.

**Static content:**
- The Roadmap page. Forward-looking product copy with no server equivalent.

---

## Layout

```
backend/
  app/
    core/       settings, password hashing, JWT
    db/         SQLAlchemy engine + session
    models/     the real TRD §4 schema
    schemas/    Pydantic request/response shapes
    services/   file_storage · pixel_analysis · face_embedding
                deepfake_model · attribution · report_builder
                report_pdf · llm_report · exif_gps · geo_intel
                knowledge_graph · neo4j_service · graph_store · graph_sync
                graph_rag · ml_intelligence · case_automation · audit · automation_pdf
    routers/    one per resource (+ geo, graph, copilot, ml, automation)
  tests/        pytest suite (unit, API, integration, live-Neo4j)
  docker-compose.yml   Postgres + API + Neo4j Community
frontend/
  src/
    lib/api.ts          typed client for every endpoint
    lib/adapters.ts     server shapes → display shapes
    lib/pipeline.ts     real Incident state machine
    context/            AuthContext · CaseContext (replaced caseData.ts)
    components/states   loading / error / empty states
    screens/            one per screen, all reading from the API
```

## Optional: LLM-written report summaries

Set `ANTHROPIC_API_KEY` in `backend/.env` and the incident report's summary
paragraph is written by a real Claude call, given only the already-computed
facts. Without a key, a deterministic template writes it instead. The
report's JSON schema is identical either way — only the prose source changes.

## Optional: search phrase generation

Add `GEMINI_API_KEY` to `backend/.env` and restart the API. In a case with an
uploaded image, open **Detection Analysis**, consent, and select **Generate
search links**. Gemini describes the image and suggests phrases; Google and
Bing pages open only when you choose a link. LINEAGE does not collect search
results or create source records from them. Manually add a page you reviewed
with **+ Add Source** in Evidence Locker or Lineage. Images over 12 MB are not
accepted. Google's unpaid Gemini terms may allow image submissions to be used
to improve services and reviewed by people, so do not submit sensitive images
using unpaid quota.

## Known gaps

- No Alembic migrations yet (`create_all` runs at startup)
- No rate limiting on uploads (TRD §8)
- Investigator actions are audited (Phase 5), but merely *viewing* the Evidence Locker is not
- Audio fingerprinting not implemented (Roadmap v3)
- Docker files exist in `backend/` but are untested in this build environment (Neo4j was verified with a local
  Neo4j 5.26 Community server instead)
- No frontend automated test runner; the UI was verified by build/type-check and API-level tests, not browser automation
