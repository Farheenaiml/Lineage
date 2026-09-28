import { Image, AudioLines, ScanFace, Layers3, CheckCircle2 } from "lucide-react";
import { Panel, PanelHeader } from "../components/ui";
import { useCase } from "../context/CaseContext";
import { toDisplaySources, parseFaceEmbedding } from "../lib/adapters";

export default function FingerprintScreen() {
  const { fingerprint: fpSlice, media, sources: sourcesSlice } = useCase();
  const fp = fpSlice.data;
  const sources = toDisplaySources(sourcesSlice.data).filter((source) => source.platform !== "User upload");
  const face = parseFaceEmbedding(fp?.face_embedding_json ?? null);

  const keyframeCount = (() => {
    if (!fp?.keyframe_hashes_json) return null;
    try { return (JSON.parse(fp.keyframe_hashes_json) as unknown[]).length; } catch { return null; }
  })();

  const cards = [
    [Image, "Visual Fingerprint", "Perceptual Hash (aHash)", fp?.average_hash ?? "—"],
    [AudioLines, "Audio Fingerprint", "Acoustic Hash", fp?.audio_fingerprint ?? "Not computed"],
    [
      ScanFace,
      "Face Embedding",
      face.foundFace ? `Real ${face.dims}-dim vector` : "Facial Feature Vector",
      face.foundFace ? face.preview : fp ? "No face detected in this media" : "—",
    ],
    [
      Layers3,
      "Key Frame Fingerprints",
      "Extracted key frames",
      keyframeCount != null ? `${keyframeCount} frame${keyframeCount === 1 ? "" : "s"} extracted` : "Single frame",
    ],
  ];

  return (
    <div className="space-y-6">
      {/* Action Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border rounded-2xl p-5 sm:p-6 shadow-card">
        <div>
          <h2 className="text-xl font-semibold tracking-[-.02em] text-ink">Content Fingerprinting</h2>
          <p className="text-[13px] text-muted mt-1 leading-relaxed">
            Fingerprints describe this upload. External similarity is not automatically calculated in this build.
          </p>
        </div>
        <span className="text-[11.5px] text-muted">Generated automatically after upload</span>
      </div>

      {/* Fingerprint Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {cards.map(([I, t, s, v]: any) => (
          <Panel key={t} className="p-5 sm:p-6 flex flex-col justify-between">
            <div>
              <div className="h-10 w-10 rounded-xl bg-soft text-brand flex items-center justify-center shadow-xs">
                <I size={20} />
              </div>
              <p className="text-[15px] font-semibold text-ink mt-4">{t}</p>
              <p className="text-[11.5px] text-muted mt-1">{s}</p>
            </div>
            <div>
              <div className="mt-4 rounded-xl bg-[#FAFBF9] border border-border/70 p-3 min-h-[74px] flex items-center">
                <span className="font-mono text-[11px] text-ink/90 break-all leading-tight">{v}</span>
              </div>
              <div className={`flex items-center gap-2 font-medium text-[11.5px] mt-4 ${t === "Audio Fingerprint" ? "text-muted" : "text-brand"}`}>
                {t === "Audio Fingerprint" ? null : <CheckCircle2 size={15} />}
                {t === "Audio Fingerprint" ? "Audio fingerprinting is not available" : fp ? "Computed from this upload" : fpSlice.loading ? "Computing…" : "Not computed"}
              </div>
            </div>
          </Panel>
        ))}
      </div>

      {/* Similarity Matches & Details */}
      <div className="grid xl:grid-cols-[1.2fr_.8fr] gap-5">
        <Panel className="p-5 sm:p-6">
          <PanelHeader title="External Sources" subtitle="LINEAGE does not compare external pages automatically. Any percentage shown is an investigator-entered estimate." />
          <div className="space-y-2.5 mt-4">
            {sources.length === 0 && <p className="text-[12.5px] text-muted">No external sources have been added. The uploaded file is the reference media, not a match against itself. Use + Add Source in Evidence Locker to record a page you find.</p>}
            {sources.map((s) => (
              <div
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3.5 rounded-xl border border-border/50 hover:bg-soft/40 transition"
                key={s.id}
              >
                <div className="flex items-center gap-3.5">
                  <div className="h-10 w-10 rounded-lg bg-soft flex items-center justify-center text-brand text-[11px] font-bold shrink-0">
                    {s.platform.slice(0, 2)}
                  </div>
                  <div>
                    <p className="text-[13px] font-semibold text-ink">{s.platform}</p>
                    <p className="text-[11px] text-muted">
                      {s.account} · {s.observedAt}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="w-40 text-right">
                    <p className="text-[11.5px] font-semibold text-ink">{s.similarity != null ? `${s.similarity}% investigator estimate` : "Not scored"}</p>
                    <p className="text-[10.5px] text-muted mt-1">{s.similarity != null ? "Entered manually; not calculated by LINEAGE" : "No score provided"}</p>
                  </div>
                  {s.url && <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-[11.5px] font-medium border border-border rounded-lg px-3.5 py-1.5 hover:bg-soft transition">Open</a>}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <div className="space-y-5">
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Fingerprint Details" />
            <div className="space-y-2.5 text-[12.5px] mt-4">
              {[
                ["File Name", media.data?.original_filename ?? "—"],
                ["File Type", media.data ? (media.data.kind === "video" ? "Video" : "Image") : "—"],
                ["File Size", media.data ? `${Math.round(media.data.file_size_bytes / 1024)} KB` : "—"],
                ["Resolution", media.data?.width && media.data?.height ? `${media.data.width} × ${media.data.height}` : "—"],
                ["Face detected", fp ? (face.foundFace ? `Yes (${Math.round((face.confidence ?? 0) * 100)}% confidence)` : "No") : "—"],
                ["Fingerprint Status", fp ? "Complete" : fpSlice.loading ? "Running…" : "Not yet run"],
              ].map(([a, b]) => (
                <div className="flex justify-between border-b border-border/40 pb-2 last:border-0" key={a}>
                  <span className="text-muted">{a}</span>
                  <span className="font-semibold text-ink text-right">{b}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="p-5 sm:p-6">
            <PanelHeader title="How it works?" />
            <p className="text-[12.5px] text-muted leading-relaxed">
              LINEAGE generates unique digital fingerprints from visual, audio, structural and facial features, then compares those signatures against known or observed sources.
            </p>
            <div className="mt-4">
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
