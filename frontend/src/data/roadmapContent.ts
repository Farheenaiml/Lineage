/**
 * Static product roadmap content. This is intentionally NOT fetched from the
 * backend — it's forward-looking product copy with no server-side equivalent,
 * so inventing an API endpoint for it would add indirection without adding
 * truth. Everything else the app displays comes from real API data.
 */
export const roadmapItems = [
  {
    title: "Licensed cross-platform search",
    detail:
      "Automatically discover related content using licensed reverse-image-search APIs (e.g., TinEye, Google Vision) instead of requiring an investigator to add every source by hand.",
    status: "Roadmap — v2",
  },
  {
    title: "Formal platform partnerships",
    detail:
      "Structured data-sharing agreements with major platforms for faster, authorized lookups — instead of scraping, which would violate most platforms' Terms of Service.",
    status: "Roadmap — v2",
  },
  {
    title: "Live lineage graph",
    detail:
      "Once automatic search is available, the propagation graph updates continuously as new sources are discovered, instead of only reflecting what's been manually recorded.",
    status: "Roadmap — v2",
  },
  {
    title: "Real-time audio fingerprinting",
    detail:
      "Acoustic fingerprints for voice-cloned audio, so manipulated speech can be matched across re-uploads the same way images already are.",
    status: "Roadmap — v3",
  },
  {
    title: "Multi-language incident reports",
    detail:
      "Generate reports and recommended actions in regional languages to widen accessibility.",
    status: "Roadmap — v3",
  },
];
