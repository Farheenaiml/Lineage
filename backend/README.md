# LINEAGE Backend — Phase 1

Real FastAPI backend implementing the Phase 1 foundations from the project
plan: auth, the actual data model from the TRD, encrypted file storage, and a
genuine (heuristic, not-yet-ML) detection + fingerprinting pipeline that the
frontend prototype's client-side version was ported from.

**What this is not yet:** Phase 2 (a real pretrained deepfake-detection model
and a real face-embedding model) and exact-image reverse search across social
platforms are not implemented — see the main project plan. Optional, consented
Gemini image description and query generation prepares Google/Bing search links;
LINEAGE does not fetch results or identify exact image matches. The
`/detect` and `/fingerprint` endpoints here use the same honest pixel
heuristic as the frontend, clearly labeled as such in every response.

## Option A — Local dev with SQLite (fastest way to try it)

No Docker, no Postgres needed.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`. Interactive docs (Swagger UI) are
at `http://localhost:8000/docs` — the fastest way to explore every endpoint.

A `data/lineage.db` SQLite file and a `data/uploads/` folder are created
automatically on first run.

### Optional no-card search phrase generation

After `pip install -r requirements.txt`, add a Gemini API key to `backend/.env`:

```dotenv
GEMINI_API_KEY=your-gemini-key
GEMINI_SEARCH_MODEL=gemini-3.8-flash
```

Restart the backend. In the frontend, open an image case's **Detection
Analysis**, consent to sending the image to Gemini, then generate search links.
Gemini returns a visual description and query phrases. LINEAGE does not send
queries to Google/Bing or collect their result pages; those open in your browser
when you click a link. Manually add any page you review with **+ Add Source**.
Search phrase generation is capped at three runs per image and accepts images
up to 12 MB. This does not search social platforms directly or compare page
pixels against the upload. Gemini's unpaid tier may use data to improve
services and allow human review; avoid sensitive images on that tier.

## Option B — Docker Compose with real Postgres

```bash
docker compose up --build
```

This runs Postgres and the API together, with the API pointed at Postgres
automatically. The API is still at `http://localhost:8000`.

Set a real `JWT_SECRET_KEY` and `FILE_ENCRYPTION_KEY` via a `.env` file
in this directory before running this anywhere beyond your own machine —
`docker-compose.yml` reads both from the environment. Generate them with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Trying the full pipeline

1. `POST /auth/register` — create an account
2. `POST /auth/login` — get a bearer token (form fields: `username` = your email, `password`)
3. `POST /incidents` — create a case
4. `POST /incidents/{id}/media` — upload an image or video (multipart `file` field)
5. `POST /incidents/{id}/media/{media_id}/detect` — run the real pixel-heuristic analysis
6. `POST /incidents/{id}/media/{media_id}/fingerprint` — compute the real average hash
7. `POST /incidents/{id}/demo/seed` — populate Riya's Case's 5 seeded sources
8. `GET /incidents/{id}/evidence` — see the evidence auto-created by seeding
9. `POST /incidents/{id}/attribution-gap` — generate the real, rule-based known/unresolved/evidence-needed breakdown
10. `POST /incidents/{id}/report` — generate the structured incident report

Every step above was tested end-to-end against a real uploaded image before
this was handed over — the hash, the heuristic score, the attribution-gap
text, and the report all come from real computation on real data, not
fixtures returned regardless of input.

## Project layout

```
app/
  core/       # settings, password hashing, JWT
  db/         # SQLAlchemy engine/session
  models/     # the real TRD §4 schema (Incident, MediaItem, DetectionResult,
              # Fingerprint, Source, SourceRelationship, EvidenceItem,
              # IncidentReport, AttributionGapEntry, User)
  schemas/    # Pydantic request/response shapes
  services/   # file_storage (encryption), pixel_analysis (hash + heuristic),
              # attribution (rule-based gap engine), report_builder
  routers/    # one file per resource, matching the TRD §6 endpoint list
  main.py     # FastAPI app, CORS, router wiring, startup table creation
```

## Known gaps to close before this is "done," not just "Phase 1"

- **No Alembic migrations yet** — `Base.metadata.create_all()` runs on
  startup, which is fine while the schema is still moving but will need to
  become real migrations before this holds anyone's actual data long-term.
- **`/detect` and `/fingerprint` are heuristics, not ML models** — by design
  for this phase; swapping in a real pretrained model only touches
  `app/services/pixel_analysis.py` and the two router functions that call it.
- **No rate limiting** on the upload endpoint yet (TRD §8).
- **No audit log** on Evidence Locker access yet (TRD §8).
- **CORS origins default to the Vite dev server** — add your deployed
  frontend's real origin to `CORS_ORIGINS` before deploying anywhere.
- **The auto-generated `FILE_ENCRYPTION_KEY`** (when left blank) is written
  to `data/.file_encryption_key` for dev convenience — a real deployment
  should set this explicitly from a secrets manager instead, since losing
  that file means every previously-uploaded file becomes permanently
  undecryptable.
