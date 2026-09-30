import { useEffect, useState } from "react";
import { Sparkles, FileText, Link2, MapPin, Network, CircleHelp, Database, Send } from "lucide-react";
import { api, CopilotAnswer, CopilotFact, GraphHealth } from "../../lib/api";
import { useCase } from "../../context/CaseContext";
import { Panel, PanelHeader, StatusBadge } from "../ui";

/**
 * Phase 3B — Investigation Copilot. Asks the backend Graph RAG endpoint and renders the grounded answer with
 * every fact's category (verified / inference / unknown) and clickable links into the existing LINEAGE views.
 * All retrieval, grounding and any LLM call happen server-side; no key or credential reaches the browser.
 */
const SUGGESTED = [
  "Where has this media appeared?",
  "Which sources are connected?",
  "What locations are involved?",
  "What is the propagation path?",
  "What evidence supports this relationship?",
  "What information is missing?",
];

const CAT: Record<CopilotFact["category"], { label: string; tone: "green" | "amber" | "gray" }> = {
  VERIFIED_FACT: { label: "Verified fact", tone: "green" },
  INFERENCE: { label: "Inference", tone: "amber" },
  UNKNOWN: { label: "Unknown", tone: "gray" },
};

export type CopilotLinks = {
  onOpenEvidence?: () => void;
  onOpenSource?: (sourceId: string) => void;
  onOpenLocation?: (mapNodeId: string) => void;
  onOpenGraph?: (sourceId?: string) => void;
};

