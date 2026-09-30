import { useMemo, useState } from "react";
import {
  ArrowRight, ShieldCheck, UserCheck, HelpCircle, Fingerprint, Pencil, Trash2, Flame, Clock, FileSearch,
  Share2, MapPin, GitCompare, Info, LocateFixed, Sparkles, Plus,
} from "lucide-react";
import type { GeoConfig, GeoEdge, GeoLevel, GeoMetric, GeoObservation, GeoStatsNode, GeoStats, Hotspot, EmptyReason } from "../../lib/api";
import { formatObserved } from "../../lib/adapters";
import { TIER_COLOR, EDGE_COLOR, HEAT_COLOR } from "./globe";

/* ------------------------------------------------------------------ shared bits */
export const TIER_LABEL: Record<string, string> = { verified: "Verified", investigator: "Investigator supplied", inferred: "Inferred", mixed: "Mixed provenance" };
export const PROV_LABEL: Record<string, string> = { exif_gps: "EXIF GPS metadata", public_metadata: "Public source metadata", investigator_supplied: "Investigator supplied", inferred: "Inferred" };
export const MODE_LABEL: Record<string, string> = { confirmed: "Confirmed direction", inferred: "Inferred propagation direction", undirected: "Undirected relationship" };
export const METRIC_LABEL: Record<GeoMetric, string> = { observations: "Observations", unique_sources: "Unique sources", propagation_events: "Propagation events" };
export const METRIC_HELP: Record<GeoMetric, string> = {
  observations: "Glow strength = number of observation records recorded at each location.",
  unique_sources: "Glow strength = number of distinct source records (platform + account) at each location.",
  propagation_events: "Glow strength = stored propagation relationships touching each location.",
};
export const LEVEL_LABEL: Record<GeoLevel, string> = { high: "High Activity", medium: "Medium Activity", low: "Low Activity" };
const fmtShort = (iso: string) => new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function TierBadge({ tier }: { tier: string }) {
  const c = TIER_COLOR[tier] ?? TIER_COLOR.inferred;
  const Icon = tier === "verified" ? ShieldCheck : tier === "investigator" ? UserCheck : HelpCircle;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10.5px] font-semibold border" style={{ color: c, borderColor: c + "55", background: c + "18" }}>
      <Icon size={11} /> {TIER_LABEL[tier] ?? tier}
    </span>
  );
}
export function LevelPill({ level, compact }: { level: GeoLevel; compact?: boolean }) {
  const c = HEAT_COLOR[level];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-[10.5px] font-semibold border whitespace-nowrap" style={{ color: level === "medium" ? "#8a6208" : c, borderColor: c + "66", background: c + "1c" }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} /> {compact ? level[0].toUpperCase() + level.slice(1) : LEVEL_LABEL[level]}
    </span>
  );
}
export function ConfBar({ value }: { value: number }) {
  const tone = value >= 80 ? "#4fe3a1" : value >= 55 ? "#f6b94d" : "#e58b7d";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-[#E6EBE5] overflow-hidden"><div className="h-full rounded-full" style={{ width: `${value}%`, background: tone }} /></div>
      <span className="text-[11.5px] font-semibold text-ink tabular-nums">{Math.round(value)}%</span>
    </div>
  );
}
export function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border/40 pb-2 last:border-0 last:pb-0 text-[12px]">
      <span className="text-muted shrink-0">{k}</span>
      <span className="font-semibold text-ink text-right break-words min-w-0">{v}</span>
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 first:mt-0">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-faint mb-2.5 flex items-center gap-2">{title}<span className="flex-1 h-px bg-border/70" /></p>
      <div className="space-y-2.5">{children}</div>
    </div>
  );
}
function Chips({ items, empty = "Not available" }: { items: string[]; empty?: string }) {
  if (!items.length) return <span className="text-[12px] font-semibold text-ink">{empty}</span>;
  return <span className="flex flex-wrap gap-1.5 justify-end">{items.map((x) => <span key={x} className="px-2 py-0.5 rounded-md bg-soft text-brand text-[10.5px] font-semibold font-mono">{x}</span>)}</span>;
}
const actBtn = "h-8 px-3 rounded-lg border border-border bg-white hover:bg-soft text-[11.5px] font-semibold text-ink inline-flex items-center gap-1.5 transition";

