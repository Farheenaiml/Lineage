import { createContext, useContext, useState, ReactNode, useCallback, useEffect } from "react";
import {
  api,
  Incident,
  MediaItem,
  DetectionResult,
  Fingerprint,
  Source,
  SourceRelationship,
  EvidenceItem,
  AttributionGapEntry,
  IncidentReport,
} from "../lib/api";

/**
 * Holds everything about the currently-open investigation, loaded from the
 * real backend. This is what replaced src/data/caseData.ts — every screen
 * that used to import fixed mock objects now reads from here instead.
 *
 * Each slice tracks its own loading/error state, because the pipeline stages
 * genuinely complete at different times: detection can be running while
 * sources are already loaded, and the UI should say so honestly rather than
 * showing everything at once the instant the page opens.
 */

type Slice<T> = { data: T; loading: boolean; error: string | null };
export type AnalysisStage = "creating" | "uploading" | "detection" | "fingerprinting" | "evidence" | "attribution" | "report" | "complete";

function emptySlice<T>(initial: T): Slice<T> {
  return { data: initial, loading: false, error: null };
}

type CaseState = {
  incidentId: string | null;
  setIncidentId: (id: string | null) => void;
  analysisStage: AnalysisStage | null;
  setAnalysisStage: (stage: AnalysisStage | null) => void;

  incident: Slice<Incident | null>;
  media: Slice<MediaItem | null>;
  detection: Slice<DetectionResult | null>;
  fingerprint: Slice<Fingerprint | null>;
  sources: Slice<Source[]>;
  relationships: Slice<SourceRelationship[]>;
  evidence: Slice<EvidenceItem[]>;
  attributionGap: Slice<AttributionGapEntry[]>;
  report: Slice<IncidentReport | null>;

  /** Actions — each updates the relevant slice and reloads what it affects. */
  uploadAndAnalyze: (file: File, overrideIncidentId?: string) => Promise<void>;
  addSource: (source: {
    platform: string; account_identifier?: string; url?: string;
    observed_at: string; similarity_score?: number; relationship_label?: string;
  }) => Promise<Source>;
  addRelationship: (fromSourceId: string, toSourceId: string, relationshipType: string, confidence?: number) => Promise<void>;
  generateGap: () => Promise<void>;
  generateReport: () => Promise<void>;
  refreshAll: () => Promise<void>;
};

const CaseContext = createContext<CaseState | null>(null);

