# Phase 2 — Heatmap + Geographic Location Intelligence

Built on top of Phase 1. No duplicate location system: same `source_locations`, `sources`, `source_relationships`,
`evidence_items` tables, same globe engine, same `/geo` API (unchanged).

## Files
Backend — NEW: `app/services/geo_intel.py` (aggregation, hotspot rules, activity score; pure Python),
`tests/test_geo_intel.py` (19 tests). MODIFIED: `app/routers/geo.py` (+`/geo-stats`, `/geo-observations`, city/region on
location PUT + geocode), `app/models/location.py` (+`city`, `region`), `app/main.py` (additive migration), `.env.example`.
Frontend — NEW: `components/geo/panels.tsx` (location card/panel, hotspots, score breakdown, compare, earliest, legends, empty states).
MODIFIED: `components/geo/PropagationMap.tsx` (rewritten container), `components/geo/globe.ts` (heat layer, layer toggles,
region picking, selection marker), `components/geo/LocationEditor.tsx` (city/region), `lib/api.ts`, `screens/LineageMap.tsx`, `App.tsx`.

## Schema change (only one, additive)
`source_locations.city`, `source_locations.region` (nullable). Applied on startup by `_migrate_additive_columns()` with
`ALTER TABLE ... ADD COLUMN` — existing rows/investigations are preserved. Old rows show "Not recorded"; values are only ever
filled from a geocoder result or an investigator, never guessed.

## Definitions (kept separate in the UI)
- Observation = one located source record (timestamp = `Source.observed_at`).
- Unique source = distinct identity: platform + (account | url | source id). unique_sources <= observations.
- Propagation event = a STORED `SourceRelationship` whose both endpoints are located and pass the active filters.
- Activity score = obs×3 + unique sources×5 + events×6, capped at 100; High ≥ 60, Medium ≥ 25 (env `GEO_*` or query
  `high_score`/`medium_score`). Factors are shown in the UI. It is not a risk/crime/person score.
- "Earliest Observed" is never labelled "Original Source".

## API
`GET /incidents/{id}/geo-stats?start&end&platform&tier&metric&high_score&medium_score`
`GET /incidents/{id}/geo-observations?start&end&platform&tier`  (flat provenance rows: location_id, lat/lon, city, region,
country, location_type, confidence, source_id, evidence_ids, observed_at, created_at)

## Testing status (be aware)
- Ran here: 19 backend unit tests for all aggregation/filter/score/hotspot/empty-state logic (`python tests/test_geo_intel.py`) — all pass.
- NOT run here (no network → no npm/pip installs): FastAPI endpoints against a live DB, `npm run build`, and the browser UI.
  Run `cd frontend && npm install && npm run build` and click through the scenarios in the checklist before the demo.
