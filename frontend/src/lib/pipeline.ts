import { IncidentStatus } from "./api";

/**
 * The real Incident state machine from the Project Flow document, in order.
 * The StageTracker in the UI derives its completed/pending state from the
 * incident's actual `status` field via this list — it is no longer a
 * hardcoded array of "everything is done".
 */
export const PIPELINE_STAGES: { key: IncidentStatus; label: string }[] = [
  { key: "created", label: "Created" },
  { key: "analyzing", label: "Analyzing" },
  { key: "fingerprinted", label: "Fingerprinted" },
  { key: "evidence_building", label: "Evidence Building" },
  { key: "gap_reviewed", label: "Gap Reviewed" },
  { key: "report_generated", label: "Report Generated" },
  { key: "closed", label: "Closed / Archived" },
];

export function stageIndex(status: IncidentStatus | undefined): number {
  if (!status) return -1;
  return PIPELINE_STAGES.findIndex((s) => s.key === status);
}

export function stagesWithProgress(status: IncidentStatus | undefined) {
  const current = stageIndex(status);
  return PIPELINE_STAGES.map((stage, i) => ({
    ...stage,
    done: current >= 0 && i <= current,
    current: i === current,
  }));
}

export function statusLabel(status: IncidentStatus | undefined): string {
  if (!status) return "Unknown";
  return PIPELINE_STAGES.find((s) => s.key === status)?.label ?? status;
}
