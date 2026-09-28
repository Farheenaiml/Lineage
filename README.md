# LINEAGE — Full Stack (Phases 1–3 Complete)

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
                report_pdf · llm_report
    routers/    one per resource, matching TRD §6
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
- No audit log on Evidence Locker access (TRD §8)
- Audio fingerprinting not implemented (Roadmap v3)
- Docker files exist in `backend/` but are untested — deferred to deployment
