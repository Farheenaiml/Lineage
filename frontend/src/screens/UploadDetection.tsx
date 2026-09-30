import { useEffect, useMemo, useState } from "react";
import { ExternalLink, LoaderCircle, Search, CheckCircle2 } from "lucide-react";
import { Panel, PanelHeader, ConfidenceBar, Notice, StatusBadge } from "../components/ui";
import UploadDropzone from "../components/UploadDropzone";
import MediaPreview from "../components/MediaPreview";
import { useCase } from "../context/CaseContext";
import { AsyncBlock, EmptyState } from "../components/states";
import { statusLabel } from "../lib/pipeline";
import { api, WebSearchRun } from "../lib/api";

type ExplainabilityPayload = {
  status: "available" | "unavailable";
  method?: string;
  message?: string;
  face_box?: number[] | null;
  face_confidence?: number | null;
  grid?: number[][] | null;
  frame_timestamp_sec?: number | null;
  target_label?: string | null;
  baseline_score?: number | null;
  max_score_change?: number | null;
};

export default function UploadDetection() {
  const { incidentId, media, detection, fingerprint, incident, sources } = useCase();
  const m = media.data;
  const d = detection.data;
  const live = !!m;

  // The real model reports which detector actually ran. When the pretrained
  // model isn't reachable the backend falls back to the pixel heuristic and
  // says so in model_name — surfaced here rather than hidden.
  const usedFallback = !!d?.model_name?.includes("fallback");
  const likelihood = d?.manipulation_likelihood ?? 0;
  const tone: "red" | "amber" | "green" = likelihood >= 70 ? "red" : likelihood >= 40 ? "amber" : "green";
  const verdictLabel = likelihood >= 70 ? "High likelihood" : likelihood >= 40 ? "Moderate likelihood" : "Low likelihood";
  const explainability = useMemo<ExplainabilityPayload | null>(() => {
    if (!d?.explainability_json) return null;
    try {
      return JSON.parse(d.explainability_json) as ExplainabilityPayload;
    } catch {
      return null;
    }
  }, [d?.explainability_json]);
  const heatmapGrid = explainability?.grid ?? [];
  const [analysisFrameUrl, setAnalysisFrameUrl] = useState<string | null>(null);
  const [webSearchConfigured, setWebSearchConfigured] = useState<boolean | null>(null);
  const [webSearchConsent, setWebSearchConsent] = useState(false);
  const [webSearchBusy, setWebSearchBusy] = useState(false);
  const [webSearchError, setWebSearchError] = useState<string | null>(null);
  const [webSearchRun, setWebSearchRun] = useState<WebSearchRun | null>(null);

  useEffect(() => {
    if (!incidentId || !m || !d) {
      setAnalysisFrameUrl(null);
      return;
    }
    let active = true;
    let objectUrl: string | null = null;
    api.getAnalysisFrame(incidentId, m.id)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setAnalysisFrameUrl(objectUrl);
      })
      .catch(() => { if (active) setAnalysisFrameUrl(null); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [incidentId, m?.id, d?.id]);

  const faceBox = explainability?.face_box;
  const frameWidth = m?.width ?? 1;
  const frameHeight = m?.height ?? 1;
  const validFaceBox = !!faceBox && faceBox.length === 4 && frameWidth > 0 && frameHeight > 0;
  const [faceLeft, faceTop, faceRight, faceBottom] = validFaceBox ? faceBox! : [0, 0, 0, 0];
  const faceWidth = Math.max(1, faceRight - faceLeft);
  const faceHeight = Math.max(1, faceBottom - faceTop);
  const facePosition = {
    left: `${(faceLeft / frameWidth) * 100}%`,
    top: `${(faceTop / frameHeight) * 100}%`,
    width: `${(faceWidth / frameWidth) * 100}%`,
    height: `${(faceHeight / frameHeight) * 100}%`,
  };
  const strongestCell = heatmapGrid.flatMap((row, rowIndex) => row.map((value, columnIndex) => ({ value, rowIndex, columnIndex })))
    .reduce<{ value: number; rowIndex: number; columnIndex: number } | null>(
      (strongest, cell) => !strongest || cell.value > strongest.value ? cell : strongest,
      null,
    );
  const renderHeatmapCells = (opacity: number) => heatmapGrid.flatMap((row, rowIndex) => row.map((value, columnIndex) => {
    const normalized = Math.max(0, Math.min(1, value ?? 0));
    const hue = Math.round(240 * (1 - normalized));
    const strongest = strongestCell?.rowIndex === rowIndex && strongestCell.columnIndex === columnIndex;
    return (
      <span
        key={`${rowIndex}-${columnIndex}`}
        className={`block min-h-0 min-w-0 ${strongest ? "z-10 ring-2 ring-white" : ""}`}
        style={{ backgroundColor: `hsl(${hue} 95% 52%)`, opacity, boxShadow: strongest ? "0 0 0 1px rgba(15, 23, 42, 0.8)" : undefined }}
        title={`Cell ${rowIndex + 1}:${columnIndex + 1} model sensitivity ${normalized.toFixed(4)}`}
      />
    );
  }));

  useEffect(() => {
    let active = true;
    api.getWebSearchStatus()
      .then((status) => { if (active) setWebSearchConfigured(status.configured); })
      .catch(() => { if (active) setWebSearchConfigured(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!incidentId || !m || m.kind !== "image") {
      setWebSearchRun(null);
      return;
    }
    let active = true;
    api.getLatestWebSearch(incidentId, m.id)
      .then((run) => { if (active) setWebSearchRun(run); })
      .catch(() => { if (active) setWebSearchRun(null); });
    return () => { active = false; };
  }, [incidentId, m?.id, m?.kind]);

  async function runWebSearch() {
    if (!incidentId || !m || !webSearchConsent) return;
    setWebSearchBusy(true);
    setWebSearchError(null);
    try {
      const result = await api.generateImageSearchLinks(incidentId, m.id);
      setWebSearchRun(result);
      setWebSearchConsent(false);
    } catch (error: any) {
      setWebSearchError(error?.message ?? "Could not generate search phrases.");
    } finally {
      setWebSearchBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Description header section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border rounded-2xl p-5 sm:p-6 shadow-card">
        <div>
          <h2 className="text-xl font-semibold tracking-[-.02em] text-ink">Detection Analysis</h2>
          <p className="text-[13px] text-muted mt-1 leading-relaxed">
            Assess manipulation likelihood with an explanation — never a bare fake/real verdict.
          </p>
        </div>
        <div className="shrink-0">
          <StatusBadge tone="amber">{statusLabel(incident.data?.status)}</StatusBadge>
        </div>
      </div>

      <UploadDropzone />

      {m?.kind === "image" && (
        <Panel className="p-5 sm:p-6">
          <PanelHeader
            title="Prepare public-web searches"
            subtitle="Gemini describes the image and prepares search phrases. Google or Bing opens only when you choose a link; LINEAGE does not collect results."
            right={<Search className="text-brand" size={19} />}
          />
          <div className="rounded-xl border border-amber/70 bg-amber/30 p-4 text-[12.5px] text-ink leading-relaxed">
            LINEAGE does not search the web automatically. With your permission, the image is sent to Google Gemini to create a description and search phrases. Only when you click a Google or Bing link will your browser send that phrase to the search engine. Under Google's unpaid Gemini terms, prompts and images may be used to improve services and may be reviewed by people; do not send sensitive or confidential images using unpaid quota. LINEAGE stores the description and query phrases, not search results. Images must be 12 MB or smaller.
          </div>
          {webSearchConfigured === false && (
            <p className="text-[12px] text-muted mt-4">Gemini query generation is not configured. Set GEMINI_API_KEY in backend/.env and restart the backend to enable it.</p>
          )}
          <label className="flex items-start gap-3 mt-4 text-[12.5px] text-ink leading-relaxed">
            <input
              type="checkbox"
              checked={webSearchConsent}
              onChange={(event) => setWebSearchConsent(event.target.checked)}
              disabled={!webSearchConfigured || webSearchBusy}
              className="mt-0.5 h-4 w-4 accent-brand"
            />
            <span>I am authorized to submit this image to Google Gemini, understand the data handling notice above, and consent to generating search phrases from it.</span>
          </label>
          <button
            type="button"
            onClick={runWebSearch}
            disabled={!webSearchConfigured || !webSearchConsent || webSearchBusy}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-[12.5px] font-semibold text-white hover:bg-brandDark disabled:cursor-not-allowed disabled:opacity-50"
          >
            {webSearchBusy ? <LoaderCircle size={15} className="animate-spin" /> : <Search size={15} />}
            {webSearchBusy ? "Preparing search phrases…" : "Generate search links"}
          </button>
          {webSearchError && <p role="alert" className="mt-3 text-[12px] text-red-800">{webSearchError}</p>}

          {webSearchRun && (
            <div className="mt-6 border-t border-border pt-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-[15px] font-semibold text-ink">Search phrases to review</h3>
                <span className="text-[11px] text-muted">{webSearchRun.model_name} · {new Date(webSearchRun.created_at).toLocaleString()}</span>
              </div>
              <p className="text-[12px] text-muted leading-relaxed mt-2"><b className="text-ink">Image description:</b> {webSearchRun.image_description}</p>
              <p className="text-[12px] text-muted leading-relaxed mt-2">{webSearchRun.summary}</p>
              {webSearchRun.search_queries.length === 0 ? (
                <p className="mt-4 text-[12.5px] text-muted">No search phrases were generated. This does not mean the image is absent from the web.</p>
              ) : (
                <div className="space-y-3 mt-4">
                  {webSearchRun.search_queries.map((searchQuery, index) => (
                    <div key={`${searchQuery.query}-${index}`} className="border border-border rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-ink">{searchQuery.query}</p>
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <a href={searchQuery.google_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[11.5px] font-semibold text-ink hover:bg-soft">
                          Google <ExternalLink size={12} />
                        </a>
                        <a href={searchQuery.bing_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[11.5px] font-semibold text-ink hover:bg-soft">
                          Bing <ExternalLink size={12} />
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-muted mt-4">Open a search link, review pages yourself, then use <b>+ Add Source</b> in Evidence Locker or Lineage to save a page you observed. LINEAGE does not verify exact image matches.</p>
            </div>
          )}
        </Panel>
      )}

      <div className="grid xl:grid-cols-[.9fr_1.2fr_.8fr] gap-5">
          <Panel className="p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <PanelHeader title={live ? "Your Upload" : "Uploaded Media"} subtitle={m?.original_filename ?? "No media uploaded yet"} />
            <MediaPreview incidentId={incidentId} media={m} className="h-[320px] sm:h-[360px] rounded-xl shadow-inner" />
          </div>
          <div className="mt-5 space-y-2.5 text-[12.5px] pt-4 border-t border-border/60">
            {[
              ["File type", m?.kind ?? "—"],
              ["File size", m ? `${Math.round(m.file_size_bytes / 1024)} KB` : "—"],
              ["Dimensions", m?.width && m?.height ? `${m.width} × ${m.height}` : "—"],
              ["Fingerprint", fingerprint.loading ? "Running…" : fingerprint.data ? "Complete" : "Not yet run"],
            ].map(([a, b]) => (
              <div className="flex justify-between border-b border-border/40 pb-2 last:border-0" key={a}>
                <span className="text-muted">{a}</span>
                <span className="font-semibold text-ink">{b}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <PanelHeader
              title="Manipulation Analysis"
              subtitle={
                d
                  ? usedFallback
                    ? "Heuristic fallback — the pretrained model was unavailable"
                    : `Pretrained model: ${d.model_name}`
                  : "No analysis run yet"
              }
            />
            <AsyncBlock
              loading={detection.loading}
              error={detection.error}
              loadingLabel="Running detection on the server…"
              isEmpty={!d}
              empty={
                <EmptyState
                  title="No detection result yet"
                  detail="Upload an image or video above. LINEAGE runs the detection model server-side and reports a likelihood with an explanation — never a bare fake/real verdict."
                />
              }
            >
            <div className="flex flex-col sm:flex-row items-center gap-6 mb-7 bg-soft/40 p-4 rounded-xl border border-border/50">
              <div
                className="h-36 w-36 rounded-full flex items-center justify-center shrink-0 shadow-xs"
                style={{
                  background: `conic-gradient(#B96255 ${likelihood}%, #E9EDE8 0)`,
                }}
              >
                <div className="h-28 w-28 bg-card rounded-full flex flex-col items-center justify-center shadow-xs">
                  <b className="text-[34px] font-semibold text-ink leading-none">{Math.round(likelihood)}%</b>
                  <span className="text-[10px] text-muted font-medium mt-1">likelihood</span>
                </div>
              </div>
              <div>
                <StatusBadge tone={tone}>{verdictLabel}</StatusBadge>
                <p className="text-[12.5px] text-ink leading-relaxed mt-3">{d?.explanation ?? "—"}</p>
              </div>
            </div>

            <div className="space-y-4">
              <ConfidenceBar label="Manipulation likelihood" value={likelihood} tone={tone} />
              {d?.edge_irregularity != null && (
                <ConfidenceBar label="Edge irregularity" value={d.edge_irregularity} tone="amber" />
              )}
              {d?.compression_density != null && (
                <ConfidenceBar label="Compression density anomaly" value={d.compression_density} tone="amber" />
              )}

              <section className="mt-6 rounded-2xl border border-border bg-soft/30 p-4" aria-labelledby="facial-analysis-title">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 id="facial-analysis-title" className="text-[13px] font-semibold text-ink">Facial Manipulation Analysis</h3>
                    <p className="mt-1 text-[11px] text-muted">Model contribution visualization, not proof of manipulated pixels.</p>
                  </div>
                  <StatusBadge tone={explainability?.status === "available" ? "amber" : "gray"}>
                    {explainability?.status === "available" ? "Explainability available" : "Explainability unavailable"}
                  </StatusBadge>
                </div>
                <p className="mt-3 text-[12px] text-muted leading-relaxed">
                  {explainability?.message ?? "No explanation data is available for this detection result."}
                  {explainability?.frame_timestamp_sec != null && ` Analyzed frame: ${explainability.frame_timestamp_sec.toFixed(2)} s.`}
                </p>

                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div className="min-w-0">
                    <p className="mb-2 text-[11px] font-semibold text-ink">Original {m?.kind === "video" ? "analysis frame" : "image"}</p>
                    <div className="flex h-[220px] items-center justify-center overflow-hidden rounded-lg border border-border bg-neutral-950 p-2">
                      {analysisFrameUrl ? (
                        <img src={analysisFrameUrl} alt="Original frame used by the manipulation detector" className="max-h-full max-w-full object-contain" />
                      ) : <span className="text-[11px] text-white/70">Loading analyzed frame…</span>}
                    </div>
                  </div>
                  {explainability?.status === "available" && heatmapGrid.length > 0 && validFaceBox ? (
                    <>
                      <div className="min-w-0">
                        <p className="mb-2 text-[11px] font-semibold text-ink">Face-region sensitivity</p>
                        <div className="mx-auto relative overflow-hidden rounded-lg border border-border bg-neutral-950" style={{ width: `min(100%, ${Math.min(280, 220 * faceWidth / faceHeight)}px)`, aspectRatio: `${faceWidth} / ${faceHeight}` }}>
                          {analysisFrameUrl && (
                            <img
                              src={analysisFrameUrl}
                              alt="Face crop used for the contribution visualization"
                              className="absolute max-w-none grayscale opacity-35"
                              style={{ width: `${(frameWidth / faceWidth) * 100}%`, height: `${(frameHeight / faceHeight) * 100}%`, left: `${(-faceLeft / faceWidth) * 100}%`, top: `${(-faceTop / faceHeight) * 100}%` }}
                            />
                          )}
                          {heatmapGrid[0]?.length > 0 && (
                            <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${heatmapGrid[0].length}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${heatmapGrid.length}, minmax(0, 1fr))` }}>
                              {renderHeatmapCells(0.9)}
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <p className="mb-2 text-[11px] font-semibold text-ink">Contribution overlay</p>
                        <div className="mx-auto relative overflow-hidden rounded-lg border border-border bg-neutral-950" style={{ width: `min(100%, ${Math.min(280, 220 * frameWidth / frameHeight)}px)`, aspectRatio: `${frameWidth} / ${frameHeight}` }}>
                          {analysisFrameUrl && <img src={analysisFrameUrl} alt="Analyzed original frame" className="absolute inset-0 h-full w-full object-fill" />}
                          <div className="absolute grid" style={{ ...facePosition, gridTemplateColumns: `repeat(${heatmapGrid[0]?.length ?? 1}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${heatmapGrid.length}, minmax(0, 1fr))` }}>
                            {renderHeatmapCells(0.62)}
                          </div>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="flex min-h-[220px] flex-col justify-center rounded-lg border border-border bg-card p-4 text-[12px] text-muted md:col-span-2">
                      <b className="mb-1 text-ink">{explainability?.status === "available" ? "Face-region visualization unavailable" : "Explainability unavailable"}</b>
                      <span>{explainability?.message ?? "No explanation data is available for this detection result."}</span>
                    </div>
                  )}
                </div>
                {explainability?.status === "available" && heatmapGrid.length > 0 && validFaceBox && (
                  <>
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11px] text-muted">
                      <span>Model: {d?.model_name ?? "Not recorded"}</span>
                      <span>Manipulation likelihood: {likelihood.toFixed(1)}%</span>
                      {strongestCell && <span>Strongest sensitivity: cell {strongestCell.rowIndex + 1}:{strongestCell.columnIndex + 1}</span>}
                      {faceBox && <span>Face detected: {Math.round(faceLeft)}, {Math.round(faceTop)} to {Math.round(faceRight)}, {Math.round(faceBottom)}</span>}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[10px] text-muted" aria-label="Heatmap sensitivity scale">
                      <span>Lower contribution</span><span className="h-2 flex-1 rounded-full bg-gradient-to-r from-blue-600 via-cyan-400 via-yellow-300 to-red-600" /><span>Higher contribution</span>
                    </div>
                  </>
                )}
              </section>

              <div className="grid grid-cols-2 gap-4 mt-6 pt-4 border-t border-border/60 text-[12px]">
                <div>
                  <p className="text-muted font-medium">Model used</p>
                  <b className="block mt-1 text-ink break-words">{d?.model_name ?? "—"}</b>
                </div>
                <div>
                  <p className="text-muted font-medium">Likely technique</p>
                  <b className="block mt-1 text-ink">{d?.likely_technique ?? "Not reported"}</b>
                </div>
                <div>
                  <p className="text-muted font-medium">Detected region</p>
                  <b className="block mt-1 text-ink">{d?.detected_region ?? "Not reported"}</b>
                </div>
                <div>
                  <p className="text-muted font-medium">Analyzed at</p>
                  <b className="block mt-1 text-ink">{d ? new Date(d.created_at).toLocaleString() : "—"}</b>
                </div>
              </div>
            </div>
            </AsyncBlock>
          </div>
        </Panel>

        <div className="space-y-5">
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Frame Analysis" />
            <div className="min-h-24 rounded-xl border border-border bg-soft/40 flex items-center justify-center text-center px-4">
              <div>
                <p className="text-[13px] font-semibold text-ink">{m?.kind === "video" ? "Video midpoint frame" : "Single image"}</p>
                <p className="text-[11.5px] text-muted mt-1">{m?.kind === "video" ? "Detection and fingerprinting sample the middle frame. Full multi-frame analysis is not implemented." : "Detection and fingerprinting use the uploaded image."}</p>
              </div>
            </div>
          </Panel>

          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Next Steps" />
            <div className="space-y-3 text-[12.5px]">
              {([
                ["Media uploaded", !!m],
                ["Detection completed", !!d],
                ["Fingerprinting completed", !!fingerprint.data],
                ["External sources added", sources.data.some((source) => source.platform !== "User upload")],
              ] as [string, boolean][]).map(([label, done]) => (
                <div className="flex items-center gap-3" key={label}>
                  <CheckCircle2 size={16} className={done ? "text-brand shrink-0" : "text-border shrink-0"} />
                  <span className={done ? "font-semibold text-ink" : "text-muted"}>{label}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Notice tone="info">
            <b>Important Notice</b>
            <br />
            This analysis provides an indication of likelihood, not definitive proof. Review the evidence and recommended next steps.
          </Notice>
        </div>
      </div>
    </div>
  );
}