export function CaseProvider({ children }: { children: ReactNode }) {
  const [incidentId, setIncidentId] = useState<string | null>(
    () => localStorage.getItem("lineage_active_incident")
  );
  const [analysisStage, setAnalysisStage] = useState<AnalysisStage | null>(null);

  const [incident, setIncident] = useState<Slice<Incident | null>>(emptySlice(null));
  const [media, setMedia] = useState<Slice<MediaItem | null>>(emptySlice(null));
  const [detection, setDetection] = useState<Slice<DetectionResult | null>>(emptySlice(null));
  const [fingerprint, setFingerprint] = useState<Slice<Fingerprint | null>>(emptySlice(null));
  const [sources, setSources] = useState<Slice<Source[]>>(emptySlice([]));
  const [relationships, setRelationships] = useState<Slice<SourceRelationship[]>>(emptySlice([]));
  const [evidence, setEvidence] = useState<Slice<EvidenceItem[]>>(emptySlice([]));
  const [attributionGap, setAttributionGap] = useState<Slice<AttributionGapEntry[]>>(emptySlice([]));
  const [report, setReport] = useState<Slice<IncidentReport | null>>(emptySlice(null));

  const updateIncidentId = useCallback((id: string | null) => {
    setIncidentId(id);
    if (id) localStorage.setItem("lineage_active_incident", id);
    else localStorage.removeItem("lineage_active_incident");
  }, []);

  const rebuildCaseOutputs = useCallback(async (id: string, setStage?: (stage: AnalysisStage) => void) => {
    setAttributionGap((s) => ({ ...s, loading: true, error: null }));
    try {
      const entries = await api.generateAttributionGap(id);
      setAttributionGap({ data: entries, loading: false, error: null });
    } catch (e: any) {
      setAttributionGap((s) => ({ ...s, loading: false, error: e?.message ?? "Attribution analysis failed." }));
    }

    setStage?.("report");
    setReport((s) => ({ ...s, loading: true, error: null }));
    try {
      const generatedReport = await api.generateReport(id);
      setReport({ data: generatedReport, loading: false, error: null });
    } catch (e: any) {
      setReport((s) => ({ ...s, loading: false, error: e?.message ?? "Report generation failed." }));
    }
  }, []);

  const refreshAll = useCallback(async () => {
    if (!incidentId) return;
    const id = incidentId;

    setIncident((s) => ({ ...s, loading: true, error: null }));
    setSources((s) => ({ ...s, loading: true, error: null }));
    setEvidence((s) => ({ ...s, loading: true, error: null }));
    setMedia((s) => ({ ...s, loading: true, error: null }));
    setDetection((s) => ({ ...s, loading: true, error: null }));
    setFingerprint((s) => ({ ...s, loading: true, error: null }));

    const settle = <T,>(
      p: Promise<T>,
      setter: (v: Slice<T>) => void,
      fallback: T
    ): Promise<T> =>
      p
        .then((data) => {
          setter({ data, loading: false, error: null });
          return data;
        })
        .catch((e) => {
          setter({
            data: fallback,
            loading: false,
            // A 404 here means "not generated yet", which is a normal state
            // in this pipeline, not a failure worth showing as an error.
            error: e?.status === 404 ? null : e?.message ?? "Failed to load.",
          });
          return fallback;
        });

    let latest: MediaItem | null = null;
    try {
      const mediaItems = await api.listMedia(id);
      latest = mediaItems[mediaItems.length - 1] ?? null;
      setMedia({ data: latest, loading: false, error: null });
    } catch (e: any) {
      setMedia({ data: null, loading: false, error: e?.status === 404 ? null : e?.message ?? "Failed to load." });
    }

    const [sourceItems, , evidenceItems, gapEntries, existingReport] = await Promise.all([
      settle(api.listSources(id), setSources, []),
      settle(api.listRelationships(id), setRelationships, []),
      settle(api.listEvidence(id), setEvidence, []),
      settle(api.getAttributionGap(id), setAttributionGap, []),
      settle<IncidentReport | null>(api.getReport(id), setReport, null),
    ]);

    const outputsNeedRefresh =
      latest &&
      sourceItems.some((source) => source.platform === "User upload") &&
      (!gapEntries.length ||
        !existingReport ||
        existingReport.payload.source_count !== sourceItems.length ||
        existingReport.payload.evidence_count !== evidenceItems.length);
    if (outputsNeedRefresh) await rebuildCaseOutputs(id);

    try {
      const updated = await api.getIncident(id);
      setIncident({ data: updated, loading: false, error: null });
    } catch (e: any) {
      setIncident((s) => ({ ...s, loading: false, error: e?.message ?? "Failed to load investigation." }));
    }

    if (latest) {
      await Promise.all([
        settle(api.getDetection(id, latest.id), setDetection, null),
        settle(api.getFingerprint(id, latest.id), setFingerprint, null),
      ]);
    } else {
      setDetection({ data: null, loading: false, error: null });
      setFingerprint({ data: null, loading: false, error: null });
    }
  }, [incidentId, rebuildCaseOutputs]);

  useEffect(() => {
    if (incidentId) refreshAll();
  }, [incidentId, refreshAll]);

  const uploadAndAnalyze = useCallback(
    async (file: File, overrideIncidentId?: string) => {
      // `overrideIncidentId` exists because NewInvestigation creates an
      // incident and uploads to it in the same handler: the setIncidentId
      // state update isn't visible in this closure yet, so the caller passes
      // the id it just received directly.
      const id = overrideIncidentId ?? incidentId;
      if (!id) throw new Error("No active investigation.");

      setAnalysisStage("uploading");
      setMedia({ data: null, loading: true, error: null });
      setDetection({ data: null, loading: true, error: null });
      setFingerprint({ data: null, loading: true, error: null });

      try {
        const uploaded = await api.uploadMedia(id, file);
        setMedia({ data: uploaded, loading: false, error: null });

        // Detection and fingerprinting run SEQUENTIALLY, not in parallel.
        // Both load ML models on first use, and firing them concurrently
        // makes them contend while each lazily initialises its model —
        // in testing that turned a ~14s sequential run into an apparent
        // hang. Each result is still surfaced the moment it lands, so the
        // UI fills in progressively rather than waiting for both.
        try {
          setAnalysisStage("detection");
          const d = await api.runDetection(id, uploaded.id);
          setDetection({ data: d, loading: false, error: null });
        } catch (e: any) {
          setDetection({ data: null, loading: false, error: e?.message ?? "Detection failed." });
        }

        try {
          setAnalysisStage("fingerprinting");
          const f = await api.runFingerprint(id, uploaded.id);
          setFingerprint({ data: f, loading: false, error: null });
        } catch (e: any) {
          setFingerprint({ data: null, loading: false, error: e?.message ?? "Fingerprinting failed." });
        }

        // Uploads are recorded as a source and evidence item on the backend.
        // Load them before deriving the attribution gap and report.
        try {
          setAnalysisStage("evidence");
          const [sourceItems, evidenceItems] = await Promise.all([
            api.listSources(id),
            api.listEvidence(id),
          ]);
          setSources({ data: sourceItems, loading: false, error: null });
          setEvidence({ data: evidenceItems, loading: false, error: null });
        } catch (e: any) {
          const message = e?.message ?? "Could not refresh case evidence.";
          setSources((s) => ({ ...s, loading: false, error: message }));
          setEvidence((s) => ({ ...s, loading: false, error: message }));
        }

        setAnalysisStage("attribution");
        await rebuildCaseOutputs(id, setAnalysisStage);
        setAnalysisStage("report");

        // All available pipeline stages have run server-side; refresh the
        // incident so the stage tracker reflects the final persisted state.
        try {
          const updated = await api.getIncident(id);
          setIncident({ data: updated, loading: false, error: null });
        } catch { /* non-fatal */ }
        setAnalysisStage("complete");
      } catch (e: any) {
        const message = e?.message ?? "Upload failed.";
        setMedia({ data: null, loading: false, error: message });
        setDetection({ data: null, loading: false, error: null });
        setFingerprint({ data: null, loading: false, error: null });
        throw e;
      } finally {
        window.setTimeout(() => setAnalysisStage(null), 2500);
      }
    },
    [incidentId, rebuildCaseOutputs]
  );

  const addSource = useCallback(
    async (source: {
      platform: string; account_identifier?: string; url?: string;
      observed_at: string; similarity_score?: number; relationship_label?: string;
    }) => {
      if (!incidentId) throw new Error("No active investigation.");
      const created = await api.addSource(incidentId, source);
      const updatedSources = await api.listSources(incidentId);
      setSources({ data: updatedSources, loading: false, error: null });
      const updatedEvidence = await api.listEvidence(incidentId);
      setEvidence({ data: updatedEvidence, loading: false, error: null });
      await rebuildCaseOutputs(incidentId);
      const updatedIncident = await api.getIncident(incidentId);
      setIncident({ data: updatedIncident, loading: false, error: null });
      return created;
    },
    [incidentId, rebuildCaseOutputs]
  );

  const addRelationship = useCallback(
    async (fromSourceId: string, toSourceId: string, relationshipType: string, confidence?: number) => {
      if (!incidentId) throw new Error("No active investigation.");
      await api.addRelationship(incidentId, {
        from_source_id: fromSourceId,
        to_source_id: toSourceId,
        relationship_type: relationshipType,
        confidence,
      });
      const updatedRels = await api.listRelationships(incidentId);
      setRelationships({ data: updatedRels, loading: false, error: null });
    },
    [incidentId]
  );

  const generateGap = useCallback(async () => {
    if (!incidentId) throw new Error("No active investigation.");
    setAttributionGap((s) => ({ ...s, loading: true, error: null }));
    try {
      const entries = await api.generateAttributionGap(incidentId);
      setAttributionGap({ data: entries, loading: false, error: null });
      const updated = await api.getIncident(incidentId);
      setIncident({ data: updated, loading: false, error: null });
    } catch (e: any) {
      setAttributionGap((s) => ({ ...s, loading: false, error: e?.message ?? "Failed to generate." }));
      throw e;
    }
  }, [incidentId]);

  const generateReport = useCallback(async () => {
    if (!incidentId) throw new Error("No active investigation.");
    setReport((s) => ({ ...s, loading: true, error: null }));
    try {
      const r = await api.generateReport(incidentId);
      setReport({ data: r, loading: false, error: null });
      const updated = await api.getIncident(incidentId);
      setIncident({ data: updated, loading: false, error: null });
    } catch (e: any) {
      setReport((s) => ({ ...s, loading: false, error: e?.message ?? "Failed to generate report." }));
      throw e;
    }
  }, [incidentId]);

  return (
    <CaseContext.Provider
      value={{
        incidentId,
        setIncidentId: updateIncidentId,
        analysisStage,
        setAnalysisStage,
        incident,
        media,
        detection,
        fingerprint,
        sources,
        relationships,
        evidence,
        attributionGap,
        report,
        uploadAndAnalyze,
        addSource,
        addRelationship,
        generateGap,
        generateReport,
        refreshAll,
      }}
    >
      {children}
    </CaseContext.Provider>
  );
}

export function useCase() {
  const ctx = useContext(CaseContext);
  if (!ctx) throw new Error("useCase must be used within CaseProvider");
  return ctx;
}
