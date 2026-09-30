import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Plus, Minus, RotateCcw, RotateCw, Maximize2, Play, Pause, Orbit, MapPin, ArrowRight, Route, Clock,
  Crosshair, Layers, Info, Flame, Users, Share2, Eye, EyeOff, Filter, Radar,
} from "lucide-react";
import { useCase } from "../../context/CaseContext";
import { api, GeoData, GeoStats, GeoStatsNode, GeoMetric, TierFilter, GeoObservation } from "../../lib/api";
import { formatObserved } from "../../lib/adapters";
import { Panel } from "../ui";
import { GlobeEngine, TIER_COLOR, EDGE_COLOR, HEAT_COLOR, Layers as LayerSet } from "./globe";
import LocationEditor from "./LocationEditor";
import {
  EdgePanel, LocationCard, LocationDetailPanel, HotspotsPanel, EarliestCard, ComparePanel, HeatLegend, EmptyOverlay,
  TIER_LABEL, METRIC_LABEL, LEVEL_LABEL,
} from "./panels";

/* ------------------------------------------------------------------ constants */
type ViewMode = "propagation" | "nodes" | "heatmap" | "combined";
const MODES: { key: ViewMode; label: string; icon: typeof Route }[] = [
  { key: "propagation", label: "Propagation graph", icon: Route },
  { key: "nodes", label: "Location nodes", icon: MapPin },
  { key: "heatmap", label: "Heatmap", icon: Flame },
  { key: "combined", label: "Combined", icon: Layers },
];
const PRESET: Record<Exclude<ViewMode, "combined">, LayerSet> = {
  propagation: { heat: false, nodes: true, arcs: true },
  nodes: { heat: false, nodes: true, arcs: false },
  heatmap: { heat: true, nodes: false, arcs: false },
};
const TIER_FILTERS: { key: TierFilter; label: string }[] = [
  { key: "all", label: "All" }, { key: "verified", label: "Verified" }, { key: "investigator", label: "Investigator Supplied" }, { key: "inferred", label: "Inferred" },
];
const ms = (iso: string) => new Date(iso).getTime();
type Sel = { kind: "node" | "edge"; id: string } | null;

