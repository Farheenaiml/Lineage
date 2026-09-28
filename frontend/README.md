# LINEAGE — Interactive Prototype (No Backend)

A click-through prototype of LINEAGE, built for the HerSpark Ideathon 2026 (Track 2).
Everything is powered by a single mock dataset (`src/data/caseData.ts`) representing
"Riya's Case" — there is no backend, no API calls, and no real data leaves your machine.

## Running it

You need Node.js 18+ installed. Then, from this folder:

```
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`) in your browser.

## How it's organized

- `src/data/caseData.ts` — the single source of truth. All screens read from here.
  Edit this file to change the numbers, sources, or report text shown anywhere in
  the app.
- `src/components/Sidebar.tsx` — the free-click navigation, styled as the
  investigation pipeline (Detection → Fingerprinting → Evidence Locker → Lineage
  Map → Attribution Gap → Incident Report), plus Overview and Roadmap.
- `src/screens/` — one file per screen, matching the modules described in the
  LINEAGE PRD/TRD/Project Flow documents.
- `src/components/ui.tsx` — shared UI primitives (panels, confidence bars, the
  seeded/live data tag, the stage tracker).

## What's "real" vs "seeded" in this prototype

This is a hybrid: some things genuinely compute in your browser from a file you
upload, and some things are fixed sample data. Both are labeled in the UI itself
so the distinction is never hidden.

**Genuinely live** (upload a file on the Detection screen to try it):
- A real 64-bit average hash, computed from your file's actual pixel data.
- A "signal score" (edge irregularity + compression density) computed from real
  pixel statistics — this is an honest heuristic, explicitly labeled as **not** a
  trained deepfake classifier, since building one is out of scope for a no-backend
  prototype.
- For images, the hash is genuinely stable across recompression and resizing, and
  genuinely different for an unrelated image — try it yourself with two versions
  of the same photo. It's less stable across heavy cropping, which the UI says
  outright rather than overclaiming.
- For videos, a frame from partway through the clip is captured and analyzed the
  same way.

**Seeded / sample data** (Riya's Case, unaffected by what you upload):
- The four propagation sources (SRC-A–D), the Evidence Locker, the Lineage Map,
  the Attribution Gap Report, and the generated Incident Report all stay fixed —
  these represent the parts of the real product that would need licensed
  cross-platform search or a trained face-recognition model, neither of which
  this prototype runs.
- The face embedding, key-frame hashes, and audio fingerprint values on the
  Fingerprinting screen are sample data even when you've uploaded a file, and are
  labeled as such.

## Presenting it on 30 Sep

The sidebar is a free-click dashboard — jump to any screen in any order. A natural
walkthrough order for judges is: **Overview → Detection (try a live upload here) →
Fingerprinting → Evidence Locker → Lineage Map → Attribution Gap → Incident Report
→ Roadmap**, narrating the seeded portion as Riya's Case exactly as described in
the Project Flow document's demo script.