function fmt(iso: string | null) {
  if (!iso) return "time not recorded";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

const chip = "inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-[11px] font-medium text-ink hover:border-brand hover:text-brand transition";

export default function InvestigationCopilot({ onOpenEvidence, onOpenSource, onOpenLocation, onOpenGraph }: CopilotLinks) {
  const { incidentId } = useCase();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<CopilotAnswer | null>(null);
  const [health, setHealth] = useState<GraphHealth | null>(null);

  useEffect(() => { api.getGraphHealth().then(setHealth).catch(() => setHealth(null)); }, []);

  async function ask(q: string) {
    if (!incidentId || !q.trim()) return;
    setQuestion(q);
    setBusy(true); setErr(null);
    try { setRes(await api.askCopilot(incidentId, q.trim())); }
    catch (e: any) { setErr(e?.message ?? "The Copilot could not answer."); }
    finally { setBusy(false); }
  }

  const src = res?.graph_context.graph_source;
  const codeOf = (nodeId: string) => {
    const n = res?.graph_context.nodes.find((x) => x.id === nodeId);
    return n?.code ?? n?.label ?? nodeId;
  };
  const sourceIdOf = (nodeId: string) => (nodeId.startsWith("source:") ? nodeId.slice(7) : undefined);

  return (
    <div className="space-y-5">
      <Panel className="p-5 sm:p-6">
        <PanelHeader
          title="Investigation Copilot"
          subtitle="Ask about this investigation. Answers are built only from recorded sources, evidence, locations and graph relationships."
          right={
            <StatusBadge tone={health?.status === "connected" ? "green" : "gray"}>
              <Database size={11} /> {health?.status === "connected" ? "Graph: Neo4j" : "Neo4j unavailable — using in-memory graph."}
            </StatusBadge>
          }
        />
        <form onSubmit={(e) => { e.preventDefault(); ask(question); }} className="flex flex-col sm:flex-row gap-2">
          <input
            value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000}
            placeholder="e.g. What is the propagation path?"
            className="flex-1 h-11 rounded-xl border border-border bg-white px-4 text-[13px] text-ink outline-none focus:ring-2 focus:ring-brand/15"
          />
          <button type="submit" disabled={busy || !question.trim()}
            className="h-11 rounded-xl bg-brand text-white px-5 text-[12.5px] font-semibold hover:bg-brandDark transition disabled:opacity-50 inline-flex items-center justify-center gap-2">
            <Send size={14} /> {busy ? "Asking…" : "Ask"}
          </button>
        </form>
        <div className="flex flex-wrap gap-1.5 mt-3">
          {SUGGESTED.map((q) => (
            <button key={q} onClick={() => ask(q)} disabled={busy} className={chip}>{q}</button>
          ))}
        </div>
        {err && <p className="mt-3 text-[12.5px] text-[#8A4138]">{err}</p>}
      </Panel>

      {res && (
        <div className="grid xl:grid-cols-[1fr_340px] gap-5">
          <div className="space-y-5">
            <Panel className="p-5 sm:p-6">
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <Sparkles size={15} className="text-brand" />
                <b className="text-[14px] text-ink">Answer</b>
                {res.insufficient_evidence && <StatusBadge tone="red">Insufficient evidence</StatusBadge>}
                <StatusBadge tone="blue">{res.answer_source === "llm" ? `Written by ${res.llm.model ?? "LLM"} from retrieved facts` : "Deterministic (no LLM)"}</StatusBadge>
                {src && <StatusBadge tone={src.backend === "neo4j" ? "green" : "gray"}>{src.backend === "neo4j" ? "Read from Neo4j" : "In-memory graph"}</StatusBadge>}
              </div>
              <pre className="whitespace-pre-wrap font-sans text-[12.5px] leading-relaxed text-ink">{res.answer}</pre>
              {!res.llm.used && (
                <p className="text-[11px] text-muted mt-3">
                  {res.llm.status === "rejected_ungrounded"
                    ? `LLM answer discarded (not grounded) — showing grounded graph/evidence context. ${res.llm.reason ?? ""}`
                    : "LLM unavailable — showing grounded graph/evidence context."}
                </p>
              )}
              {src?.fallback && src.reason && <p className="text-[11px] text-muted mt-1">Graph: {src.reason}</p>}
            </Panel>

            <Panel className="p-5 sm:p-6">
              <PanelHeader title="Facts used" subtitle="Each statement keeps the status recorded in the graph. Inferences and unknowns are never shown as verified." />
              {[...res.verified_facts, ...res.inferences, ...res.unknowns].length === 0 && (
                <p className="text-[12.5px] text-muted">Insufficient evidence. No recorded fact answers this question.</p>
              )}
              <div className="space-y-2.5">
                {[...res.verified_facts, ...res.inferences, ...res.unknowns].map((f, i) => (
                  <div key={i} className="rounded-xl border border-border/70 p-3">
                    <div className="flex items-start gap-2">
                      <StatusBadge tone={CAT[f.category].tone}>{CAT[f.category].label}</StatusBadge>
                      {f.status && <span className="text-[10.5px] text-faint mt-1 font-mono">{f.status}</span>}
                    </div>
                    <p className="text-[12.5px] text-ink mt-2 leading-relaxed">{f.statement}</p>
                    {f.relationships.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {f.relationships.map((r, j) => (
                          <button key={j} className={chip} onClick={() => onOpenGraph?.(sourceIdOf(r.source) ?? sourceIdOf(r.target))}
                            title="Open in the Source Graph">
                            <Network size={11} /> {codeOf(r.source)} —{r.type}→ {codeOf(r.target)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="space-y-5">
            <Panel className="p-5">
              <PanelHeader title="Evidence used" />
              {res.evidence_used.length === 0 ? <p className="text-[12px] text-muted">No evidence item was used.</p> : (
                <div className="space-y-2">
                  {res.evidence_used.map((e) => (
                    <button key={e.id} onClick={() => onOpenEvidence?.()} className="w-full text-left rounded-xl border border-border/70 p-2.5 hover:border-brand transition">
                      <p className="text-[12px] font-semibold text-ink flex items-center gap-1.5"><FileText size={12} className="text-brand" /> {e.code ?? e.id.slice(0, 8)} · {(e.item_type ?? "evidence").replace(/_/g, " ")}</p>
                      <p className="text-[11px] text-muted mt-0.5">Captured {fmt(e.captured_at)} · ID {e.id.slice(0, 8)}</p>
                    </button>
                  ))}
                </div>
              )}
            </Panel>

            <Panel className="p-5">
              <PanelHeader title="Sources" />
              {res.sources_used.length === 0 ? <p className="text-[12px] text-muted">No source was used.</p> : (
                <div className="flex flex-wrap gap-1.5">
                  {res.sources_used.map((s) => (
                    <button key={s.id} className={chip} onClick={() => onOpenSource?.(s.id)} title={`${s.label} · observed ${fmt(s.observed_at)} · ID ${s.id}`}>
                      <Link2 size={11} /> {s.code} · {s.label}
                    </button>
                  ))}
                </div>
              )}
            </Panel>

            <Panel className="p-5">
              <PanelHeader title="Locations" />
              {res.locations_used.length === 0 ? <p className="text-[12px] text-muted">No location was used.</p> : (
                <div className="space-y-2">
                  {res.locations_used.map((l) => (
                    <button key={l.id} disabled={!l.map_node_id} onClick={() => l.map_node_id && onOpenLocation?.(l.map_node_id)}
                      className="w-full text-left rounded-xl border border-border/70 p-2.5 hover:border-brand transition">
                      <p className="text-[12px] font-semibold text-ink flex items-center gap-1.5"><MapPin size={12} className="text-brand" /> {l.label}</p>
                      <p className="text-[11px] text-muted mt-0.5">
                        {l.latitude.toFixed(4)}, {l.longitude.toFixed(4)} · {[l.city, l.region, l.country].filter(Boolean).join(", ") || "city/region not recorded"} · {l.tier}
                        {l.confidence != null ? ` · ${Math.round(l.confidence * 100)}%` : " · confidence not recorded"}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </Panel>

            <Panel className="p-5">
              <PanelHeader title="Unknowns & evidence gaps" />
              {res.evidence_gaps.length === 0 ? <p className="text-[12px] text-muted">No gap detected in the recorded data.</p> : (
                <ul className="space-y-1.5">
                  {res.evidence_gaps.map((g, i) => (
                    <li key={i} className="text-[11.5px] text-ink flex gap-1.5"><CircleHelp size={12} className="text-faint shrink-0 mt-0.5" /> {g.gap}</li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