/* ------------------------------------------------------------------ component */
export default function PropagationMap({ onViewSources, onNavigate, focusNodeId }: { onViewSources?: (sourceId?: string) => void; onNavigate?: (s: any) => void; focusNodeId?: string | null }) {
  const { incidentId, sources, relationships, fingerprint } = useCase();

  // Phase 1 payload (unlocated sources + mutation results) and Phase 2 aggregated stats
  const [geo, setGeo] = useState<GeoData | null>(null);
  const [stats, setStats] = useState<GeoStats | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [statsBusy, setStatsBusy] = useState(false);
  const [tick, setTick] = useState(0);

  // view + filters
  const [mode, setMode] = useState<ViewMode>("combined");
  const [combined, setCombined] = useState<LayerSet>({ heat: true, nodes: true, arcs: true });
  const [tier, setTier] = useState<TierFilter>("all");
  const [platform, setPlatform] = useState<string>("all");
  const [metric, setMetric] = useState<GeoMetric>("observations");

  // selection + editing
  const [selected, setSelected] = useState<Sel>(null);
  const [hover, setHover] = useState<Sel>(null);
  const [editor, setEditor] = useState<null | { source: { id: string; label: string; platform: string }; initial?: any }>(null);
  const [legendOpen, setLegendOpen] = useState(true);
  const [autoRot, setAutoRot] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [sideTab, setSideTab] = useState<"hotspots" | "compare">("hotspots");

  // time window (ms). `touched` false => the window tracks the full extent of the data
  const [win, setWin] = useState<[number, number] | null>(null);
  const [touched, setTouched] = useState(false);
  const [playing, setPlaying] = useState(false);
  const winRef = useRef<[number, number] | null>(null);
  winRef.current = win;

  const mountRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<GlobeEngine | null>(null);
  const [webglOk, setWebglOk] = useState(true);

  /* ---- Phase 1 payload ---- */
  const loadGeo = useCallback(async () => {
    if (!incidentId) return;
    try { setGeo(await api.getGeo(incidentId)); } catch { /* stats effect reports errors */ }
  }, [incidentId]);
  useEffect(() => { loadGeo(); setTick((t) => t + 1); }, [loadGeo, sources.data, relationships.data]);

  /* ---- extent = full range of ALL located observations (independent of filters) ---- */
  const extent = useMemo<[number, number] | null>(() => {
    const tr = stats?.available.time_range;
    if (!tr?.start || !tr?.end) return null;
    const lo = ms(tr.start), hi = ms(tr.end);
    return [lo, hi === lo ? hi + 60000 : hi];
  }, [stats?.available.time_range?.start, stats?.available.time_range?.end]); // eslint-disable-line
  useEffect(() => { if (extent && (!touched || !win)) setWin(extent); }, [extent, touched]); // eslint-disable-line
  const [lo, hi] = win ?? extent ?? [0, 0];

  /* ---- server-side aggregation (debounced; stale responses dropped) ---- */
  const startIso = touched && extent && lo > extent[0] ? new Date(lo).toISOString() : undefined;
  const endIso = touched && extent && hi < extent[1] ? new Date(hi).toISOString() : undefined;
  const reqId = useRef(0);
  useEffect(() => {
    if (!incidentId) return;
    const id = ++reqId.current;
    const h = window.setTimeout(async () => {
      setStatsBusy(true);
      try {
        const s = await api.getGeoStats(incidentId, { start: startIso, end: endIso, platform, tier, metric });
        if (id === reqId.current) { setStats(s); setLoadErr(null); }
      } catch (e: any) {
        if (id === reqId.current) setLoadErr(e?.message ?? "Could not load geographic statistics.");
      } finally { if (id === reqId.current) setStatsBusy(false); }
    }, playing ? 0 : 130);
    return () => window.clearTimeout(h);
  }, [incidentId, startIso, endIso, platform, tier, metric, tick]); // eslint-disable-line

  /* ---- engine lifecycle (created once; data/layer changes never rebuild the renderer) ---- */
  useEffect(() => {
    if (!mountRef.current) return;
    try {
      const canvas = document.createElement("canvas");
      if (!(canvas.getContext("webgl2") || canvas.getContext("webgl"))) throw new Error("no webgl");
      const eng = new GlobeEngine(mountRef.current);
      eng.onSelect = (p) => setSelected(p);
      eng.onHover = (p) => setHover(p);
      engineRef.current = eng;
      return () => { eng.dispose(); engineRef.current = null; };
    } catch { setWebglOk(false); }
  }, []);

  const layers: LayerSet = mode === "combined" ? combined : PRESET[mode];
  useEffect(() => {
    if (!stats) return;
    engineRef.current?.setData(stats.nodes, stats.edges, { showEdges: true });
    engineRef.current?.select(selected);
  }, [stats?.nodes, stats?.edges]); // eslint-disable-line
  useEffect(() => { if (stats) engineRef.current?.setHeat(stats.heat.points); }, [stats?.heat]); // eslint-disable-line
  useEffect(() => { engineRef.current?.setLayers(layers); }, [layers.heat, layers.nodes, layers.arcs]); // eslint-disable-line
  useEffect(() => { engineRef.current?.select(selected); }, [selected]);

  /* ---- playback: steps through the real observation timestamps (filter-aware, from the server) ---- */
  const timesRef = useRef<number[]>([]);
  useEffect(() => { timesRef.current = (stats?.time_index ?? []).map(ms); }, [stats?.time_index]);
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const cur = winRef.current ?? extent;
      if (!cur) return setPlaying(false);
      const next = timesRef.current.find((t) => t > cur[1]);
      if (next === undefined) return setPlaying(false);
      setWin([cur[0], next]);
    }, 950);
    return () => window.clearInterval(id);
  }, [playing, extent]);
  function togglePlay() {
    if (playing) return setPlaying(false);
    const times = timesRef.current;
    if (!extent || !times.length) return;
    const start = touched ? lo : extent[0];
    const first = times.find((t) => t >= start) ?? times[0];
    setTouched(true); setWin([start, first]); setPlaying(true);
  }

  /* ---- derived ---- */
  const nodes: GeoStatsNode[] = stats?.nodes ?? [];
  const selNode = selected?.kind === "node" ? nodes.find((n) => n.id === selected.id) ?? null : null;
  const selEdge = selected?.kind === "edge" ? stats?.edges.find((e) => e.id === selected.id) ?? null : null;
  const nodeName = (id: string) => nodes.find((n) => n.id === id)?.name ?? geo?.nodes.find((n) => n.id === id)?.name ?? id;
  const hoverInfo = useMemo(() => {
    if (!hover || !stats) return null;
    if (hover.kind === "node") {
      const n = stats.nodes.find((x) => x.id === hover.id);
      return n ? `${n.name} · ${n.observation_count} obs · ${n.unique_sources} src · ${LEVEL_LABEL[n.activity.level]}` : null;
    }
    const e = stats.edges.find((x) => x.id === hover.id);
    return e ? `${nodeName(e.source)} ${e.mode === "undirected" ? "—" : "→"} ${nodeName(e.target)} · ${e.mode === "confirmed" ? "Confirmed direction" : e.mode === "inferred" ? "Inferred propagation direction" : "Undirected relationship"}` : null;
  }, [hover, stats]); // eslint-disable-line

  function selectNode(id: string, focus = true) {
    setSelected({ kind: "node", id });
    if (focus) engineRef.current?.focus(id);
  }
  // Phase 3B: the Copilot can open the map on a specific location node (same ids as the knowledge graph's map_node_id)
  const focusedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focusNodeId || focusedRef.current === focusNodeId || !stats?.nodes.some((n) => n.id === focusNodeId)) return;
    focusedRef.current = focusNodeId;
    selectNode(focusNodeId);
  }, [focusNodeId, stats?.nodes]); // eslint-disable-line
  function resetFilters() {
    setTier("all"); setPlatform("all"); setTouched(false); setPlaying(false); if (extent) setWin(extent);
  }
  async function mutate(fn: () => Promise<GeoData>) {
    setBusy(true); setActionErr(null);
    try { setGeo(await fn()); setTick((t) => t + 1); } catch (e: any) { setActionErr(e?.message ?? "Action failed."); } finally { setBusy(false); }
  }
  function viewTimeline(n: GeoStatsNode) {
    setPlaying(false); setTouched(true); setWin([ms(n.first_observed), Math.max(ms(n.last_observed), ms(n.first_observed) + 1)]);
    timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function addLocation() {
    const s = geo?.unlocated_sources[0];
    if (s) setEditor({ source: { id: s.source_id, label: s.label, platform: s.platform } });
    else onViewSources?.();
  }

  const s = stats?.summary;
  const hasAny = (stats?.available.total_observations ?? 0) > 0;
  const emptyReason = stats?.empty_reason ?? null;
  const fpHash = fingerprint.data?.average_hash;
  const ctrlBtn = "h-9 w-9 rounded-xl bg-[#0b1a24]/80 border border-white/10 text-[#cfe9df] hover:bg-[#12303a] hover:border-[#4fe3a1]/50 transition flex items-center justify-center backdrop-blur";
  const chip = (on: boolean) => `px-3 h-8 rounded-lg text-[11.5px] font-semibold inline-flex items-center gap-1.5 transition ${on ? "bg-[#4fe3a1] text-[#062018]" : "text-[#a9cfc2] hover:text-white"}`;
  const selectCls = "h-9 rounded-xl border border-border bg-white px-3 text-[12px] font-medium text-ink outline-none focus:ring-2 focus:ring-brand/15";

  const statCards = [
    { l: "Observations", v: s?.observations, sub: "located source records", icon: Layers, c: "#3E503C" },
    { l: "Unique sources", v: s?.unique_sources, sub: "distinct source identities", icon: Users, c: "#6585A8" },
    { l: "Platforms", v: s?.unique_platforms, sub: s?.platforms.slice(0, 3).join(", ") || "—", icon: Share2, c: "#6B5AA0" },
    { l: "Propagation events", v: s?.propagation_events, sub: "stored relationships", icon: Route, c: "#39d5ff" },
    { l: "Locations", v: s?.locations, sub: s ? `${s.verified_observations} verified obs` : "", icon: MapPin, c: TIER_COLOR.verified },
    { l: "Hotspots", v: s ? s.high_activity : undefined, sub: s ? `${s.high_activity} high · ${s.medium_activity} medium · ${s.low_activity} low` : "", icon: Flame, c: HEAT_COLOR.high },
  ];

  return (
    <div className="space-y-5">
      {/* ------------------------------ stats strip ------------------------------ */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {statCards.map((c) => (
          <div key={c.l} className="relative overflow-hidden bg-card border border-border rounded-2xl px-4 py-3.5 shadow-card">
            <span className="absolute -right-5 -top-5 h-16 w-16 rounded-full opacity-[0.12]" style={{ background: c.c }} />
            <div className="flex items-center gap-2 text-[10.5px] uppercase tracking-wider text-faint"><c.icon size={13} style={{ color: c.c }} /> {c.l}</div>
            <p className="text-[24px] font-semibold text-ink leading-tight tabular-nums mt-1">{c.v ?? "—"}</p>
            <p className="text-[10.5px] text-muted truncate">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* ------------------------------ filter bar ------------------------------ */}
      <div className="bg-card border border-border rounded-2xl shadow-card px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.14em] text-faint"><Filter size={13} /> Filters</div>
        <div className="flex items-center gap-1 p-1 rounded-xl bg-[#0b1a24]">
          {TIER_FILTERS.map((t) => {
            const n = t.key === "all" ? stats?.available.total_observations : stats?.available.tiers[t.key];
            return (
              <button key={t.key} onClick={() => setTier(t.key)} className={chip(tier === t.key)} title={`${t.label} locations`}>
                {t.key !== "all" && <span className="h-1.5 w-1.5 rounded-full" style={{ background: TIER_COLOR[t.key] }} />}
                {t.label}<span className={`text-[10px] tabular-nums ${tier === t.key ? "opacity-70" : "text-[#6f968a]"}`}>{n ?? 0}</span>
              </button>
            );
          })}
        </div>
        <label className="flex items-center gap-2 text-[11.5px] text-muted">Platform
          <select className={selectCls} value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="all">All platforms</option>
            {(stats?.available.platforms ?? []).map((p) => <option key={p.platform} value={p.platform}>{p.platform} ({p.observations})</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-[11.5px] text-muted">Heatmap metric
          <select className={selectCls} value={metric} onChange={(e) => setMetric(e.target.value as GeoMetric)}>
            {(Object.keys(METRIC_LABEL) as GeoMetric[]).map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
          </select>
        </label>
        {(tier !== "all" || platform !== "all" || touched) && (
          <button onClick={resetFilters} className="ml-auto text-[11.5px] font-semibold text-brand hover:underline">Reset filters</button>
        )}
        {statsBusy && <span className="text-[10.5px] text-faint animate-pulse">updating…</span>}
      </div>

      <div className="grid xl:grid-cols-[1fr_390px] gap-5">
        {/* ------------------------------ globe panel ------------------------------ */}
        <div className="rounded-2xl overflow-hidden border border-[#16333c] shadow-soft bg-[radial-gradient(ellipse_at_50%_35%,#0d2a35_0%,#07141b_55%,#050d12_100%)] self-start">
          <div className="relative h-[600px]">
            <div ref={mountRef} className="absolute inset-0" />

            {!webglOk && (
              <div className="absolute inset-0 flex items-center justify-center text-center p-8 text-[#cfe9df] text-[13px]">
                WebGL is unavailable in this browser, so the 3D globe cannot render. Location data is still listed in the side panel.
              </div>
            )}

            {/* mode switch + layer toggles */}
            <div className="absolute top-4 left-4 space-y-2">
              <div className="flex items-center gap-1 rounded-xl bg-[#0b1a24]/80 border border-white/10 p-1 backdrop-blur">
                {MODES.map(({ key, label, icon: Icon }) => (
                  <button key={key} onClick={() => setMode(key)} className={chip(mode === key)}><Icon size={13} /> {label}</button>
                ))}
              </div>
              {mode === "combined" && (
                <div className="flex items-center gap-1.5">
                  {([["heat", "Heatmap", HEAT_COLOR.high], ["nodes", "Location nodes", TIER_COLOR.verified], ["arcs", "Propagation arcs", EDGE_COLOR.confirmed]] as const).map(([k, label, col]) => {
                    const on = combined[k];
                    return (
                      <button key={k} onClick={() => setCombined((c) => ({ ...c, [k]: !c[k] }))}
                        className={`h-7 px-2.5 rounded-lg text-[10.5px] font-semibold inline-flex items-center gap-1.5 border backdrop-blur transition ${on ? "bg-[#0b1a24]/85 text-white border-white/20" : "bg-[#0b1a24]/50 text-[#6f968a] border-white/5"}`}>
                        {on ? <Eye size={11} style={{ color: col }} /> : <EyeOff size={11} />} {label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* controls */}
            <div className="absolute top-4 right-4 flex flex-col gap-1.5">
              <button className={ctrlBtn} title="Zoom in" onClick={() => engineRef.current?.zoom(0.8)}><Plus size={15} /></button>
              <button className={ctrlBtn} title="Zoom out" onClick={() => engineRef.current?.zoom(1.25)}><Minus size={15} /></button>
              <button className={ctrlBtn} title="Rotate left" onClick={() => engineRef.current?.rotate(-0.35, 0)}><RotateCcw size={15} /></button>
              <button className={ctrlBtn} title="Rotate right" onClick={() => engineRef.current?.rotate(0.35, 0)}><RotateCw size={15} /></button>
              <button className={`${ctrlBtn} ${autoRot ? "!border-[#4fe3a1]/70 !text-[#4fe3a1]" : ""}`} title="Auto-rotate"
                onClick={() => { const v = !autoRot; setAutoRot(v); engineRef.current?.setAutoRotate(v); }}><Orbit size={15} /></button>
              <button className={ctrlBtn} title="Reset view" onClick={() => { engineRef.current?.reset(); setSelected(null); }}><Maximize2 size={15} /></button>
            </div>

            {/* observed-activity badge (never claims proven spread) */}
            {touched && extent && (
              <div className="absolute top-[78px] left-1/2 -translate-x-1/2 px-3.5 py-1.5 rounded-full bg-[#0b1a24]/90 border border-[#4fe3a1]/30 text-[11px] text-[#dff5ec] backdrop-blur pointer-events-none flex items-center gap-2">
                <Radar size={12} className={`text-[#4fe3a1] ${playing ? "animate-pulse" : ""}`} />
                Observed activity up to <b>{formatObserved(new Date(hi).toISOString())}</b>
              </div>
            )}
            {hoverInfo && (
              <div className="absolute top-[118px] left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full bg-[#0b1a24]/90 border border-white/15 text-[11.5px] text-[#dff5ec] backdrop-blur pointer-events-none">{hoverInfo}</div>
            )}

            {stats && emptyReason && (
              <EmptyOverlay reason={emptyReason} canAdd={(geo?.unlocated_sources.length ?? 0) > 0} onAdd={addLocation} onReset={resetFilters} />
            )}
            {loadErr && <div className="absolute bottom-28 left-4 right-4 text-[12px] text-red-200 bg-red-900/50 border border-red-400/30 rounded-xl px-3 py-2">{loadErr}</div>}

            {/* legend */}
            <div className="absolute bottom-4 left-4 flex flex-col gap-2 items-start">
              {!legendOpen ? (
                <button onClick={() => setLegendOpen(true)} className="h-8 px-3 rounded-xl bg-[#0b1a24]/85 border border-white/10 text-[11px] text-[#cfe9df] inline-flex items-center gap-1.5 backdrop-blur"><Layers size={13} /> Legend</button>
              ) : (<>
                {layers.heat && stats && <HeatLegend metric={metric} config={stats.config} max={stats.heat.max[metric]} />}
                {(layers.nodes || layers.arcs) && (
                  <div className="w-[248px] rounded-xl bg-[#0b1a24]/88 border border-white/10 p-3.5 text-[10.5px] text-[#b6d6ca] backdrop-blur space-y-2.5">
                    <div className="flex justify-between items-center"><b className="text-white text-[11.5px]">Legend</b><button onClick={() => setLegendOpen(false)} className="text-[#7fa89a] hover:text-white">hide</button></div>
                    {layers.nodes && (
                      <div>
                        <p className="uppercase tracking-wider text-[9px] text-[#6f968a] mb-1">Nodes · location type</p>
                        {(["verified", "investigator", "inferred"] as const).map((t) => (
                          <p key={t} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: TIER_COLOR[t], boxShadow: `0 0 8px ${TIER_COLOR[t]}` }} />{TIER_LABEL[t]}{t === "verified" ? " (EXIF / metadata)" : ""}</p>
                        ))}
                        <p className="text-[#8db3a5] mt-1">Size = observations</p>
                      </div>
                    )}
                    {layers.arcs && (
                      <div>
                        <p className="uppercase tracking-wider text-[9px] text-[#6f968a] mb-1">Connections</p>
                        <p className="flex items-center gap-2"><span className="w-7 h-[3px] rounded" style={{ background: EDGE_COLOR.confirmed }} /><ArrowRight size={11} style={{ color: EDGE_COLOR.confirmed }} />Confirmed direction</p>
                        <p className="flex items-center gap-2"><span className="w-7 border-t-2 border-dashed" style={{ borderColor: EDGE_COLOR.inferred }} /><ArrowRight size={11} style={{ color: EDGE_COLOR.inferred }} />Inferred (timestamps)</p>
                        <p className="flex items-center gap-2"><span className="w-7 border-t-2 border-dashed" style={{ borderColor: EDGE_COLOR.undirected }} />Undirected relation</p>
                      </div>
                    )}
                  </div>
                )}
                {layers.heat && !layers.nodes && !layers.arcs && <button onClick={() => setLegendOpen(false)} className="text-[10.5px] text-[#7fa89a] hover:text-white">hide legend</button>}
              </>)}
            </div>
          </div>

          {/* ------------------------------ evidence timeline ------------------------------ */}
          <div ref={timelineRef} className="border-t border-white/10 bg-[#07131a] px-5 py-4">
            <div className="flex items-center gap-3 mb-2.5 flex-wrap">
              <button disabled={!extent || !(stats?.time_index.length)} onClick={togglePlay}
                className="h-9 px-4 rounded-full bg-[#4fe3a1] text-[#062018] text-[11.5px] font-bold tracking-wide inline-flex items-center gap-2 disabled:opacity-40 hover:brightness-110 transition">
                {playing ? <><Pause size={13} /> PAUSE</> : <><Play size={13} className="ml-0.5" /> PLAY OBSERVED ACTIVITY</>}
              </button>
              <div className="leading-tight">
                <div className="flex items-center gap-2 text-[11.5px] text-[#cfe9df] font-semibold"><Clock size={13} className="text-[#4fe3a1]" /> Observed Activity Timeline</div>
                <div className="text-[10px] text-[#6f968a]">Evidence timeline · when observations were recorded</div>
              </div>
              <div className="ml-auto text-[11px] text-[#cfe9df] tabular-nums">
                {extent ? `${formatObserved(new Date(lo).toISOString())}  →  ${formatObserved(new Date(hi).toISOString())}` : "No timestamps"}
              </div>
              {touched && extent && (
                <button onClick={() => { setTouched(false); setPlaying(false); setWin(extent); }} className="text-[11px] text-[#4fe3a1] hover:underline">Reset</button>
              )}
            </div>
            <div className="relative h-6">
              <div className="absolute top-1/2 -translate-y-1/2 inset-x-0 h-1.5 rounded-full bg-white/10" />
              {extent && (
                <div className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-gradient-to-r from-[#39d5ff] to-[#4fe3a1]"
                  style={{ left: `${((lo - extent[0]) / (extent[1] - extent[0])) * 100}%`, width: `${((hi - lo) / (extent[1] - extent[0])) * 100}%` }} />
              )}
              {extent && stats?.timeline_events.map((o, i) => {
                const t = ms(o.t), inWin = t >= lo && t <= hi, isSel = selNode?.id === o.node_id;
                return (
                  <button key={i} onClick={() => selectNode(o.node_id)} title={`${o.label} · ${o.platform} · ${formatObserved(o.t)}`}
                    className="absolute top-[2px] h-4 w-[6px] -translate-x-1/2 flex items-center justify-center z-[1]" style={{ left: `${((t - extent[0]) / (extent[1] - extent[0])) * 100}%` }}>
                    <span className="block w-[2px] rounded transition-all" style={{ height: isSel ? 16 : 12, background: isSel ? "#f6b94d" : inWin ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.18)", boxShadow: isSel ? "0 0 8px #f6b94d" : "none" }} />
                  </button>
                );
              })}
              {extent && (<>
                <input type="range" className="geo-range" min={extent[0]} max={extent[1]} step={Math.max(1, Math.floor((extent[1] - extent[0]) / 1000))} value={lo}
                  onChange={(e) => { setTouched(true); setPlaying(false); setWin([Math.min(Number(e.target.value), hi), hi]); }} aria-label="Range start" />
                <input type="range" className="geo-range" min={extent[0]} max={extent[1]} step={Math.max(1, Math.floor((extent[1] - extent[0]) / 1000))} value={hi}
                  onChange={(e) => { setTouched(true); setPlaying(false); setWin([lo, Math.max(Number(e.target.value), lo)]); }} aria-label="Range end" />
              </>)}
            </div>
            <p className="text-[10.5px] text-[#6f968a] mt-2 flex items-center gap-1.5 flex-wrap">
              <Info size={11} /> {s ? `${s.locations} location${s.locations === 1 ? "" : "s"} · ${s.observations} observation${s.observations === 1 ? "" : "s"} · ${stats?.edges.length ?? 0} connection${stats?.edges.length === 1 ? "" : "s"} in window.` : "Loading…"}
              Playback replays when observations were recorded; it does not by itself prove how content spread. Basemap: Natural Earth.
            </p>
          </div>
        </div>

        {/* ------------------------------ side column ------------------------------ */}
        <div className="space-y-5 min-w-0">
          {selNode && <LocationCard node={selNode} onEvidence={() => onNavigate?.("evidence")} />}

          <Panel className="p-5 sm:p-6">
            {selNode && stats && (
              <LocationDetailPanel node={selNode} config={stats.config} busy={busy} onClose={() => setSelected(null)}
                onEdit={(o: GeoObservation) => setEditor({ source: { id: o.source_id, label: o.label, platform: o.platform }, initial: { latitude: selNode.latitude, longitude: selNode.longitude, place_name: selNode.has_name ? selNode.name : "", confidence: o.confidence, basis: o.basis } })}
                onRemove={(o: GeoObservation) => incidentId && mutate(() => api.deleteSourceLocation(incidentId, o.source_id))}
                onLocate={() => engineRef.current?.focus(selNode.id)}
                onViewSources={() => onViewSources?.(selNode.observations[0]?.source_id)} onViewEvidence={() => onNavigate?.("evidence")} onViewTimeline={() => viewTimeline(selNode)} />
            )}

            {selEdge && (
              <EdgePanel edge={selEdge} from={nodeName(selEdge.source)} to={nodeName(selEdge.target)} fpHash={fpHash} busy={busy}
                onClose={() => setSelected(null)}
                onConfirm={(rid, note) => incidentId && mutate(() => api.confirmDirection(incidentId, rid, note))}
                onRevoke={(rid) => incidentId && mutate(() => api.revokeDirection(incidentId, rid))}
                onViewSource={(label) => onViewSources?.(nodes.flatMap((n) => n.observations).find((o) => o.label === label)?.source_id)} />
            )}

            {!selNode && !selEdge && (
              <div>
                <div className="flex items-center gap-1 p-1 rounded-xl bg-soft/70 mb-4">
                  {([["hotspots", "Hotspots"], ["compare", "Compare"]] as const).map(([k, l]) => (
                    <button key={k} onClick={() => setSideTab(k)} className={`flex-1 h-8 rounded-lg text-[12px] font-semibold transition ${sideTab === k ? "bg-white text-ink shadow-card" : "text-muted hover:text-ink"}`}>{l}</button>
                  ))}
                </div>
                {sideTab === "hotspots" && stats && <HotspotsPanel hotspots={stats.hotspots} config={stats.config} selectedId={null} onSelect={(id) => selectNode(id)} />}
                {sideTab === "compare" && <ComparePanel nodes={nodes} />}
                {!stats && <p className="text-[12.5px] text-muted flex items-center gap-2"><Crosshair size={14} /> Loading geographic intelligence…</p>}
                <p className="text-[11px] text-faint mt-4 leading-relaxed">Click a heat area, location node or connection arc on the globe to open its evidence-backed detail panel.</p>
              </div>
            )}
            {actionErr && <p className="mt-3 text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{actionErr}</p>}
          </Panel>

          <EarliestCard e={stats?.earliest_observed ?? null} onSelect={(id) => selectNode(id)} />

          {geo && geo.unlocated_sources.length > 0 && (
            <Panel className="p-5 sm:p-6">
              <h3 className="text-[14px] font-semibold text-ink">Sources without a location</h3>
              <p className="text-[11.5px] text-muted mt-1 leading-relaxed">No coordinates are inferred. Add a location only if you have a basis for it — it will be tagged <b>Investigator supplied</b>.</p>
              <div className="mt-3 space-y-2">
                {geo.unlocated_sources.map((u) => (
                  <div key={u.source_id} className="flex items-center gap-3 border border-border rounded-xl px-3 py-2">
                    <div className="h-8 w-8 rounded-lg bg-soft text-brand text-[10px] font-bold flex items-center justify-center">{u.label.replace("SRC-", "")}</div>
                    <div className="min-w-0 flex-1"><p className="text-[12.5px] font-medium text-ink truncate">{u.platform}</p><p className="text-[10.5px] text-muted truncate">{u.account ?? "no account"} · {formatObserved(u.observed_at)}</p></div>
                    <button onClick={() => setEditor({ source: { id: u.source_id, label: u.label, platform: u.platform } })}
                      className="text-[11.5px] font-semibold text-brand hover:underline inline-flex items-center gap-1 shrink-0"><MapPin size={12} /> Add location</button>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <div className="rounded-2xl bg-blue/70 p-4 text-[12px] text-[#3B5A7D] border border-blue shadow-xs leading-relaxed">
            <Info size={15} className="inline mr-2 -mt-0.5" />
            <b>Evidence integrity:</b> <b>Observations</b> are located source records; <b>unique sources</b> are distinct source identities, so the two are never the same number. Propagation events are counted only from stored relationships. Verified = metadata in preserved evidence · Investigator supplied = entered by a person · Inferred is never counted as verified.
            {s && s.relationships_without_locations > 0 && ` ${s.relationships_without_locations} recorded link(s) are not counted because an endpoint has no location.`}
          </div>
        </div>
      </div>

      {editor && incidentId && (
        <LocationEditor incidentId={incidentId} source={editor.source} initial={editor.initial} onClose={() => setEditor(null)} onSaved={(g) => { setGeo(g); setTick((t) => t + 1); }} />
      )}
    </div>
  );
}
