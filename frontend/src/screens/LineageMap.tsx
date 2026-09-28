import { useState } from "react";
import { Info, Plus, Minus, Maximize2, MousePointer2, ExternalLink } from "lucide-react";
import { useCase } from "../context/CaseContext";
import { toDisplaySources, toDisplayRelationships } from "../lib/adapters";
import { AsyncBlock, EmptyState } from "../components/states";
import { Panel, PanelHeader, PrimaryButton, StatusBadge } from "../components/ui";
import AddSourceModal from "../components/AddSourceModal";

const pos: any = {
  "SRC-A": [350, 70],
  "SRC-B": [170, 210],
  "SRC-C": [530, 210],
  "SRC-D": [350, 350],
  "SRC-E": [700, 350],
};

export default function LineageMap() {
  const { sources: sourcesSlice, relationships: relsSlice } = useCase();
  const sources = toDisplaySources(sourcesSlice.data);
  const sourceRelationships = toDisplayRelationships(relsSlice.data, sources);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [showAddSource, setShowAddSource] = useState(false);
  const selected = sources.find((s) => s.id === selectedId) ?? sources[0] ?? null;

  // Node positions are keyed by display label (SRC-A…SRC-E). Sources beyond
  // the five the layout was designed for fall back to a generated position
  // rather than crashing on a missing key.
  function posFor(label: string, index: number): [number, number] {
    return pos[label] ?? [150 + (index % 4) * 200, 430 + Math.floor(index / 4) * 90];
  }

  return (
    <div className="space-y-6">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border rounded-2xl p-5 sm:p-6 shadow-card">
        <div>
          <h2 className="text-xl font-semibold tracking-[-.02em] text-ink">Content Lineage</h2>
          <p className="text-[13px] text-muted mt-1 leading-relaxed">
            Visualize how this media appears to have propagated across sources.
          </p>
        </div>
        <button
          onClick={() => setShowAddSource(true)}
          className="rounded-xl bg-brand text-white px-4 py-2 text-[12.5px] font-semibold hover:bg-brandDark transition"
        >
          + Add Source
        </button>
        {showAddSource && <AddSourceModal onClose={() => setShowAddSource(false)} />}
      </div>

      <div className="grid xl:grid-cols-[1fr_340px] gap-5">
        <Panel className="p-0 overflow-hidden flex flex-col justify-between">
          <div className="p-4 border-b border-border flex justify-between items-center bg-card">
            <div className="flex items-center gap-2 text-[12px] text-muted font-medium">
              <MousePointer2 size={15} className="text-brand" /> Click a source to inspect its evidence
            </div>
            <div className="flex gap-1.5">
              <button
                onClick={() => setZoom((z) => Math.max(0.7, z - 0.1))}
                className="h-8 w-8 rounded-lg border border-border hover:bg-soft transition flex items-center justify-center text-ink"
              >
                <Minus size={14} />
              </button>
              <button
                onClick={() => setZoom((z) => Math.min(1.3, z + 0.1))}
                className="h-8 w-8 rounded-lg border border-border hover:bg-soft transition flex items-center justify-center text-ink"
              >
                <Plus size={14} />
              </button>
              <button
                onClick={() => setZoom(1)}
                className="h-8 w-8 rounded-lg border border-border hover:bg-soft transition flex items-center justify-center text-ink"
              >
                <Maximize2 size={14} />
              </button>
            </div>
          </div>

          <AsyncBlock
            loading={sourcesSlice.loading}
            error={sourcesSlice.error}
            loadingLabel="Loading propagation graph…"
            isEmpty={sources.length === 0}
            empty={
              <div className="p-6">
                <EmptyState
                  title="No propagation data yet"
                  detail="The lineage graph is built from the sources you record. Add the first observed source to start building it."
                  action={<PrimaryButton onClick={() => setShowAddSource(true)}>+ Add Source</PrimaryButton>}
                />
              </div>
            }
          >
          <div className="relative h-[480px] sm:h-[520px] bg-[#FAFBF9] overflow-hidden">
            <svg viewBox="0 0 900 500" className="w-full h-full transition-transform duration-300" style={{ transform: `scale(${zoom})` }}>
              {sourceRelationships.map((r, i) => {
                const aIdx = sources.findIndex((s) => s.label === r.fromLabel);
                const bIdx = sources.findIndex((s) => s.label === r.toLabel);
                if (aIdx === -1 || bIdx === -1) return null;
                const a = posFor(r.fromLabel, aIdx),
                  b = posFor(r.toLabel, bIdx);
                return (
                  <g key={i}>
                    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#A8B5A9" strokeWidth="2" />
                    <rect x={(a[0] + b[0]) / 2 - 35} y={(a[1] + b[1]) / 2 - 13} width="70" height="26" rx="13" fill="#fff" stroke="#DDE2DC" />
                    <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 + 4} textAnchor="middle" fontSize="10" fontWeight="600" fill="#3E503C">
                      {r.confidence != null ? `${r.confidence}%` : "—"}
                    </text>
                  </g>
                );
              })}
              {sources.map((s, idx) => {
                const [x, y] = posFor(s.label, idx);
                const active = selected?.id === s.id;
                return (
                  <g key={s.id} onClick={() => setSelectedId(s.id)} className="cursor-pointer group">
                    <rect
                      x={x - 95}
                      y={y - 34}
                      width="190"
                      height="68"
                      rx="16"
                      fill="#fff"
                      stroke={active ? "#3E503C" : "#DDE2DC"}
                      strokeWidth={active ? 2.5 : 1}
                      className="transition-all"
                    />
                    <circle cx={x - 70} cy={y} r="17" fill="#E8EEE6" />
                    <text x={x - 70} y={y + 4} textAnchor="middle" fontSize="10" fontWeight="700" fill="#3E503C">
                      {s.label.replace("SRC-", "")}
                    </text>
                    <text x={x - 45} y={y - 9} fontSize="12" fontWeight="600" fill="#182421">
                      {s.platform}
                    </text>
                    <text x={x - 45} y={y + 8} fontSize="9.5" fill="#66716C">
                      {s.account}
                    </text>
                    <text x={x - 45} y={y + 23} fontSize="9" fill="#8A948F">
                      {s.observedAt.split(", ")[1]}
                    </text>
                  </g>
                );
              })}
            </svg>
            <div className="absolute top-4 right-4 rounded-xl bg-card border border-border p-3.5 text-[11px] shadow-card">
              <p className="font-semibold text-ink mb-2">Match Similarity</p>
              <p className="text-muted">● 90–100% Strong</p>
              <p className="text-muted">● 70–89% Similar</p>
              <p className="text-muted">● 50–69% Moderate</p>
            </div>
          </div>
          </AsyncBlock>
        </Panel>

        <div className="space-y-5">
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Source Details" />
            {!selected ? (
              <p className="text-[12.5px] text-muted mt-2">Select a source in the graph to inspect its evidence.</p>
            ) : (<>
            <div className="flex items-center justify-between mt-2">
              <b className="text-[15px] font-semibold text-ink">{selected.platform}</b>
              <StatusBadge tone="green">{selected.similarity != null ? `${selected.similarity}% Match` : "No score"}</StatusBadge>
            </div>
            <p className="text-[12px] text-muted mt-1">{selected.account}</p>
            <div className="mt-5 space-y-3 text-[12px]">
              {[
                ["Observed on", selected.observedAt],
                ["Relationship", selected.relationship],
                ["Source ID", selected.label],

              ].map(([a, b]) => (
                <div className="flex justify-between gap-3 border-b border-border/40 pb-2 last:border-0" key={a}>
                  <span className="text-muted">{a}</span>
                  <span className="font-semibold text-ink text-right">{b}</span>
                </div>
              ))}
            </div>
            <button className="mt-4 text-[12px] font-semibold text-brand hover:underline flex items-center gap-1">
              <ExternalLink size={14} /> View preserved evidence
            </button>
            </>)}
          </Panel>

          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Propagation Timeline" />
            {sources.length === 0 && <p className="text-[12.5px] text-muted mt-2">No sources recorded yet.</p>}
            <div className="space-y-4 border-l-2 border-border/60 ml-2.5 pl-5 mt-4">
              {sources.map((s) => (
                <div key={s.id} className="relative">
                  <span className="absolute -left-[26px] top-1 h-3 w-3 rounded-full bg-brand ring-4 ring-card" />
                  <p className="text-[12.5px] font-semibold text-ink">{s.platform}</p>
                  <p className="text-[11px] text-muted">{s.observedAt}</p>
                </div>
              ))}
            </div>
          </Panel>

          <div className="rounded-2xl bg-blue/70 p-4 text-[12px] text-[#3B5A7D] border border-blue shadow-xs">
            <Info size={16} className="inline mr-2 shrink-0" />
            This graph reflects sources recorded for this case. Automatic cross-platform discovery is a planned capability — see Roadmap.
          </div>
        </div>
      </div>
    </div>
  );
}
