# Phase 1 — 3D Propagation / Location Map

## New / changed files
Backend
- app/models/location.py           NEW  SourceLocation (provenance, confidence, basis), RelationshipDirection
- app/models/__init__.py           MOD  imports new models (tables created by existing create_all; no data loss)
- app/services/exif_gps.py         NEW  Pillow-only EXIF GPS extraction (never guesses)
- app/routers/geo.py               NEW  GET /incidents/{id}/geo, PUT/DELETE source location, confirm/revoke direction, OSM geocode proxy
- app/routers/media.py             MOD  upload records EXIF GPS as a verified-tier location when present
- app/main.py                      MOD  registers geo router
Frontend
- src/components/geo/globe.ts            NEW  Three.js engine (Natural Earth basemap rendered locally, no API keys)
- src/components/geo/PropagationMap.tsx  NEW  map UI, timeline filter, inspector, legend
- src/components/geo/LocationEditor.tsx  NEW  investigator-supplied location (OSM search or manual lat/lon)
- src/screens/LineageMap.tsx             MOD  original Source Graph kept as a tab; 3D map added as sibling tab
- src/components/AddSourceModal.tsx      MOD  optional location fields
- src/lib/api.ts, src/index.css          MOD  geo types/methods, label styles
- package.json                           +three, d3-geo, topojson-client, world-atlas

## Integrity rules (server-side)
- No coordinates are generated; a node exists only for a stored SourceLocation row.
- EXIF = Verified tier; human-entered = Investigator supplied; heuristic = Inferred. Humans cannot create Verified.
- EXIF locations cannot be edited or deleted.
- Arc direction: confirmed only after investigator confirmation; "inferred propagation direction" only when timestamps
  support the recorded link; otherwise (or for "same content" links) undirected with no arrow.

## Run
cd frontend && npm install
cd backend && uvicorn app.main:app --reload   (no new Python deps)
