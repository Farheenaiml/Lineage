import { useCallback, useEffect, useState } from "react";
import { Brain, Link2, MapPin, FileText, Network, RefreshCw, CheckCircle2, Info } from "lucide-react";
import { api, MLAll, MLFactor, MLLocation, MLProvenance, MLSource } from "../../lib/api";
import { useCase } from "../../context/CaseContext";
import { Panel, PanelHeader, StatusBadge } from "../ui";

/**
 * Phase 4 — ML Intelligence. Visual similarity, unusual patterns and clusters computed server-side from stored
 * fingerprints and the investigation graph. Every card shows its score, explanation, evidence, model/version and
 * timestamp. Results are analysis, not facts; similarity is not identity.
 */
export type MLLinks = {
  onOpenEvidence?: () => void;
  onOpenSource?: (sourceId: string) => void;
  onOpenLocation?: (mapNodeId: string) => void;
  onOpenGraph?: (sourceId?: string) => void;
};

const chip = "inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-[11px] font-medium text-ink hover:border-brand hover:text-brand transition disabled:opacity-50 disabled:hover:border-border disabled:hover:text-ink";

function fmt(iso: string | null | undefined) {
  if (!iso) return "time not recorded";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function factorValue(f: MLFactor) {
  if (f.value === null || f.value === undefined) return "not available";
  if (Array.isArray(f.value)) return f.value.join(", ") || "none";
  if (typeof f.value === "number") return Number.isInteger(f.value) ? String(f.value) : f.value.toFixed(3);
  return String(f.value);
}

function Provenance({ p }: { p: MLProvenance }) {
  return <p className="text-[10.5px] text-faint mt-2 font-mono">{p.model_name} v{p.model_version} · computed {fmt(p.computed_at)}</p>;
}

function Factors({ factors }: { factors: MLFactor[] }) {
  return (
    <ul className="mt-2 grid sm:grid-cols-2 gap-x-4 gap-y-1">
      {factors.map((f) => (
        <li key={f.name} className="text-[11px] text-muted" title={f.detail}>
          <span className="text-ink font-medium">{f.name.replace(/_/g, " ")}:</span> {factorValue(f)}
        </li>
      ))}
    </ul>
  );
}

export default function MLIntelligence({ onOpenEvidence, onOpenSource, onOpenLocation, onOpenGraph }: MLLinks) {
  const { incidentId } = useCase();
  const [data, setData] = useState<MLAll | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    if (!incidentId) return;
    setBusy(true); setErr(null);
    try { setData(await api.getML(incidentId)); } catch (e: any) { setErr(e?.message ?? "Could not run ML analysis."); } finally { setBusy(false); }
  }, [incidentId]);
  useEffect(() => { load(); }, [load]);

  async function review(id: string) {
    if (!incidentId) return;
    try { await api.recordReview(incidentId, "ml_finding", id); setReviewed((r) => ({ ...r, [id]: true })); }
    catch (e: any) { setErr(e?.message ?? "Could not record the review."); }
  }

  const sourceChips = (sources: MLSource[]) => sources.map((s) => {
    const here = s.incident_id === incidentId;
    return (
      <button key={s.source_id} className={chip} disabled={!here} onClick={() => here && onOpenSource?.(s.source_id)}
        title={here ? `Open ${s.label} in the Source Graph` : "Source belongs to another investigation"}>
        <Link2 size={11} /> {s.code} · {s.label}{s.appears_in_status ? ` (${s.appears_in_status.replace("_", " ")})` : ""}
      </button>
    );
  });
  const locationChips = (locs: MLLocation[]) => locs.map((l) => (
    <button key={l.location_node_id} className={chip} disabled={!l.map_node_id} onClick={() => l.map_node_id && onOpenLocation?.(l.map_node_id)}>
      <MapPin size={11} /> {l.label} · {l.status.replace("_", " ")}
    </button>
  ));
  const evidenceChip = (ids: string[]) => ids.length > 0 && (
    <button className={chip} onClick={() => onOpenEvidence?.()} title={ids.join(", ")}><FileText size={11} /> {ids.length} evidence item(s)</button>
  );
  const reviewBtn = (id: string) => (
    <button className={chip} onClick={() => review(id)} disabled={reviewed[id]}>
      <CheckCircle2 size={11} /> {reviewed[id] ? "Reviewed" : "Mark reviewed"}
    </button>
  );
  const empty = (a: { status: string; message: string | null }) => (
    <p className="text-[12.5px] text-muted">{a.message ?? (a.status === "insufficient_data" ? "Insufficient data." : "No results.")}</p>
  );

  return (
    <div className="space-y-5">
      <Panel className="p-5 sm:p-6">
        <PanelHeader
          title="ML Intelligence"
          subtitle="Local analysis of stored fingerprints, timestamps, locations and relationships. Results are observations for an investigator to review, not facts."
          right={<button onClick={load} disabled={busy} className={chip}><RefreshCw size={12} className={busy ? "animate-spin" : ""} /> {busy ? "Analysing…" : "Re-run"}</button>}
        />
        <div className="rounded-xl bg-blue/70 border border-blue p-3 text-[11.5px] text-[#3B5A7D] flex gap-2">
          <Info size={14} className="shrink-0 mt-0.5" />
          Similarity is not identity. Unusual patterns are not evidence of malicious activity. Clusters do not indicate who created, owns or posted anything.
        </div>
        {err && <p className="mt-3 text-[12.5px] text-[#8A4138]">{err}</p>}
      </Panel>

      {data && (<>
        <Panel className="p-5 sm:p-6">
          <PanelHeader title="Similarity" subtitle={`${data.similarity.provenance.model_name} v${data.similarity.provenance.model_version} · ${data.similarity.disclaimer}`} />
          {data.similarity.results.length === 0 ? empty(data.similarity) : (
            <div className="space-y-3">
              {data.similarity.results.map((r) => (
                <div key={r.id} className="rounded-xl border border-border/70 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone="blue">{r.label}</StatusBadge>
                    <b className="text-[13px] text-ink">score {r.score.toFixed(2)}</b>
                    <span className="text-[11px] text-muted">'{r.media.filename}' ↔ '{r.match.filename}'{r.match.same_investigation ? "" : ` in “${r.match.incident_title}”`}</span>
                  </div>
                  <p className="text-[12px] text-ink mt-2 leading-relaxed">{r.explanation}</p>
                  <Factors factors={r.factors} />
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {sourceChips([...r.media.sources, ...r.match.sources])}
                    {locationChips([...r.media.locations, ...r.match.locations])}
                    {evidenceChip(r.evidence_refs.evidence_ids)}
                    {reviewBtn(r.id)}
                  </div>
                  <Provenance p={r.provenance} />
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel className="p-5 sm:p-6">
          <PanelHeader title="Anomalies (unusual patterns)" subtitle={`${data.anomalies.provenance.model_name} v${data.anomalies.provenance.model_version} · ${data.anomalies.disclaimer}`} />
          {data.anomalies.detectors && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {data.anomalies.detectors.map((d) => (
                <span key={d.detector} title={d.reason} className="text-[10.5px] rounded-md bg-soft px-2 py-1 text-muted">
                  {d.detector.replace(/_/g, " ")}: {d.status === "ran" ? "ran" : "insufficient data"}
                </span>
              ))}
            </div>
          )}
          {data.anomalies.results.length === 0 ? empty(data.anomalies) : (
            <div className="space-y-3">
              {data.anomalies.results.map((a) => (
                <div key={a.id} className="rounded-xl border border-border/70 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone="amber">Unusual pattern</StatusBadge>
                    <b className="text-[13px] text-ink">{a.title}</b>
                    <span className="text-[11px] text-muted">score {a.score.toFixed(2)} · {fmt(a.window.start)} – {fmt(a.window.end)}</span>
                  </div>
                  <p className="text-[12px] text-ink mt-2 leading-relaxed">{a.explanation}</p>
                  <Factors factors={a.factors} />
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {a.source_ids.map((sid) => (
                      <button key={sid} className={chip} onClick={() => onOpenSource?.(sid)}><Link2 size={11} /> Source {sid.slice(0, 8)}</button>
                    ))}
                    {a.relationship_ids.map((rid) => (
                      <button key={rid} className={chip} onClick={() => onOpenGraph?.(a.source_ids[0])}><Network size={11} /> {rid.split(":")[0]}</button>
                    ))}
                    {a.location_node_ids.map((lid) => (
                      <button key={lid} className={chip} onClick={() => onOpenLocation?.(lid.replace(/^location:/, ""))}><MapPin size={11} /> location</button>
                    ))}
                    {evidenceChip(a.evidence_ids)}
                    {reviewBtn(a.id)}
                  </div>
                  <Provenance p={a.provenance} />
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel className="p-5 sm:p-6">
          <PanelHeader title="Clusters" subtitle={`${data.clusters.provenance.model_name} v${data.clusters.provenance.model_version} · ${data.clusters.disclaimer}`} />
          {data.clusters.results.length === 0 ? empty(data.clusters) : (
            <div className="space-y-3">
              {data.clusters.results.map((c) => (
                <div key={c.id} className="rounded-xl border border-border/70 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone="gray">{c.id}</StatusBadge>
                    <b className="text-[13px] text-ink">{c.size} media · {c.source_count} source(s)</b>
                    <span className="text-[11px] text-muted">similarity {c.similarity_range.min.toFixed(2)}–{c.similarity_range.max.toFixed(2)} · platforms: {c.platforms.join(", ") || "none"} · {c.investigations.length} investigation(s)</span>
                  </div>
                  <p className="text-[12px] text-ink mt-2 leading-relaxed">{c.explanation}</p>
                  <p className="text-[11px] text-muted mt-1">Members: {c.members.map((m) => `'${m.filename}' (${m.incident_title})`).join(", ")}</p>
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {sourceChips(c.sources)}
                    {locationChips(c.locations)}
                    {evidenceChip(c.evidence_refs.evidence_ids)}
                    {reviewBtn(c.id)}
                  </div>
                  <Provenance p={c.provenance} />
                </div>
              ))}
            </div>
          )}
        </Panel>
      </>)}
      {!data && busy && <p className="text-[12.5px] text-muted flex items-center gap-2"><Brain size={14} /> Running analysis…</p>}
    </div>
  );
}
