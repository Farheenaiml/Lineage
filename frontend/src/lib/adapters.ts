import { Source, EvidenceItem, SourceRelationship } from "./api";

/**
 * Adapters between the backend's API shapes and the display shapes the
 * existing screens were written against.
 *
 * This exists so Phase 3 stays a data-source swap rather than a redesign:
 * screens keep their markup and field names, and this file is the single
 * place where server field names (`account_identifier`, `observed_at`) are
 * translated into display values. It also generates the human-readable
 * SRC-A / SRC-B labels, which are a presentation concern — the backend
 * uses real UUIDs.
 */

export function formatObserved(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export type DisplaySource = {
  id: string;          // real backend UUID
  label: string;       // "SRC-A", "SRC-B", … for display
  platform: string;
  account: string;
  observedAt: string;
  similarity: number | null;
  relationship: string;
  seeded: boolean;
  url: string | null;
};

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export function toDisplaySources(sources: Source[]): DisplaySource[] {
  return sources.map((s, i) => ({
    id: s.id,
    label: `SRC-${LETTERS[i] ?? i + 1}`,
    platform: s.platform,
    account: s.account_identifier ?? "—",
    observedAt: formatObserved(s.observed_at),
    similarity: s.similarity_score,
    relationship: s.relationship_label ?? "—",
    seeded: s.is_seeded,
    url: s.url,
  }));
}

export type DisplayEvidence = {
  id: string;
  label: string;
  type: string;
  sourceLabel: string;
  capturedAt: string;
  notes: string | null;
};

export function toDisplayEvidence(
  items: EvidenceItem[],
  sources: DisplaySource[]
): DisplayEvidence[] {
  const byId = new Map(sources.map((s) => [s.id, s.label]));
  return items.map((e, i) => ({
    id: e.id,
    label: `EV-${String(i + 1).padStart(2, "0")}`,
    type: e.item_type === "uploaded_image"
      ? "Uploaded image"
      : e.item_type === "uploaded_video"
      ? "Uploaded video"
      : e.item_type,
    sourceLabel: e.source_id ? byId.get(e.source_id) ?? "—" : "—",
    capturedAt: formatObserved(e.captured_at),
    notes: e.notes,
  }));
}

export type DisplayRelationship = {
  id: string;
  fromLabel: string;
  toLabel: string;
  fromId: string;
  toId: string;
  type: string;
  confidence: number | null;
};

export function toDisplayRelationships(
  rels: SourceRelationship[],
  sources: DisplaySource[]
): DisplayRelationship[] {
  const byId = new Map(sources.map((s) => [s.id, s.label]));
  return rels.map((r) => ({
    id: r.id,
    fromId: r.from_source_id,
    toId: r.to_source_id,
    fromLabel: byId.get(r.from_source_id) ?? "?",
    toLabel: byId.get(r.to_source_id) ?? "?",
    type: r.relationship_type,
    confidence: r.confidence,
  }));
}

/** Parsed face-embedding info stored as JSON on the Fingerprint record. */
export function parseFaceEmbedding(json: string | null): {
  foundFace: boolean;
  dims: number | null;
  confidence: number | null;
  preview: string | null;
  error?: string;
} {
  if (!json) return { foundFace: false, dims: null, confidence: null, preview: null };
  try {
    const parsed = JSON.parse(json);
    const emb: number[] | null = parsed.embedding ?? null;
    return {
      foundFace: !!parsed.found_face,
      dims: emb ? emb.length : null,
      confidence: parsed.detection_confidence ?? null,
      preview: emb ? `[${emb.slice(0, 5).map((v) => v.toFixed(3)).join(", ")}, …]` : null,
      error: parsed.error,
    };
  } catch {
    return { foundFace: false, dims: null, confidence: null, preview: null };
  }
}
