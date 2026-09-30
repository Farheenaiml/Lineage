# Phase 3A (Neo4j persistence) + Phase 3B (Graph RAG / Investigation Copilot)

Built on the Phase 3A in-memory `KnowledgeGraph`, which is still the only place that decides relationships, statuses
and confidences. Neo4j stores its output, and the Copilot reads it. No SQL tables or migrations were added.

## Files
Backend, new:
- `app/services/neo4j_service.py`: driver lifecycle, health, transactions, error handling
- `app/services/graph_store.py`: all Cypher (constraints, MERGE upsert, prune, read)
- `app/services/graph_sync.py`: SQL → KnowledgeGraph → Neo4j sync, Neo4j/memory loader, CLI
- `app/services/graph_rag.py`: the Copilot
- `app/routers/copilot.py`
- `app/schemas/copilot.py`
- Tests: `tests/graph_fakes.py`, `test_neo4j_service.py`, `test_graph_sync.py`, `test_graph_rag.py`, `test_neo4j_integration.py`

Backend, modified:
- `app/core/config.py`: `NEO4J_*` and `COPILOT_*` settings
- `app/main.py`: `/health` neo4j field, constraints at startup, driver closed at shutdown, routers registered
- `app/routers/graph.py`: reads Neo4j with fallback, adds `graph_source`, `/graph/sync`, `/graph/source` and `/graph/health`. `load_graph_input` moved to `graph_sync` and is still importable from here.
- `app/services/knowledge_graph.py`: additive `from_records()`; the propagation-node builder was extracted into `_attach_propagation()` with identical output
- `requirements.txt` (`neo4j==6.3.1`), `.env.example`, `docker-compose.yml` (`neo4j:5-community` service)

Frontend, new: `src/components/copilot/InvestigationCopilot.tsx`.
Frontend, modified:
- `src/lib/api.ts`: types, `askCopilot`, `getGraphHealth`, `syncGraph`
- `src/screens/LineageMap.tsx`: third tab "Investigation Copilot"; the Source Graph accepts a preselected source
- `src/components/geo/PropagationMap.tsx`: optional `focusNodeId` prop

## Neo4j model
- Each node has the `:LineageNode` label plus one entity label: Investigation, Media, Source, Evidence, Platform, Account, Location, Fingerprint or Detection.
- The MERGE key is `uid = "<investigation_id>|<graph node id>"`. The graph node id embeds the SQL primary key, which is also stored as `record_id`.
- Constraints: `uid` is unique for `:LineageNode` and every label. `record_id` is unique for the six SQL-backed labels. There are indexes on `investigation_id`, `record_id`, and the relationship `uid` of each relationship type.
- Platform, Account and Location nodes are scoped per investigation, so investigations owned by different users never share a node.
- Relationships carry `status` verbatim (`confirmed`, `inferred`, `unknown`, `verified`, `investigator_supplied`, `recorded`, `incident_scoped`). They also carry `confidence`, `timestamp` and `evidence_id` only when a value exists: SQL NULL becomes an absent property, never 0.
- `metadata_json` / `payload_json` keep the lossless original, so reading from Neo4j reproduces the in-memory graph exactly. Tests check this against both the fake repository and a real server.
- Propagation nodes and `HAS_ORIGIN` / `HAS_DESTINATION` are **not persisted**, because they are not in the Phase 3A label list. They are re-derived from each `PROPAGATES_TO` on read, with the same status.
- Sync is one transaction per investigation: MERGE everything, `SET n = props`, then delete only that investigation's nodes and relationships that SQL no longer produces. Other investigations are never touched.

## Retrieval and fallback
`graph_sync.load_graph()` behaves as follows:
- If Neo4j is configured and reachable, it runs an idempotent sync (when `NEO4J_AUTO_SYNC=true`, the default) and then reads from Neo4j.
- If Neo4j is not configured, down, rejects the credentials, or a query fails, it serves the in-memory graph.
- Every graph response includes `graph_source` (`backend`, `neo4j`, `fallback`, `reason`).
- After a failed connection the backend waits `NEO4J_RETRY_SECONDS` before trying again, so a down Neo4j costs one short timeout, not one per request.

## Copilot (POST /incidents/{id}/copilot, `{"question": "..."}`)
Pipeline: detect intents (appearances, sources, locations, propagation, evidence, gaps); run a lexical entity search with the graph's existing node search (the project has no text or vector index); traverse the graph; build categorised facts and evidence gaps.

Grounding rules:
- Categories come from the stored status and are never raised:
  - `confirmed`, `verified`, `recorded` → VERIFIED FACT
  - `inferred`, `incident_scoped`, `investigator_supplied` → INFERENCE
  - `unknown` → UNKNOWN
- A path is only as strong as its weakest link.
- When retrieval finds nothing, the answer says "Insufficient evidence."

LLM (optional):
- It uses `ANTHROPIC_API_KEY` with `COPILOT_MODEL` (default `claude-opus-5-5`, effort `low`, server-side refusal fallback enabled).
- It only writes the prose `answer`. All structured lists come from the deterministic retrieval.
- LLM prose is rejected if it cites a SRC-/EV- code that doesn't exist, or omits "Insufficient evidence." where retrieval found none. The deterministic answer is used instead.
- With no key, or with `COPILOT_LLM_PROVIDER=none`, the deterministic grounded answer and the full context are returned.

## Run
- Neo4j: `cd backend && docker compose up -d neo4j`, or a local Neo4j 5 Community install.
- Backend `.env`: `NEO4J_URI=bolt://localhost:7687`, `NEO4J_PASSWORD=<yours>`.
- CLI:
  - `python -m app.services.graph_sync status`
  - `python -m app.services.graph_sync sync <incident_id> [--rebuild]`
  - `python -m app.services.graph_sync sync-all`
  - `python -m app.services.graph_sync counts <incident_id>`
- Tests: `cd backend && pytest tests`. To also run the real-server tests, set `NEO4J_TEST_URI=bolt://localhost:7687` and `NEO4J_TEST_PASSWORD=...`.