/* ------------------------------------------------------------------ activity score (fully transparent) */
export function ScoreBreakdown({ node, config }: { node: GeoStatsNode; config: GeoConfig }) {
  const a = node.activity, c = HEAT_COLOR[a.level];
  return (
    <div className="rounded-xl border border-border bg-[#FBFCFA] p-3.5">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-faint">Location activity</p>
          <p className="text-[30px] leading-none font-semibold text-ink tabular-nums mt-1">{a.score}<span className="text-[13px] text-faint font-medium"> / {a.cap}</span></p>
        </div>
        <LevelPill level={a.level} />
      </div>
      <div className="relative h-2 rounded-full bg-[#E6EBE5] mt-3 overflow-visible">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, (a.score / a.cap) * 100)}%`, background: `linear-gradient(90deg, ${HEAT_COLOR.low}, ${c})` }} />
        {[config.thresholds.medium, config.thresholds.high].map((t) => (
          <span key={t} className="absolute -top-1 h-4 w-px bg-ink/30" style={{ left: `${(t / a.cap) * 100}%` }} title={`threshold ${t}`} />
        ))}
      </div>
      <p className="text-[10px] font-semibold text-faint mt-1.5 uppercase tracking-wide">Factors</p>
      <div className="mt-1 space-y-1">
        {a.factors.map((f) => (
          <div key={f.key} className="flex items-center justify-between text-[11.5px]">
            <span className="text-ink"><b className="text-brand">+</b> {f.value} {f.value === 1 && f.label.endsWith("s") ? f.label.slice(0, -1) : f.label}</span>
            <span className="text-muted tabular-nums">× {f.weight} = <b className="text-ink">{f.points}</b></span>
          </div>
        ))}
        <div className="flex items-center justify-between text-[11.5px] border-t border-border/60 pt-1.5 mt-1">
          <span className="text-muted">Total{a.capped ? ` (capped at ${a.cap})` : ""}</span><b className="text-ink tabular-nums">{a.raw}</b>
        </div>
      </div>
      <p className="text-[10.5px] text-faint mt-2.5 leading-relaxed">
        Observed activity in this investigation only — not a risk, crime or person score. High ≥ {config.thresholds.high}, Medium ≥ {config.thresholds.medium} (server-configurable).
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ compact location card */
export function LocationCard({ node, onEvidence }: { node: GeoStatsNode; onEvidence?: () => void }) {
  const tierText = node.tier === "mixed" ? "Mixed provenance" : TIER_LABEL[node.tier];
  return (
    <div className="rounded-2xl overflow-hidden border border-[#16333c] bg-[linear-gradient(160deg,#0d2a35,#07141b)] text-[#dff5ec] shadow-soft">
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[9.5px] uppercase tracking-[0.16em] text-[#6f968a]">Location activity</p>
          <h4 className="text-[17px] font-semibold text-white leading-tight truncate">{node.name}{node.country ? `, ${node.country}` : ""}</h4>
        </div>
        <LevelPill level={node.activity.level} compact />
      </div>
      <div className="grid grid-cols-4 gap-px bg-white/10 border-y border-white/10">
        {[["Observations", node.observation_count], ["Sources", node.unique_sources], ["Platforms", node.platforms.length], ["Events", node.propagation_events]].map(([l, v]) => (
          <div key={l as string} className="bg-[#0a1e28] px-2 py-2.5 text-center">
            <p className="text-[19px] font-semibold text-white tabular-nums leading-none">{v}</p>
            <p className="text-[9px] uppercase tracking-wider text-[#6f968a] mt-1">{l}</p>
          </div>
        ))}
      </div>
      <div className="px-4 py-3 grid grid-cols-2 gap-3 text-[11px]">
        <div><p className="text-[#6f968a] text-[9.5px] uppercase tracking-wider">First observed</p><p className="text-white font-semibold mt-0.5">{fmtShort(node.first_observed)}</p></div>
        <div><p className="text-[#6f968a] text-[9.5px] uppercase tracking-wider">Last observed</p><p className="text-white font-semibold mt-0.5">{fmtShort(node.last_observed)}</p></div>
        <div><p className="text-[#6f968a] text-[9.5px] uppercase tracking-wider">Location</p><p className="font-semibold mt-0.5" style={{ color: TIER_COLOR[node.tier] }}>{tierText}</p></div>
        <div><p className="text-[#6f968a] text-[9.5px] uppercase tracking-wider">Confidence</p><p className="text-white font-semibold mt-0.5">{node.confidence_label} · {Math.round(node.confidence)}%</p></div>
      </div>
      {onEvidence && (
        <button onClick={onEvidence} className="w-full h-9 border-t border-white/10 text-[11.5px] font-semibold text-[#4fe3a1] hover:bg-white/5 transition inline-flex items-center justify-center gap-1.5">
          <FileSearch size={13} /> View Evidence
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ full location intelligence panel */
export function LocationDetailPanel({ node, config, busy, onClose, onEdit, onRemove, onLocate, onViewSources, onViewEvidence, onViewTimeline }: {
  node: GeoStatsNode; config: GeoConfig; busy: boolean; onClose: () => void;
  onEdit: (o: GeoObservation) => void; onRemove: (o: GeoObservation) => void; onLocate: (o: GeoObservation) => void;
  onViewSources: () => void; onViewEvidence: () => void; onViewTimeline: () => void;
}) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10.5px] uppercase tracking-wider text-faint">Location intelligence</p>
          <h3 className="text-[18px] font-semibold text-ink leading-tight">{node.name}</h3>
        </div>
        <button onClick={onClose} className="text-[11px] text-muted hover:text-ink">close</button>
      </div>
      <div className="flex flex-wrap gap-2 mt-3"><TierBadge tier={node.tier} /><LevelPill level={node.activity.level} /></div>
      <div className="flex flex-wrap gap-2 mt-3">
        <button className={actBtn} onClick={onViewSources}><Share2 size={12} /> View Sources</button>
        <button className={actBtn} onClick={onViewEvidence}><FileSearch size={12} /> View Evidence</button>
        <button className={actBtn} onClick={onViewTimeline}><Clock size={12} /> View Timeline</button>
      </div>

      <div className="mt-5"><ScoreBreakdown node={node} config={config} /></div>

      <div className="mt-5">
        <Section title="Location">
          <Row k="City" v={node.city ?? <span className="text-faint font-normal">Not recorded</span>} />
          <Row k="State / Region" v={node.region ?? <span className="text-faint font-normal">Not recorded</span>} />
          <Row k="Country" v={node.country ?? <span className="text-faint font-normal">Not recorded</span>} />
          <Row k="Latitude" v={<span className="font-mono">{node.latitude.toFixed(5)}</span>} />
          <Row k="Longitude" v={<span className="font-mono">{node.longitude.toFixed(5)}</span>} />
        </Section>
        <Section title="Observations">
          <Row k="Total observations" v={node.observation_count} />
          <Row k="Unique sources" v={node.unique_sources} />
          <Row k="Unique platforms" v={<>{node.platforms.length} <span className="text-muted font-normal">({node.platforms.join(", ")})</span></>} />
          <Row k="Propagation events" v={node.propagation_events} />
        </Section>
        <Section title="Time">
          <Row k="First observed" v={formatObserved(node.first_observed)} />
          <Row k="Last observed" v={formatObserved(node.last_observed)} />
        </Section>
        <Section title="Evidence">
          <Row k="Evidence IDs" v={<Chips items={node.evidence_labels} />} />
          <Row k="Source IDs" v={<Chips items={node.source_labels} />} />
          <Row k="Related media" v={<span className="font-mono text-[11.5px]">Case media (this investigation)</span>} />
        </Section>
        <Section title="Location quality">
          {(["verified", "investigator", "inferred"] as const).map((t) => (
            <div key={t} className="flex items-center justify-between text-[12px]">
              <span className="inline-flex items-center gap-2 text-muted"><span className="h-2 w-2 rounded-full" style={{ background: TIER_COLOR[t] }} />{TIER_LABEL[t]}</span>
              <span className="font-semibold text-ink tabular-nums">{node.tier_counts[t]}</span>
            </div>
          ))}
        </Section>
        <Section title="Confidence">
          <div><p className="text-[12px] text-muted mb-1.5">Location confidence · {node.confidence_label}</p><ConfBar value={node.confidence} /></div>
          <p className="text-[10.5px] text-faint">Source-level confidence is shown per observation below where recorded.</p>
        </Section>
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-faint mb-2.5">Provenance per observation</p>
        <div className="space-y-2.5">
          {node.observations.map((o) => (
            <div key={o.source_id} className="rounded-xl border border-border p-3 bg-[#FBFCFA]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-semibold text-ink">{o.label} · {o.platform}</span>
                <TierBadge tier={o.tier} />
              </div>
              <p className="text-[11px] text-muted mt-1.5">Source: {PROV_LABEL[o.provenance] ?? o.provenance} · Observed {formatObserved(o.observed_at)}</p>
              <p className="text-[11px] text-muted mt-1 leading-relaxed">{o.basis ?? "Basis not recorded."}</p>
              <p className="text-[10.5px] text-faint mt-1">Evidence: {o.evidence_labels.length ? o.evidence_labels.join(", ") : "none linked"}{o.location_id ? ` · Location ${o.location_id.slice(0, 8)}` : ""}</p>
              <div className="mt-2"><ConfBar value={o.confidence} /></div>
              <div className="flex gap-3 mt-2">
                <button onClick={() => onLocate(o)} className="text-[11px] font-semibold text-brand hover:underline inline-flex items-center gap-1"><LocateFixed size={11} /> Locate on map</button>
                {o.provenance === "investigator_supplied" && (<>
                  <button disabled={busy} onClick={() => onEdit(o)} className="text-[11px] font-semibold text-brand hover:underline inline-flex items-center gap-1"><Pencil size={11} /> Edit</button>
                  <button disabled={busy} onClick={() => onRemove(o)} className="text-[11px] font-semibold text-[#8A4138] hover:underline inline-flex items-center gap-1"><Trash2 size={11} /> Remove</button>
                </>)}
              </div>
              {o.provenance === "exif_gps" && <p className="text-[10.5px] text-faint mt-2">EXIF-derived locations are preserved evidence and cannot be edited.</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ hotspots */
export function HotspotsPanel({ hotspots, config, selectedId, onSelect }: {
  hotspots: Hotspot[]; config: GeoConfig; selectedId: string | null; onSelect: (id: string) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-[15px] font-semibold text-ink flex items-center gap-2"><Flame size={16} className="text-[#f0523f]" /> Hotspots</h3>
        <span className="text-[10.5px] text-faint">{hotspots.length} location{hotspots.length === 1 ? "" : "s"}</span>
      </div>
      <p className="text-[11.5px] text-muted mt-1.5 leading-relaxed">
        Ranked by transparent activity score (observations, unique sources, propagation events). Levels describe observed activity only.
      </p>
      {hotspots.length === 0 ? (
        <p className="text-[12px] text-faint mt-4">No locations in the current view.</p>
      ) : (
        <div className="mt-3 space-y-2">
          {hotspots.map((h) => (
            <button key={h.id} onClick={() => onSelect(h.id)}
              className={`w-full text-left rounded-xl border px-3 py-2.5 transition hover:shadow-card ${selectedId === h.id ? "border-brand bg-soft/60" : "border-border bg-white hover:bg-[#FAFBF9]"}`}>
              <div className="flex items-center gap-2.5">
                <span className="h-6 w-6 rounded-lg text-[10.5px] font-bold flex items-center justify-center text-white" style={{ background: HEAT_COLOR[h.level] }}>{h.rank}</span>
                <span className="text-[12.5px] font-semibold text-ink flex-1 truncate">{h.name}</span>
                <LevelPill level={h.level} compact />
              </div>
              <div className="flex items-center gap-3 mt-2 pl-[34px] text-[10.5px] text-muted tabular-nums">
                <span><b className="text-ink">{h.observations}</b> obs</span>
                <span><b className="text-ink">{h.unique_sources}</b> src</span>
                <span><b className="text-ink">{h.propagation_events}</b> events</span>
                <span className="ml-auto">score <b className="text-ink">{h.score}</b></span>
              </div>
            </button>
          ))}
        </div>
      )}
      <p className="text-[10px] text-faint mt-3">Thresholds: High ≥ {config.thresholds.high} · Medium ≥ {config.thresholds.medium} · Low below. Configurable server-side.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ earliest observed */
export function EarliestCard({ e, onSelect }: { e: GeoStats["earliest_observed"]; onSelect: (id: string) => void }) {
  return (
    <div className="rounded-2xl border border-border bg-card shadow-card p-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-faint flex items-center gap-1.5"><Sparkles size={12} className="text-brand" /> Earliest observed</p>
      {!e ? <p className="text-[12px] text-faint mt-2">No timestamped locations in the current view.</p> : (
        <>
          <button onClick={() => onSelect(e.node_id)} className="text-left mt-2 group">
            <p className="text-[10.5px] text-muted">Earliest Observed Location</p>
            <p className="text-[17px] font-semibold text-ink group-hover:text-brand transition">{e.name}</p>
          </button>
          <div className="flex items-center gap-2 mt-1.5 text-[11.5px] text-muted flex-wrap">
            <span>Observed <b className="text-ink">{formatObserved(e.observed_at)}</b></span><span>·</span><span>{e.source_label} · {e.platform}</span>
          </div>
          <p className="text-[10.5px] text-faint mt-2.5 leading-relaxed flex gap-1.5"><Info size={12} className="shrink-0 mt-px" />
            The earliest recorded observation in this view. An upload timestamp may not reflect the original online publication, so this is not treated as the original source.</p>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ compare */
export function ComparePanel({ nodes }: { nodes: GeoStatsNode[] }) {
  const [a, setA] = useState<string>(""); const [b, setB] = useState<string>("");
  const ids = useMemo(() => nodes.map((n) => n.id), [nodes]);
  const A = nodes.find((n) => n.id === (ids.includes(a) ? a : ids[0])) ?? null;
  const B = nodes.find((n) => n.id === (ids.includes(b) ? b : ids.find((i) => i !== A?.id) ?? "")) ?? null;
  const sel = "h-9 rounded-lg border border-border bg-white px-2 text-[12px] font-medium text-ink outline-none focus:ring-2 focus:ring-brand/15 min-w-0 w-full";
  const rows: [string, (n: GeoStatsNode) => React.ReactNode][] = [
    ["Observations", (n) => n.observation_count], ["Unique sources", (n) => n.unique_sources], ["Platforms", (n) => n.platforms.length],
    ["Propagation events", (n) => n.propagation_events], ["Activity score", (n) => `${n.activity.score} · ${n.activity.level_label}`],
    ["Location type", (n) => TIER_LABEL[n.tier]], ["First observed", (n) => fmtShort(n.first_observed)], ["Last observed", (n) => fmtShort(n.last_observed)],
  ];
  const earlier = A && B ? (new Date(A.first_observed) < new Date(B.first_observed) ? A : new Date(B.first_observed) < new Date(A.first_observed) ? B : null) : null;
  return (
    <div>
      <h3 className="text-[15px] font-semibold text-ink flex items-center gap-2"><GitCompare size={16} className="text-brand" /> Compare locations</h3>
      {nodes.length < 2 ? <p className="text-[12px] text-faint mt-3">At least two locations are needed to compare.</p> : (
        <>
          <div className="grid grid-cols-2 gap-2 mt-3">
            <select className={sel} value={A?.id ?? ""} onChange={(e) => setA(e.target.value)}>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select>
            <select className={sel} value={B?.id ?? ""} onChange={(e) => setB(e.target.value)}>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select>
          </div>
          {A && B && (
            <div className="mt-3 rounded-xl border border-border overflow-hidden text-[11.5px]">
              <div className="grid grid-cols-[1fr_1fr_1fr] bg-soft/70 font-semibold text-ink"><span className="px-2.5 py-2" /><span className="px-2.5 py-2 truncate">{A.name}</span><span className="px-2.5 py-2 truncate">{B.name}</span></div>
              {rows.map(([k, f]) => (
                <div key={k} className="grid grid-cols-[1fr_1fr_1fr] border-t border-border/60">
                  <span className="px-2.5 py-2 text-muted">{k}</span><span className="px-2.5 py-2 font-semibold text-ink tabular-nums">{f(A)}</span><span className="px-2.5 py-2 font-semibold text-ink tabular-nums">{f(B)}</span>
                </div>
              ))}
            </div>
          )}
          <p className="text-[10.5px] text-faint mt-2.5 leading-relaxed">
            {earlier ? `${earlier.name} has the earlier first observation. ` : ""}Comparing recorded activity does not establish that one location caused the other.
          </p>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ heat legend (globe overlay) */
export function HeatLegend({ metric, config, max }: { metric: GeoMetric; config: GeoConfig; max: number }) {
  return (
    <div className="w-[248px] rounded-xl bg-[#0b1a24]/88 border border-white/10 p-3.5 text-[10.5px] text-[#b6d6ca] backdrop-blur space-y-2">
      <b className="text-white text-[11.5px]">Heat · {METRIC_LABEL[metric]}</b>
      <div className="h-2 rounded-full" style={{ background: `linear-gradient(90deg, ${HEAT_COLOR.low}, ${HEAT_COLOR.medium}, ${HEAT_COLOR.high})` }} />
      <div className="flex justify-between text-[9.5px]"><span>Low activity</span><span>Medium</span><span>High</span></div>
      <p className="leading-relaxed text-[#8db3a5]">Colour = activity level (score: Medium ≥ {config.thresholds.medium}, High ≥ {config.thresholds.high}). {METRIC_HELP[metric]} Busiest location in view: {max}.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ empty states */
export const EMPTY_COPY: Record<Exclude<EmptyReason, null>, { title: string; body: string }> = {
  no_locations: { title: "No geographic evidence available yet.", body: "No geographic observations available for this investigation. Locations appear only from real metadata (EXIF GPS) or ones you add — nothing is invented." },
  no_time_range: { title: "No observations in this time range.", body: "No observations were recorded during this time range. Widen the timeline or reset it." },
  no_platform: { title: "No geographic data for this platform.", body: "No sources from the selected platform have associated geographic data." },
  no_verified: { title: "No verified locations.", body: "No verified geographic observations are available." },
  no_investigator: { title: "No investigator-supplied locations.", body: "No investigator-supplied geographic observations match the current filters." },
  no_inferred: { title: "No inferred locations.", body: "No inferred geographic observations match the current filters." },
};
export function EmptyOverlay({ reason, canAdd, onAdd, onReset }: { reason: Exclude<EmptyReason, null>; canAdd: boolean; onAdd: () => void; onReset: () => void }) {
  const c = EMPTY_COPY[reason];
  return (
    <div className="absolute inset-x-0 bottom-28 mx-auto max-w-md text-center rounded-2xl bg-[#0b1a24]/88 border border-white/10 p-5 backdrop-blur">
      <MapPin size={22} className="mx-auto text-[#4fe3a1] mb-2" />
      <p className="text-[13.5px] font-semibold text-white">{c.title}</p>
      <p className="text-[12px] text-[#9fc3b6] mt-1.5 leading-relaxed">{c.body}</p>
      <div className="mt-3 flex justify-center gap-2">
        {reason === "no_locations" ? (
          <button onClick={onAdd} className="h-8 px-3.5 rounded-lg bg-[#4fe3a1] text-[#062018] text-[12px] font-semibold inline-flex items-center gap-1.5 hover:brightness-110"><Plus size={13} /> Add Location</button>
        ) : (
          <button onClick={onReset} className="h-8 px-3.5 rounded-lg bg-white/10 text-white text-[12px] font-semibold hover:bg-white/15">Reset filters</button>
        )}
      </div>
      {reason === "no_locations" && !canAdd && <p className="text-[10.5px] text-[#7fa89a] mt-2">Add a source first (Source Graph tab), then attach a location to it.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ connection panel (Phase 1, unchanged behaviour) */
export function EdgePanel({ edge, from, to, fpHash, busy, onClose, onConfirm, onRevoke, onViewSource }: {
  edge: GeoEdge; from: string; to: string; fpHash?: string; busy: boolean; onClose: () => void;
  onConfirm: (rid: string, note?: string) => void; onRevoke: (rid: string) => void;
  /** Phase 6: open the relationship's origin source in the Source Graph (by source label, e.g. SRC-A). */
  onViewSource?: (label: string) => void;
}) {
  const [note, setNote] = useState("");
  const color = EDGE_COLOR[edge.mode];
  const first = edge.relationships[0];
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10.5px] uppercase tracking-wider text-faint">Connection</p>
          <h3 className="text-[16px] font-semibold text-ink leading-tight flex items-center gap-2 flex-wrap">
            {from} <span style={{ color }}>{edge.mode === "undirected" ? "—" : <ArrowRight size={16} />}</span> {to}
          </h3>
        </div>
        <button onClick={onClose} className="text-[11px] text-muted hover:text-ink">close</button>
      </div>
      <div className="mt-3 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[10.5px] font-semibold border" style={{ color, borderColor: color + "66", background: color + "18" }}>
        {edge.mode === "inferred" && "⚠ "}{MODE_LABEL[edge.mode]}
      </div>
      <p className="text-[11.5px] text-muted mt-2 leading-relaxed">{edge.basis}</p>
      <div className="mt-4 space-y-2.5">
        <Row k="Source location" v={from} />
        <Row k="Destination location" v={to} />
        <Row k="Platform / source" v={edge.platforms.join(" ↔ ")} />
        <Row k="Relationship" v={edge.types.join(", ")} />
        <Row k="Propagated observations" v={edge.count} />
        <Row k="Timestamp" v={edge.first_timestamp === edge.last_timestamp ? formatObserved(edge.last_timestamp) : `${formatObserved(edge.first_timestamp)} – ${formatObserved(edge.last_timestamp)}`} />
        <Row k="Similarity" v={edge.similarity != null ? `${edge.similarity}% (recorded match score)` : "Not available"} />
        <Row k="Fingerprint (case media aHash)" v={fpHash ? <span className="font-mono inline-flex items-center gap-1"><Fingerprint size={11} />{fpHash}</span> : "Not available"} />
        <div className="pt-1"><p className="text-[12px] text-muted mb-1.5">Confidence</p>{edge.confidence != null ? <ConfBar value={edge.confidence} /> : <span className="text-[12px] font-semibold text-ink">Not available</span>}</div>
      </div>

      <div className="mt-5 border-t border-border pt-4 space-y-2.5">
        <p className="text-[11px] uppercase tracking-wider text-faint">Underlying links</p>
        {edge.relationships.map((r) => (
          <div key={r.relationship_id} className="rounded-xl border border-border p-3 bg-[#FBFCFA] text-[11.5px]">
            <p className="font-semibold text-ink">{r.from_label} ({r.from_platform}) → {r.to_label} ({r.to_platform})</p>
            <p className="text-muted mt-1">{r.type} · {formatObserved(r.from_observed)} → {formatObserved(r.to_observed)}</p>
            <p className="text-muted mt-0.5">Evidence: {r.evidence_labels.length ? r.evidence_labels.join(", ") : "Not available"}</p>
            {onViewSource && (
              <button onClick={() => onViewSource(r.from_label)} className="mt-1.5 text-[11.5px] font-semibold text-brand hover:underline">View in Source Graph</button>
            )}
            {edge.mode === "inferred" && (
              <div className="mt-2 space-y-1.5">
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Basis for confirming direction (optional)" className="w-full h-8 rounded-lg border border-border px-2.5 text-[11.5px] outline-none focus:ring-2 focus:ring-brand/15" />
                <button disabled={busy} onClick={() => onConfirm(r.relationship_id, note || undefined)} className="text-[11.5px] font-semibold text-brand hover:underline">Confirm this direction as investigator</button>
              </div>
            )}
            {edge.mode === "confirmed" && (
              <button disabled={busy} onClick={() => onRevoke(r.relationship_id)} className="mt-2 text-[11.5px] font-semibold text-[#8A4138] hover:underline">Revoke confirmation</button>
            )}
          </div>
        ))}
      </div>
      {first && edge.mode === "undirected" && <p className="text-[10.5px] text-faint mt-3">Direction is not asserted for this relationship, so no arrow is drawn.</p>}
    </div>
  );
}
