import { useEffect, useState } from "react";
import { FileImage, LoaderCircle } from "lucide-react";
import { api, MediaItem } from "../lib/api";

export default function MediaPreview({
  incidentId,
  media,
  className = "",
}: {
  incidentId: string | null;
  media: MediaItem | null;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!incidentId || !media) {
      setUrl(null);
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setLoading(true);
    setError(null);
    api.getMediaPreview(incidentId, media.id)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((cause: any) => {
        if (active) setError(cause?.message ?? "Preview unavailable.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [incidentId, media?.id]);

  return (
    <div className={`relative flex items-center justify-center overflow-hidden bg-brandDark ${className}`}>
      {url && media?.kind === "image" && (
        <img src={url} alt={`Uploaded case media: ${media.original_filename}`} className="h-full w-full object-contain" />
      )}
      {url && media?.kind === "video" && (
        <video src={url} controls playsInline preload="metadata" className="h-full w-full object-contain" aria-label={`Uploaded case video: ${media.original_filename}`} />
      )}
      {(!url || loading || error) && (
        <div className="flex flex-col items-center gap-2 px-4 text-center text-white/75">
          {loading ? <LoaderCircle size={26} className="animate-spin" /> : <FileImage size={30} />}
          <span className="text-[12px]">{loading ? "Loading original media…" : error ?? "No media uploaded yet"}</span>
        </div>
      )}
      {media && <span className="absolute bottom-3 left-3 max-w-[calc(100%-24px)] truncate rounded-lg bg-black/60 px-3 py-1 text-[11px] text-white">{media.original_filename}</span>}
    </div>
  );
}