import { useState } from "react";
import { X, Search, MapPin, Loader2, ShieldAlert } from "lucide-react";
import { api, GeoData, GeocodeResult } from "../../lib/api";

/**
 * Investigator-supplied location entry. Coordinates come from a person (typed, or picked from an
 * OpenStreetMap Nominatim result) — never generated. Saved with provenance = investigator_supplied.
 */
export default function LocationEditor({
  incidentId, source, initial, onClose, onSaved,
}: {
  incidentId: string;
  source: { id: string; label: string; platform: string };
  initial?: { latitude: number; longitude: number; place_name?: string; confidence?: number; basis?: string | null };
  onClose: () => void;
  onSaved: (g: GeoData) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [lat, setLat] = useState(initial ? String(initial.latitude) : "");
  const [lon, setLon] = useState(initial ? String(initial.longitude) : "");
  const [name, setName] = useState(initial?.place_name ?? "");
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [conf, setConf] = useState(initial?.confidence ?? 60);
  const [basis, setBasis] = useState(initial?.basis ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function search() {
    if (q.trim().length < 2) return;
    setSearching(true); setErr(null);
    try { setResults((await api.geocode(q.trim())).results); }
    catch (e: any) { setErr(e?.message ?? "Search failed."); setResults([]); }
    finally { setSearching(false); }
  }
  function pick(r: GeocodeResult) {
    setLat(r.latitude.toFixed(5)); setLon(r.longitude.toFixed(5)); setName(r.name); setCountry(r.country ?? ""); setCity(r.city ?? ""); setRegion(r.region ?? "");
    if (!basis) setBasis(`Selected from OpenStreetMap Nominatim search "${q}". Place-level, not a device location.`);
    setResults([]);
  }
  async function save() {
    const la = Number(lat), lo = Number(lon);
    if (lat === "" || lon === "" || Number.isNaN(la) || Number.isNaN(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
      setErr("Enter valid coordinates (latitude −90…90, longitude −180…180)."); return;
    }
    setBusy(true); setErr(null);
    try {
      const g = await api.setSourceLocation(incidentId, source.id, {
        latitude: la, longitude: lo, place_name: name.trim() || undefined, country: country || undefined,
        city: city.trim() || undefined, region: region.trim() || undefined,
        confidence: conf, basis: basis.trim() || undefined,
      });
      onSaved(g); onClose();
    } catch (e: any) { setErr(e?.message ?? "Could not save location."); }
    finally { setBusy(false); }
  }

  const inp = "w-full h-10 rounded-xl border border-border px-3 text-[13px] outline-none focus:ring-2 focus:ring-brand/15 bg-white";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card rounded-2xl border border-border shadow-soft w-full max-w-lg max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="font-display text-[18px] text-ink">Set location · {source.label}</h2>
            <p className="text-[11.5px] text-muted">{source.platform}</p>
          </div>
          <button onClick={onClose} className="text-muted hover:text-ink"><X size={18} /></button>
        </div>
        <div className="p-6 space-y-4">
          <div className="rounded-xl bg-amber/60 border border-[#E6CF95] p-3 text-[11.5px] text-[#78571A] flex gap-2">
            <ShieldAlert size={15} className="shrink-0 mt-0.5" />
            <span>Saved as <b>Investigator supplied</b>. It appears on the map but is never counted as a verified observation. Do not enter a location you cannot justify.</span>
          </div>

          <div>
            <label className="block text-[12px] font-medium mb-1.5">Search place (OpenStreetMap)</label>
            <div className="flex gap-2">
              <input className={inp} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Mumbai, India"
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }} />
              <button type="button" onClick={search} className="h-10 px-4 rounded-xl bg-brand text-white text-[12.5px] font-semibold inline-flex items-center gap-2 hover:bg-brandDark">
                {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Find
              </button>
            </div>
            {results.length > 0 && (
              <div className="mt-2 border border-border rounded-xl divide-y divide-border overflow-hidden">
                {results.map((r, i) => (
                  <button key={i} type="button" onClick={() => pick(r)} className="w-full text-left px-3 py-2 hover:bg-soft transition flex gap-2 items-start">
                    <MapPin size={14} className="text-brand mt-0.5 shrink-0" />
                    <span className="text-[12px] text-ink leading-snug">{r.display_name}<br /><span className="text-muted font-mono text-[10.5px]">{r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}</span></span>
                  </button>
                ))}
              </div>
            )}
            <p className="text-[10.5px] text-faint mt-1.5">Geocoding © OpenStreetMap contributors. If offline, type coordinates directly.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div><label className="block text-[12px] font-medium mb-1.5">Latitude *</label><input className={inp} value={lat} onChange={(e) => setLat(e.target.value)} placeholder="19.0760" inputMode="decimal" /></div>
            <div><label className="block text-[12px] font-medium mb-1.5">Longitude *</label><input className={inp} value={lon} onChange={(e) => setLon(e.target.value)} placeholder="72.8777" inputMode="decimal" /></div>
          </div>
          <div><label className="block text-[12px] font-medium mb-1.5">Place name</label><input className={inp} value={name} onChange={(e) => setName(e.target.value)} placeholder="City / region" /></div>
          <div>
            <label className="block text-[12px] font-medium mb-1.5">Confidence · <span className="text-brand font-semibold">{conf}%</span></label>
            <input type="range" min={5} max={95} value={conf} onChange={(e) => setConf(Number(e.target.value))} className="w-full accent-[#3E503C]" />
          </div>
          <div>
            <label className="block text-[12px] font-medium mb-1.5">Basis (why this location?)</label>
            <textarea className="w-full rounded-xl border border-border px-3 py-2 text-[13px] outline-none focus:ring-2 focus:ring-brand/15 min-h-[64px]" value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="e.g. Account profile states 'Mumbai'; post geotag visible in screenshot EV-02" />
          </div>
          {err && <p className="text-[12px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{err}</p>}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="flex-1 h-11 rounded-xl border border-border text-[13px] font-medium hover:bg-soft">Cancel</button>
            <button type="button" onClick={save} disabled={busy} className="flex-1 h-11 rounded-xl bg-brand text-white text-[13px] font-semibold hover:bg-brandDark disabled:opacity-60 inline-flex items-center justify-center gap-2">
              {busy && <Loader2 size={15} className="animate-spin" />} Save location
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
