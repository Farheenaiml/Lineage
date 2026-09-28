import { useRef, useState } from "react";
import { UploadCloud, Search, Fingerprint, FileText, Lock, ArrowRight, CheckCircle2, LoaderCircle, Circle } from "lucide-react";
import { ScreenKey } from "../components/Sidebar";
import { Panel, SectionTitle, PrimaryButton } from "../components/ui";
import { AnalysisStage, useCase } from "../context/CaseContext";
import { api } from "../lib/api";

export default function NewInvestigation({ onNavigate }: { onNavigate: (k: ScreenKey) => void }) {
  const { setIncidentId, uploadAndAnalyze, analysisStage, setAnalysisStage } = useCase();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);

  // Creates a real incident on the server, then (if a file was chosen)
  // uploads it so detection and fingerprinting run server-side. The user
  // lands on Detection when there's media to look at, Overview otherwise.
  const submit = async () => {
    if (isAnalyzing) return;
    if (!title.trim()) { setError("Give the investigation a title first."); return; }
    setIsAnalyzing(true); setError(null);
    try {
      setAnalysisStage("creating");
      const incident = await api.createIncident(title.trim(), description.trim() || undefined);
      setIncidentId(incident.id);
      if (file) {
        await uploadAndAnalyze(file, incident.id);
        onNavigate("detection");
      } else {
        setAnalysisStage(null);
        onNavigate("overview");
      }
    } catch (e: any) {
      setError(e?.message ?? "Could not create the investigation.");
    } finally {
      setIsAnalyzing(false);
      if (!file) setAnalysisStage(null);
    }
  };

  return (
    <div className="max-w-[1250px] mx-auto space-y-6">
      <SectionTitle
        eyebrow="Investigation"
        title="Start a New Investigation"
        description="Create a case and upload an image or video for detection, fingerprinting, and evidence preservation."
      />

      <AnalysisProgress stage={analysisStage} />

      <div className="grid xl:grid-cols-[1.5fr_1fr] gap-6 items-start">
        {/* Left Column: Form & Dropzone */}
        <Panel className="p-6 sm:p-8 space-y-6">
          <div>
            <h2 className="text-lg font-semibold text-ink">Case Information</h2>
            <p className="text-[12.5px] text-muted mt-1">Provide details to identify and organize this investigation.</p>
          </div>

          <div>
            <label className="block text-[12.5px] font-semibold text-ink mb-2">
              Incident Title <span className="text-[#B96255]">*</span>
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Riya's Case"
              className="w-full h-11 rounded-xl border border-border bg-card px-4 text-[13px] outline-none focus:ring-2 focus:ring-brand/20 transition"
            />
          </div>

          <div>
            <label className="block text-[12.5px] font-semibold text-ink mb-2">
              Description <span className="text-muted font-normal">(Optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Add any details you want to include (where you found the content, when you saw it, etc.)"
              className="w-full min-h-[110px] rounded-xl border border-border bg-card px-4 py-3 text-[13px] outline-none resize-none focus:ring-2 focus:ring-brand/20 transition leading-relaxed"
            />
          </div>

          <div className="pt-4 border-t border-border/60">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-ink">Add Media</h3>
              <span className="text-[11.5px] text-muted font-medium">Max 500 MB</span>
            </div>

            <div
              onClick={() => !isAnalyzing && ref.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const dropped = event.dataTransfer.files[0];
                if (!dropped) return;
                if (/^(image\/|video\/)/.test(dropped.type)) {
                  setFile(dropped);
                  setError(null);
                } else {
                  setError("Choose an image or video file.");
                }
              }}
              className="min-h-[240px] rounded-2xl border-2 border-dashed border-[#BAC4BB] bg-[#FAFBF9] p-6 flex flex-col items-center justify-center text-center hover:bg-soft/50 transition cursor-pointer group shadow-xs"
            >
              <input
                ref={ref}
                type="file"
                accept="image/*,video/*"
                className="hidden"
                onChange={(event) => {
                  const selected = event.target.files?.[0];
                  if (!selected) return;
                  if (/^(image\/|video\/)/.test(selected.type)) {
                    setFile(selected);
                    setError(null);
                  } else {
                    setError("Choose an image or video file.");
                  }
                  event.currentTarget.value = "";
                }}
              />
              {isAnalyzing ? (
                <>
                  <div className="h-14 w-14 rounded-full bg-soft flex items-center justify-center text-brand">
                    <LoaderCircle size={24} className="animate-spin" />
                  </div>
                  <p className="font-semibold text-ink text-[15px] mt-4">{stageLabel(analysisStage)}</p>
                  <p className="text-[12.5px] text-muted mt-1">The server will update each stage as it completes.</p>
                </>
              ) : file ? (
                <>
                  <div className="h-14 w-14 rounded-full bg-soft flex items-center justify-center text-brand">
                    <CheckCircle2 size={26} />
                  </div>
                  <p className="font-semibold text-ink text-[15px] mt-4">{file.name}</p>
                  <p className="text-[12.5px] text-muted mt-1">{Math.round(file.size / 1024)} KB · ready to analyze</p>
                </>
              ) : (
                <>
                  <div className="h-14 w-14 rounded-full bg-soft flex items-center justify-center text-brand group-hover:scale-105 transition-transform">
                    <UploadCloud size={26} />
                  </div>
                  <p className="font-semibold text-ink text-[15px] mt-4">Drag & drop an image or video</p>
                  <p className="text-[12.5px] text-muted mt-1">The original is encrypted and analyzed on the server.</p>
                  <span className="my-3 text-[11.5px] text-faint font-medium">or</span>
                  <span className="rounded-xl bg-brand text-white px-5 py-2.5 text-[12.5px] font-semibold hover:bg-brandDark transition shadow-xs">Browse Files</span>
                  <p className="text-[11px] text-faint mt-4">JPG, PNG, WEBP, MP4, MOV, WEBM, AVI</p>
                </>
              )}
            </div>

            {error && <p className="text-[12.5px] font-medium text-[#8A4138] mt-3">{error}</p>}
          </div>
        </Panel>

        {/* Right Column: "What happens next?" & Privacy */}
        <div className="space-y-5">
          {/* What happens next Card */}
          <Panel className="p-6 sm:p-7 space-y-5">
            <h2 className="text-lg font-semibold text-ink pb-2 border-b border-border/50">What happens next?</h2>

            <div className="space-y-4">
              {[
                [Search, "AI Analysis", "Detect manipulation and return a likelihood score with an explanation."],
                [Fingerprint, "Fingerprinting", "Generate digital signatures for similarity matching."],
                [FileText, "Evidence Building", "Preserve sources and organize evidence."],
                [CheckCircle2, "Review & Report", "Understand the attribution gap and generate a structured report."],
              ].map(([I, t, d]: any, i) => (
                <div key={t} className="flex gap-3.5 items-start pb-3.5 border-b border-border/40 last:border-0 last:pb-0">
                  <div className="h-10 w-10 shrink-0 rounded-full bg-soft flex items-center justify-center text-brand mt-0.5 shadow-xs">
                    <I size={18} />
                  </div>
                  <div>
                    <p className="text-[13.5px] font-semibold text-ink">
                      {i + 1}. {t}
                    </p>
                    <p className="text-[12.5px] text-muted leading-relaxed mt-1">{d}</p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          {/* Privacy Matters Card */}
          <Panel className="p-6 sm:p-7 bg-[#F8F1EC] border-[#E8D8CE]">
            <div className="flex gap-4 items-start">
              <div className="h-10 w-10 rounded-xl bg-[#E8D8CE]/60 text-[#765A4D] flex items-center justify-center shrink-0 mt-0.5">
                <Lock size={20} />
              </div>
              <div>
                <h3 className="text-[15px] font-semibold text-[#5A4339]">Your Privacy Matters</h3>
                <p className="text-[12.5px] text-[#765A4D] leading-relaxed mt-1.5">
                  Your identity is pseudonymous by default. Evidence is handled securely and only included in exports you explicitly request.
                </p>
              </div>
            </div>
          </Panel>

          {/* Action Button */}
          <div className="pt-2 space-y-3">
            <PrimaryButton className="w-full py-3.5 text-[14px] shadow-sm" onClick={submit}>
              {isAnalyzing ? "Processing media…" : file ? "Create Case & Analyze Media" : "Create Investigation"}
            </PrimaryButton>
            <p className="text-center text-[11.5px] text-muted font-medium">Safe. Secure. Supportive.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

const stageOrder: AnalysisStage[] = ["creating", "uploading", "detection", "fingerprinting", "evidence", "attribution", "report", "complete"];


function AnalysisProgress({ stage }: { stage: AnalysisStage | null }) {
  const activeIndex = stage ? stageOrder.indexOf(stage) : -1;
  const labels = ["Create", "Upload", "Detect", "Fingerprint", "Evidence", "Attribution", "Report", "Complete"];
  const currentLabel = stage ? stageNames[stage] : "Ready to begin";
  const percent = activeIndex < 0 ? 0 : Math.round(((activeIndex + (stage === "complete" ? 1 : 0.5)) / stageOrder.length) * 100);

  return (
    <section className="rounded-xl border border-border bg-card p-4 sm:p-5" aria-label="Investigation progress">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-semibold text-ink">Investigation workflow</h2>
          <p className="text-[12px] text-muted mt-1">{currentLabel}</p>
        </div>
        {stage && <span className="text-[12px] font-semibold text-brand tabular-nums">{percent}%</span>}
      </div>
      <div className="h-1.5 rounded-full bg-soft mt-3 overflow-hidden" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-brand transition-all duration-300" style={{ width: `${percent}%` }} />
      </div>
      <ol className="mt-4 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-x-3 gap-y-3">
        {stageOrder.map((item, index) => {
          const done = activeIndex > index || stage === "complete";
          const current = stage === item;
          return (
            <li key={item} className="flex items-center gap-2 min-w-0" aria-current={current ? "step" : undefined}>
              {done ? <CheckCircle2 size={16} className="text-brand shrink-0" /> : current ? <LoaderCircle size={16} className="text-brand animate-spin shrink-0" /> : <Circle size={16} className="text-border shrink-0" />}
              <span className={`text-[11px] leading-tight ${current || done ? "font-semibold text-ink" : "text-muted"}`}>{labels[index]}</span>
            </li>
          );
        })}
      </ol>
      {!stage && <p className="text-[11px] text-muted mt-3">Create a case to start. Upload is optional; you can add media later from Detection Analysis.</p>}
    </section>
  );
}

const stageNames: Record<AnalysisStage, string> = {
  creating: "Creating case",
  uploading: "Uploading and encrypting media",
  detection: "Running manipulation analysis",
  fingerprinting: "Generating fingerprints",
  evidence: "Saving original media as evidence",
  attribution: "Building attribution gap",
  report: "Generating report",
  complete: "Analysis complete",
};

function stageLabel(stage: AnalysisStage | null): string {
  return stage ? stageNames[stage] : "Preparing investigation";
}
