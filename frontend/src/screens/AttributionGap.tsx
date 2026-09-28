import { useState } from "react";
import { CheckCircle2, HelpCircle, FileSearch, ArrowRight, Loader2 } from "lucide-react";
import { Panel, Notice, PrimaryButton } from "../components/ui";
import { ScreenKey } from "../components/Sidebar";
import { useCase } from "../context/CaseContext";
import { AsyncBlock, EmptyState, ErrorState } from "../components/states";

export default function AttributionGap({ onNavigate }: { onNavigate: (k: ScreenKey) => void }) {
  const { attributionGap, generateGap, generateReport, sources } = useCase();
  const [generating, setGenerating] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const entries = attributionGap.data;
  const known = entries.filter((e) => e.category === "known").map((e) => e.statement);
  const unresolved = entries.filter((e) => e.category === "unresolved").map((e) => e.statement);
  const evidenceNeeded = entries.filter((e) => e.category === "evidence_needed").map((e) => e.statement);

  async function runGenerate() {
    setGenerating(true); setActionError(null);
    try { await generateGap(); }
    catch (e: any) { setActionError(e?.message ?? "Could not generate the attribution gap."); }
    finally { setGenerating(false); }
  }

  async function runReport() {
    setReportBusy(true); setActionError(null);
    try { await generateReport(); onNavigate("report"); }
    catch (e: any) { setActionError(e?.message ?? "Could not generate the report."); }
    finally { setReportBusy(false); }
  }

  const col = [
    ["WHAT WE KNOW", CheckCircle2, "green", known],
    ["WHAT WE DON'T KNOW", HelpCircle, "amber", unresolved],
    ["EVIDENCE NEEDED", FileSearch, "blue", evidenceNeeded],
  ];

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border rounded-2xl p-5 sm:p-6 shadow-card">
        <div>
          <h2 className="text-xl font-semibold tracking-[-.02em] text-ink">Attribution Gap Analysis</h2>
          <p className="text-[13px] text-muted mt-1 leading-relaxed">
            Here's what the available evidence can and cannot tell us, and what is needed next.
          </p>
        </div>
      </div>

      {actionError && <ErrorState message={actionError} />}

      <AsyncBlock
        loading={attributionGap.loading}
        error={attributionGap.error}
        loadingLabel="Loading attribution analysis…"
        isEmpty={entries.length === 0}
        empty={
          <EmptyState
            title="No attribution analysis yet"
            detail={
              sources.data.length === 0
                ? "Add related sources first — the attribution gap is derived from the evidence graph."
                : "Run the analysis to classify what the evidence can and cannot establish."
            }
            action={
              <PrimaryButton onClick={runGenerate}>
                {generating ? "Analyzing…" : "Run Attribution Analysis"}
              </PrimaryButton>
            }
          />
        }
      >
      <div className="grid xl:grid-cols-3 gap-5">
        {col.map(([t, I, tone, items]: any) => (
          <Panel
            key={t}
            className={`p-5 sm:p-6 flex flex-col justify-between border-t-4 ${
              tone === "green" ? "border-t-brand" : tone === "amber" ? "border-t-[#C79B42]" : "border-t-[#6585A8]"
            }`}
          >
            <div>
              <div className="flex items-center gap-3.5 mb-5 pb-4 border-b border-border/50">
                <div
                  className={`h-10 w-10 rounded-full flex items-center justify-center shrink-0 ${
                    tone === "green"
                      ? "bg-soft text-brand"
                      : tone === "amber"
                      ? "bg-amber text-[#78571A]"
                      : "bg-blue text-[#3B5A7D]"
                  }`}
                >
                  <I size={20} />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold text-ink">{t}</h3>
                  <p className="text-[11.5px] text-muted mt-0.5">
                    {tone === "green"
                      ? "Facts established from available evidence."
                      : tone === "amber"
                      ? "Information that cannot be established yet."
                      : "Additional evidence that could help close gaps."}
                  </p>
                </div>
              </div>
              <div className="space-y-3.5">
                {items.map((x: string, i: number) => (
                  <div key={i} className="flex gap-3 border-b border-border/40 pb-3 last:border-0">
                    <span className="h-5 w-5 rounded-full bg-soft flex items-center justify-center shrink-0 text-[11px] font-semibold text-brand mt-0.5">
                      {i + 1}
                    </span>
                    <p className="text-[12.5px] text-ink/90 leading-relaxed">{x}</p>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        ))}
      </div>
      </AsyncBlock>

      <Notice tone="warning">
        <b>Investigative Lead — Not Proof</b>
        <br />
        LINEAGE provides analysis and investigative leads based on available data. It does not establish a person's identity, intent, or responsibility.
      </Notice>

      <Panel className="p-5 sm:p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-5 pb-5 border-b border-border/50">
          <div>
            <h2 className="text-[18px] font-semibold text-ink">Recommended Next Steps</h2>
            <p className="text-[13px] text-muted mt-1">
              Preserve evidence, use official reporting channels, and seek authorized platform records where appropriate.
            </p>
          </div>
          <PrimaryButton onClick={runReport}>
            {reportBusy ? <><Loader2 size={14} className="inline animate-spin mr-1.5" />Generating…</> : "Generate Incident Report"}
          </PrimaryButton>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
          {["Preserve Evidence", "File a Complaint", "Request Takedown", "Seek Support"].map((x, i) => (
            <div className="rounded-xl bg-soft/60 border border-border/60 p-4 hover:bg-soft transition flex flex-col justify-between" key={x}>
              <div>
                <span className="text-[10px] font-mono font-semibold text-brand uppercase tracking-wider">Step 0{i + 1}</span>
                <p className="text-[13px] font-semibold text-ink mt-2">{x}</p>
              </div>
              <ArrowRight size={16} className="text-brand mt-4" />
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
