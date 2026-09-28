import { motion } from "framer-motion";
import { ArrowRight, FileText, Network, ShieldCheck, Plus, Activity } from "lucide-react";
import { useCase } from "../context/CaseContext";
import { toDisplaySources } from "../lib/adapters";
import { stagesWithProgress } from "../lib/pipeline";
import { Panel, PanelHeader, StageTracker, StatusBadge } from "../components/ui";
import MediaPreview from "../components/MediaPreview";
import { ScreenKey } from "../components/Sidebar";

const anim = { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.35 } };

export default function Overview({ onNavigate }: { onNavigate: (k: ScreenKey) => void }) {
  const { incidentId, incident, media, detection, sources: sourcesSlice, evidence } = useCase();
  const c = incident.data;
  const d = detection.data;
  const sources = toDisplaySources(sourcesSlice.data);
  const evidenceItems = evidence.data;
  const likelihood = d?.manipulation_likelihood ?? null;
  const externalSources = sources.filter((source) => source.platform !== "User upload");
  const highestSimilarity = externalSources.reduce<number | null>(
    (max, s) => (s.similarity != null && (max == null || s.similarity > max) ? s.similarity : max),
    null
  );
  const topSource = externalSources.find((s) => s.similarity === highestSimilarity);
  const platformCount = new Set(externalSources.map((s) => s.platform)).size;

  const platformShares = (() => {
    const counts = new Map<string, number>();
    externalSources.forEach((s) => counts.set(s.platform, (counts.get(s.platform) ?? 0) + 1));
    return [...counts.entries()]
      .map(([platform, n]) => ({ platform, pct: Math.round((n / externalSources.length) * 100) }))
      .sort((a, b) => b.pct - a.pct);
  })();

  const platformGradient = (() => {
    if (platformShares.length === 0) return "conic-gradient(#D4DAD5 0 100%)";
    const palette = ["#3E503C", "#72846F", "#91A19A", "#9B8BC2", "#C79B42", "#D4DAD5"];
    let acc = 0;
    const stops = platformShares.map((x, i) => {
      const start = acc;
      acc += x.pct;
      return `${palette[i % palette.length]} ${start}% ${acc}%`;
    });
    return `conic-gradient(${stops.join(",")})`;
  })();

  return (
    <motion.div {...anim} className="space-y-6">
      {/* Primary Row: Case Summary, Media Preview, & Manipulation Assessment */}
      <div className="grid xl:grid-cols-3 gap-5">
        {/* Case Summary Panel */}
        <Panel className="xl:col-span-1 p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <PanelHeader
              title="Case Summary"
              right={<button className="text-[12px] border border-border rounded-lg px-3 py-1.5 hover:bg-soft transition">Edit</button>}
            />
            <p className="text-[13px] text-muted leading-relaxed">
              {c?.description?.trim() ||
                "No case description was provided. Add one when creating an investigation to give collaborators context on what is being investigated and why."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-6 pt-5 border-t border-border/60 text-[12px]">
            <div>
              <p className="text-muted font-medium">Media Type</p>
              <p className="font-semibold text-ink mt-1">
                {media.data ? (media.data.kind === "video" ? "Video" : "Image") : "No media yet"}
              </p>
            </div>
            <div>
              <p className="text-muted font-medium">Platforms</p>
              <p className="font-semibold text-ink mt-1">{platformCount} observed</p>
            </div>
            <div>
              <p className="text-muted font-medium">Uploaded</p>
              <p className="font-semibold text-ink mt-1">
                {media.data ? new Date(media.data.uploaded_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—"}
              </p>
            </div>
            <div>
              <p className="text-muted font-medium">Evidence</p>
              <p className="font-semibold text-ink mt-1">{evidenceItems.length} items</p>
            </div>
          </div>
        </Panel>

        {/* Media Preview Panel */}
        <Panel className="xl:col-span-1 p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <PanelHeader title="Media Preview" />
            <MediaPreview incidentId={incidentId} media={media.data} className="h-[220px] rounded-xl shadow-inner" />
          </div>
          <div className="flex items-center justify-between mt-4 text-[12px] pt-3 border-t border-border/60">
            <span className="text-muted">Original media preserved</span>
            <span className="text-brand font-semibold flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-brand" /> Available
            </span>
          </div>
        </Panel>

        {/* Manipulation Assessment Panel */}
        <Panel className="xl:col-span-1 p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <PanelHeader title="Manipulation Assessment" />
            <div className="flex items-center gap-5">
              <div
                className="h-32 w-32 rounded-full flex items-center justify-center shrink-0 shadow-sm"
                style={{ background: `conic-gradient(#B96255 0 ${likelihood ?? 0}%, #E9EDE8 ${likelihood ?? 0}% 100%)` }}
              >
                <div className="h-24 w-24 rounded-full bg-card flex flex-col items-center justify-center shadow-xs">
                  <b className="text-3xl text-ink font-semibold">{likelihood != null ? `${Math.round(likelihood)}%` : "—"}</b>
                  <span className="text-[10px] text-muted font-medium">Likely manipulated</span>
                </div>
              </div>
              <div className="flex-1 space-y-2.5 text-[12px]">
                <div className="flex justify-between items-center">
                  <span className="text-muted">High likelihood</span>
                  <b className="text-ink">{likelihood != null ? `${Math.round(likelihood)}%` : "—"}</b>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-muted">Remaining / not indicated</span>
                  <span className="text-muted font-medium">
                    {likelihood != null ? `${Math.round(100 - likelihood)}%` : "—"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-muted">Model</span>
                  <span className="text-muted font-medium text-right break-words max-w-[9rem]">{d?.model_name ?? "—"}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="border-t border-border/60 mt-5 pt-4">
            <p className="font-semibold text-[12.5px] text-ink">Highest Recorded Similarity</p>
            <div className="flex items-end gap-2 mt-1">
              <b className="text-2xl font-semibold text-ink">{highestSimilarity != null ? `${highestSimilarity}%` : "No score recorded"}</b>
              {topSource && <span className="text-[12px] text-muted mb-1 font-medium">{topSource.platform}</span>}
            </div>
            <p className="text-[11px] text-muted mt-1">Scores on manually added sources are investigator-entered, not an automatic image comparison.</p>
          </div>
        </Panel>
      </div>

      {/* Case Analytics Row: Platform Distribution & Score Trend Charts */}
      <div className="grid lg:grid-cols-2 gap-5">
        <Panel className="p-5 sm:p-6">
            <PanelHeader title="External Source Distribution" subtitle="Investigator-recorded pages; the uploaded file is excluded." />
          <div className="flex flex-col sm:flex-row items-center gap-8 mt-4">
            <div
              className="h-36 w-36 rounded-full shrink-0 shadow-xs relative"
              style={{ background: platformGradient }}
            >
              <div className="h-24 w-24 bg-card rounded-full relative top-6 left-6 flex flex-col items-center justify-center shadow-xs">
                <b className="text-2xl font-semibold text-ink">{externalSources.length}</b>
                  <span className="text-[10px] text-muted font-medium">External sources</span>
              </div>
            </div>
            <div className="space-y-2 text-[12px] w-full">
              {platformShares.length === 0 && <p className="text-muted">No sources recorded yet.</p>}
              {platformShares.map((x) => (
                <div key={x.platform} className="flex justify-between items-center py-1 border-b border-border/40 last:border-0">
                  <span className="text-muted font-medium">● {x.platform}</span>
                  <span className="font-semibold text-ink">{x.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel className="p-5 sm:p-6">
          <PanelHeader title="Manipulation Score Trends" right={<span className="text-[11px] border border-border rounded-lg px-2.5 py-1 text-muted">Last 7 days</span>} />
          <svg viewBox="0 0 560 180" className="w-full h-44 mt-2">
            <path d="M25 145 L110 115 L195 125 L280 90 L365 105 L450 65 L535 30" fill="none" stroke="#3E503C" strokeWidth="3" />
            <path d="M25 145 L110 115 L195 125 L280 90 L365 105 L450 65 L535 30 L535 170 L25 170 Z" fill="#E8EEE6" opacity="0.6" />
            {[25, 110, 195, 280, 365, 450, 535].map((x, i) => (
              <circle key={x} cx={x} cy={[145, 115, 125, 90, 105, 65, 30][i]} r="5" fill="#3E503C" />
            ))}
          </svg>
        </Panel>
      </div>

      {/* Progress & Key Finding Row */}
      <div className="grid xl:grid-cols-3 gap-5">
        <Panel className="xl:col-span-2 p-5 sm:p-6">
          <PanelHeader title="Case Progress" subtitle="Follow the investigation from media upload to report" />
          <div className="mt-4 overflow-x-auto pb-2">
            <StageTracker stages={stagesWithProgress(c?.status)} />
          </div>
        </Panel>

        <Panel className="p-5 sm:p-6 flex flex-col justify-between">
          <PanelHeader title="Key Finding" />
          <div className="rounded-xl bg-soft/70 border border-brand/20 p-4">
            <div className="flex gap-3">
              <ShieldCheck className="text-brand shrink-0 mt-0.5" size={20} />
              <p className="text-[13px] text-ink leading-relaxed">
                {likelihood == null
                  ? "Run detection to establish whether this media shows signs of manipulation."
                  : externalSources.length === 0
                  ? `Detection reports a ${Math.round(likelihood)}% manipulation likelihood. No external sources have been recorded yet.`
                  : `Detection reports a ${Math.round(likelihood)}% manipulation likelihood. ${externalSources.length} external source${externalSources.length === 1 ? " has" : "s have"} been recorded; similarity scores are investigator-entered estimates.`}
              </p>
            </div>
          </div>
          <p className="text-[11.5px] text-muted mt-3">
            Based on {evidenceItems.length} preserved evidence item{evidenceItems.length === 1 ? "" : "s"}.
          </p>
        </Panel>
      </div>

      {/* Quick Actions & Recent Activity Row */}
      <div className="grid lg:grid-cols-3 gap-5">
        <Panel className="lg:col-span-1 p-5 sm:p-6">
          <PanelHeader title="Quick Actions" />
          <div className="space-y-2.5 mt-4">
            {[
              ["Continue Detection Analysis", "detection", ShieldCheck],
              ["Add Evidence Item", "evidence", Plus],
              ["View Lineage Graph", "lineage", Network],
              ["Generate Incident Report", "report", FileText],
            ].map(([t, k, I]: any) => (
              <button
                key={k}
                onClick={() => onNavigate(k)}
                className="w-full flex items-center justify-between rounded-xl border border-border px-4 py-3 text-[12.5px] font-medium text-ink hover:bg-soft hover:border-brand/40 transition group"
              >
                <span className="flex items-center gap-3">
                  <I size={16} className="text-brand shrink-0" />
                  {t}
                </span>
                <ArrowRight size={14} className="text-muted group-hover:translate-x-0.5 transition-transform" />
              </button>
            ))}
          </div>
        </Panel>

        <Panel className="lg:col-span-2 p-5 sm:p-6">
          <PanelHeader title="Recent Activity" right={<button className="text-[12px] text-brand font-medium hover:underline">View all →</button>} />
          <div className="grid sm:grid-cols-2 gap-4 mt-4">
            {["Detection completed", "Fingerprinting completed", "New evidence source added", "Report draft prepared"].map((x, i) => (
              <div key={x} className="flex gap-3.5 items-start p-3 rounded-xl hover:bg-soft/40 transition border border-transparent hover:border-border/50">
                <div className="h-8 w-8 rounded-full bg-soft flex items-center justify-center text-brand shrink-0">
                  <Activity size={15} />
                </div>
                <div>
                  <p className="text-[13px] font-semibold text-ink">{x}</p>
                  <p className="text-[11.5px] text-muted mt-0.5">{i * 7 + 3} minutes ago</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </motion.div>
  );
}
