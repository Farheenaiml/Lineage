import { useState } from "react";
import { X, Loader2, Plus } from "lucide-react";
import { useCase } from "../context/CaseContext";
import { Source, api } from "../lib/api";

/**
 * A real data-entry form. This is what "adding a source" means in the actual
 * product: an investigator has found the content re-posted somewhere and
 * records it here. There is no seeded/demo data anywhere in this flow —
 * every field is typed in by a person and saved to the real backend.
 */
export default function AddSourceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated?: (source: Source) => void;
}) {
  const { addSource, sources, incidentId } = useCase();
  const [placeName, setPlaceName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [platform, setPlatform] = useState("");
  const [account, setAccount] = useState("");
  const [url, setUrl] = useState("");
  const [observedAt, setObservedAt] = useState(() => {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    return now.toISOString().slice(0, 16);
  });
  const [similarity, setSimilarity] = useState("");
  const [relationshipLabel, setRelationshipLabel] = useState("");
  const [linkToSourceId, setLinkToSourceId] = useState("");
  const [relationshipType, setRelationshipType] = useState("repost");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { addRelationship } = useCase();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!platform.trim()) { setError("Platform is required."); return; }
    setBusy(true);
    setError(null);
    try {
      const created = await addSource({
        platform: platform.trim(),
        account_identifier: account.trim() || undefined,
        url: url.trim() || undefined,
        observed_at: new Date(observedAt).toISOString(),
        similarity_score: similarity ? Number(similarity) : undefined,
        relationship_label: relationshipLabel.trim() || undefined,
      });

      // Optional investigator-supplied location (stored with provenance; never guessed).
      if (incidentId && lat.trim() !== "" && lon.trim() !== "") {
        const la = Number(lat), lo = Number(lon);
        if (!Number.isNaN(la) && !Number.isNaN(lo) && Math.abs(la) <= 90 && Math.abs(lo) <= 180) {
          await api.setSourceLocation(incidentId, created.id, {
            latitude: la, longitude: lo, place_name: placeName.trim() || undefined,
            confidence: 60, basis: "Location entered by the investigator when recording this source; not independently verified.",
          });
        }
      }

      if (linkToSourceId) {
        await addRelationship(linkToSourceId, created.id, relationshipType, similarity ? Number(similarity) : undefined);
      }

      onCreated?.(created);
      onClose();
    } catch (err: any) {
      setError(err?.message ?? "Could not save this source.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-card rounded-2xl border border-border shadow-card w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="font-display text-[18px] text-ink">Add Observed Source</h2>
          <button onClick={onClose} className="text-muted hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={submit} className="p-6 space-y-4">
          <p className="text-[12px] text-muted -mt-1">
            Record a place you've found this content re-posted. This is saved directly to the case.
          </p>

          <div>
            <label className="block text-[12px] font-medium mb-1.5">Platform *</label>
            <input
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              placeholder="e.g. Instagram, X, Telegram"
              className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium mb-1.5">Account / identifier</label>
              <input
                value={account}
                onChange={(e) => setAccount(e.target.value)}
                placeholder="@handle or username"
                className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
              />
            </div>
            <div>
              <label className="block text-[12px] font-medium mb-1.5">Observed on</label>
              <input
                type="datetime-local"
                value={observedAt}
                onChange={(e) => setObservedAt(e.target.value)}
                className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-[12px] font-medium mb-1.5">URL (optional)</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Link to the post, if you have it"
              className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium mb-1.5">Similarity % (optional)</label>
              <input
                type="number" min={0} max={100}
                value={similarity}
                onChange={(e) => setSimilarity(e.target.value)}
                placeholder="e.g. 92"
                className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
              />
            </div>
            <div>
              <label className="block text-[12px] font-medium mb-1.5">Relationship note (optional)</label>
              <input
                value={relationshipLabel}
                onChange={(e) => setRelationshipLabel(e.target.value)}
                placeholder="e.g. Cropped repost"
                className="w-full h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
              />
            </div>
          </div>

          <div className="border-t border-border pt-4">
            <label className="block text-[12px] font-medium mb-1.5">Location (optional — shows on the 3D map as “Investigator supplied”)</label>
            <div className="grid grid-cols-3 gap-3">
              <input value={placeName} onChange={(e) => setPlaceName(e.target.value)} placeholder="Place name"
                className="h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15" />
              <input value={lat} onChange={(e) => setLat(e.target.value)} placeholder="Latitude" inputMode="decimal"
                className="h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15" />
              <input value={lon} onChange={(e) => setLon(e.target.value)} placeholder="Longitude" inputMode="decimal"
                className="h-11 rounded-xl border border-border px-3.5 text-[13px] outline-none focus:ring-2 focus:ring-brand/15" />
            </div>
            <p className="text-[11px] text-muted mt-1.5">Leave blank if unknown — coordinates are never guessed. You can also search a place later from the map.</p>
          </div>

          {sources.data.length > 0 && (
            <div className="border-t border-border pt-4">
              <label className="block text-[12px] font-medium mb-1.5">
                Link to an existing source (optional — builds the propagation graph)
              </label>
              <div className="grid grid-cols-2 gap-3">
                <select
                  value={linkToSourceId}
                  onChange={(e) => setLinkToSourceId(e.target.value)}
                  className="h-11 rounded-xl border border-border px-3 text-[13px] outline-none focus:ring-2 focus:ring-brand/15"
                >
                  <option value="">No link</option>
                  {sources.data.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.platform} — {s.account_identifier ?? "unnamed"}
                    </option>
                  ))}
                </select>
                <select
                  value={relationshipType}
                  onChange={(e) => setRelationshipType(e.target.value)}
                  disabled={!linkToSourceId}
                  className="h-11 rounded-xl border border-border px-3 text-[13px] outline-none focus:ring-2 focus:ring-brand/15 disabled:opacity-50"
                >
                  <option value="repost">Repost</option>
                  <option value="crop + re-share">Crop + re-share</option>
                  <option value="screen recording">Screen recording</option>
                  <option value="share">Share</option>
                </select>
              </div>
              <p className="text-[11px] text-muted mt-1.5">
                If this source came from an earlier one you've already recorded, link it — this is
                what draws the connection on the Lineage graph.
              </p>
            </div>
          )}

          {error && (
            <p className="text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 h-11 rounded-xl border border-border text-[13px] font-medium hover:bg-soft transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="flex-1 h-11 rounded-xl bg-brand text-white text-[13px] font-semibold hover:bg-brandDark transition disabled:opacity-60 inline-flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
              {busy ? "Saving…" : "Add Source"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
