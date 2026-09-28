import { motion } from "framer-motion";
import {
  FolderOpen,
  Plus,
  ShieldCheck,
  Activity,
  Search,
  ArrowRight,
  Database,
  Lock,
  PieChart,
  BarChart3,
  Server,
  Layers,
} from "lucide-react";
import { Panel, PanelHeader, StatCard, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { statusLabel } from "../lib/pipeline";
import { ScreenKey } from "../components/Sidebar";

const anim = { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3 } };

export default function Dashboard({ onNavigate }: { onNavigate: (k: ScreenKey) => void }) {
  const incidents = useAsync(() => api.listIncidents(), []);
  const all = incidents.data ?? [];

  const openCount = all.filter((i) => i.status !== "closed").length;
  const reportedCount = all.filter((i) => i.status === "report_generated" || i.status === "closed").length;
  const inAnalysis = all.filter((i) => ["analyzing", "fingerprinted", "evidence_building"].includes(i.status)).length;

  // Account-level counts, read from the server. Per-case detection scores and
  // evidence totals live on each investigation rather than being aggregated
  // here — the API exposes them per incident, not as a global rollup.
  const PALETTE = ["#3E503C", "#72846F", "#91A19A", "#9B8BC2", "#C79B42", "#D4DAD5"];
  const statusBreakdown = (() => {
    if (all.length === 0) return [] as { name: string; pct: number; color: string }[];
    const counts = new Map<string, number>();
    all.forEach((i) => counts.set(i.status, (counts.get(i.status) ?? 0) + 1));
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([status, n], idx) => ({
        name: statusLabel(status as any),
        pct: Math.round((n / all.length) * 100),
        color: PALETTE[idx % PALETTE.length],
      }));
  })();

  const stats = [
    ["Total Investigations", incidents.loading ? "…" : String(all.length), "Stored on the server", FolderOpen],
    ["Open Cases", incidents.loading ? "…" : String(openCount), "Not yet archived", Activity],
    ["In Analysis", incidents.loading ? "…" : String(inAnalysis), "Detection or evidence stage", ShieldCheck],
    ["Reports Generated", incidents.loading ? "…" : String(reportedCount), "Ready to export", Database],
  ];

  return (
    <motion.div {...anim} className="space-y-6 max-w-[1400px] mx-auto">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-1">
        <div>
          <p className="text-[11px] uppercase tracking-[.18em] text-brand font-semibold mb-1">SYSTEM OVERVIEW</p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-[40px] tracking-[-.03em] font-semibold text-ink">
            Investigate with clarity.
          </h1>
          <p className="text-[13.5px] text-muted mt-2 max-w-2xl leading-relaxed">
            High-level platform metrics, global abuse landscape, and active risk monitoring across all cases.
          </p>
        </div>
        <div className="flex items-center gap-2">
        </div>
      </div>

      {/* Quick Actions Cards */}
      <div className="grid md:grid-cols-2 gap-5">
        <button
          onClick={() => onNavigate("new")}
          className="bg-brand text-white rounded-2xl p-6 text-left flex items-center justify-between hover:bg-brandDark transition shadow-sm group"
        >
          <div>
            <div className="h-10 w-10 rounded-xl bg-white/10 flex items-center justify-center text-white shrink-0 mb-3">
              <Plus size={22} />
            </div>
            <b className="block text-[17px] font-semibold">Start a New Investigation</b>
            <span className="text-[12.5px] text-white/80 mt-1 block">Upload media or paste a source link to begin detection.</span>
          </div>
          <ArrowRight className="group-hover:translate-x-1.5 transition-transform shrink-0 ml-4" size={20} />
        </button>

        <button
          onClick={() => onNavigate("investigations")}
          className="bg-card border border-border rounded-2xl p-6 text-left flex items-center justify-between hover:bg-soft transition shadow-card group"
        >
          <div>
            <div className="h-10 w-10 rounded-xl bg-soft flex items-center justify-center text-brand shrink-0 mb-3">
              <Search size={20} />
            </div>
            <b className="block text-[17px] font-semibold text-ink">Browse All Investigations</b>
            <span className="text-[12.5px] text-muted mt-1 block">{incidents.loading ? "Loading your cases…" : `View, filter, and manage ${all.length} investigation case${all.length === 1 ? "" : "s"}.`}</span>
          </div>
          <ArrowRight className="text-brand group-hover:translate-x-1.5 transition-transform shrink-0 ml-4" size={20} />
        </button>
      </div>

      {/* 4 Stat Cards */}
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.map(([l, v, s, I]: any) => (
          <StatCard key={l} label={l} value={v} sub={s} icon={I} />
        ))}
      </div>

      {/* Global Analytics Section */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Your Investigations */}
        <Panel className="p-6 sm:p-7 flex flex-col justify-between space-y-6">
          <PanelHeader
            title="Your Investigations"
            subtitle="Distribution of your cases by pipeline stage"
            right={
              <div className="h-8 w-8 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0">
                <PieChart size={18} />
              </div>
            }
          />

          <div className="flex flex-col sm:flex-row items-center gap-8 pt-2">
            <div
              className="h-40 w-40 rounded-full shrink-0 shadow-xs relative"
              style={{
                background:
                  "conic-gradient(#3E503C 0 35%, #72846F 35% 60%, #91A19A 60% 75%, #9B8BC2 75% 87%, #C79B42 87% 100%)",
              }}
            >
              <div className="h-28 w-28 bg-card rounded-full relative top-6 left-6 flex flex-col items-center justify-center shadow-xs">
                <b className="text-3xl font-semibold text-ink">{incidents.loading ? "…" : all.length}</b>
                <span className="text-[10.5px] text-muted font-medium">Investigations</span>
              </div>
            </div>

            <div className="space-y-2.5 text-[12.5px] w-full">
              {statusBreakdown.length === 0 && (
                <p className="text-[12.5px] text-muted">No investigations yet.</p>
              )}
              {statusBreakdown.map(({ name, pct, color }) => (
                <div key={name} className="flex justify-between items-center py-1.5 border-b border-border/40 last:border-0">
                  <span className="flex items-center gap-2 text-ink font-medium">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                    {name}
                  </span>
                  <span className="font-semibold text-ink">{pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        {/* Global Case Risk & Monthly Trends */}
        <Panel className="p-6 sm:p-7 flex flex-col justify-between space-y-6">
          <PanelHeader
            title="Case Status Breakdown"
            subtitle="Where your investigations currently sit in the pipeline"
            right={
              <div className="h-8 w-8 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0">
                <BarChart3 size={18} />
              </div>
            }
          />

          <div className="space-y-4 pt-2">
            {statusBreakdown.length === 0 && (
              <p className="text-[12.5px] text-muted">
                No investigations yet — case status distribution will appear here once you create one.
              </p>
            )}
            {statusBreakdown.map((x) => (
              <div key={x.name}>
                <div className="flex justify-between text-[12.5px] mb-1.5">
                  <span className="font-medium text-ink flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: x.color }} /> {x.name}
                  </span>
                  <span className="font-semibold text-ink">{x.pct}%</span>
                </div>
                <div className="h-2.5 bg-[#EEF1ED] rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${x.pct}%`, backgroundColor: x.color }} />
                </div>
              </div>
            ))}
          </div>

          <div className="p-4 rounded-xl bg-soft/50 border border-border/60 flex items-center justify-between text-[12px]">
            <span className="text-muted">Detection Pipeline Engine</span>
            <StatusBadge tone="green">Connected</StatusBadge>
          </div>
        </Panel>
      </div>

      {/* System Health & Security Cards */}
      <div className="grid md:grid-cols-3 gap-5">
        <Panel className="p-5 sm:p-6 space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0">
              <Server size={18} />
            </div>
            <div>
              <p className="text-[13.5px] font-semibold text-ink">Detector Engine</p>
              <p className="text-[11.5px] text-muted">Pretrained manipulation-detection model</p>
            </div>
          </div>
          <div className="pt-2 border-t border-border/50 flex justify-between items-center text-[12px]">
            <span className="text-muted">Output format</span>
            <span className="font-semibold text-brand">Likelihood score, never binary</span>
          </div>
        </Panel>

        <Panel className="p-5 sm:p-6 space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0">
              <Layers size={18} />
            </div>
            <div>
              <p className="text-[13.5px] font-semibold text-ink">Evidence Vault Storage</p>
              <p className="text-[11.5px] text-muted">Encrypted at rest (AES via Fernet)</p>
            </div>
          </div>
          <div className="pt-2 border-t border-border/50 flex justify-between items-center text-[12px]">
            <span className="text-muted">Cases protected</span>
            <span className="font-semibold text-brand">{incidents.loading ? "…" : all.length}</span>
          </div>
        </Panel>

        <Panel className="p-5 sm:p-6 space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0">
              <Lock size={18} />
            </div>
            <div>
              <p className="text-[13.5px] font-semibold text-ink">Takedown Rule Compliance</p>
              <p className="text-[11.5px] text-muted">2026 IT Intermediary Rules</p>
            </div>
          </div>
          <div className="pt-2 border-t border-border/50 flex justify-between items-center text-[12px]">
            <span className="text-muted">Action Window</span>
            <span className="font-semibold text-brand">3-Hour Takedown Ready</span>
          </div>
        </Panel>
      </div>
    </motion.div>
  );
}
