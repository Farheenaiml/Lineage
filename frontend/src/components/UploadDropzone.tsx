import { useRef, useState } from "react";
import { UploadCloud, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { useCase } from "../context/CaseContext";

/**
 * Uploads a real file to the backend, which then runs detection and
 * fingerprinting server-side. Replaces the earlier in-browser-only
 * analysis: the heavy work now happens where the real models live.
 */
export default function UploadDropzone() {
  const { incidentId, media, detection, fingerprint, uploadAndAnalyze } = useCase();
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const busy = media.loading || detection.loading || fingerprint.loading;

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    try {
      await uploadAndAnalyze(files[0]);
    } catch (e: any) {
      setError(e?.message ?? "Upload failed.");
    }
  }

  if (!incidentId) {
    return (
      <div className="border border-dashed border-border rounded-2xl p-5 text-center text-[12.5px] text-muted">
        Open or create an investigation before uploading media.
      </div>
    );
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
        onClick={() => !busy && inputRef.current?.click()}
        className={`rounded-2xl border border-dashed p-5 text-center transition ${
          busy ? "cursor-wait opacity-80" : "cursor-pointer hover:bg-soft/40"
        } ${dragOver ? "border-brand bg-soft/60" : "border-border"}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*,video/*"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />

        {busy ? (
          <div className="flex flex-col items-center gap-2 py-2">
            <Loader2 size={20} className="text-brand animate-spin" />
            <p className="text-[12.5px] text-ink font-medium">
              {media.loading ? "Uploading and encrypting…" : "Running analysis on the server…"}
            </p>
            <p className="text-[11px] text-muted">
              {detection.loading && "Detection running"}
              {detection.loading && fingerprint.loading && " · "}
              {fingerprint.loading && "Fingerprinting running"}
            </p>
          </div>
        ) : media.data ? (
          <div className="flex flex-col items-center gap-1.5 py-1">
            <CheckCircle2 size={18} className="text-brand" />
            <p className="text-[12.5px] text-ink font-medium">{media.data.original_filename}</p>
            <p className="text-[11px] text-muted">
              Analyzed server-side · click to replace with another file
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1.5 py-1">
            <UploadCloud size={20} className="text-faint" />
            <p className="text-[12.5px] text-ink font-medium">Drop a file to analyze</p>
            <p className="text-[11px] text-muted">
              Images and video · encrypted at rest · analyzed on the server
            </p>
          </div>
        )}
      </div>

      {(error || media.error) && (
        <p className="mt-2 text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {error || media.error}
        </p>
      )}
      {detection.error && (
        <p className="mt-2 text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          Detection failed: {detection.error}
        </p>
      )}
      {fingerprint.error && (
        <p className="mt-2 text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          Fingerprinting failed: {fingerprint.error}
        </p>
      )}
    </div>
  );
}
