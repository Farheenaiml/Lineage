import { useCallback, useEffect, useState } from "react";
import { ClipboardList, Clock, FileDown, FileText, Link2, MapPin, ShieldAlert, History, CheckCircle2, Brain, RefreshCw, Pencil, Save } from "lucide-react";
import { api, AlertDraft, AuditEventT, CaseSummary, ReportRecord, SummaryFact, TimelineEvent, WorkflowInfo } from "../lib/api";
import { useCase } from "../context/CaseContext";
import { setLineageFocus } from "../lib/focus";
import { Panel, PanelHeader, StatusBadge } from "../components/ui";
import { ScreenKey } from "../components/Sidebar";

/**
 * Phase 5 — Investigation Automation. Summary, evidence gaps, timeline, report, reviewable alert draft, export,
 * investigator-controlled status and audit trail — all built server-side from stored records. Nothing here is ever
 * sent outside LINEAGE; approving a draft only records the investigator's decision.
 */
const chip = "inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-[11px] font-medium text-ink hover:border-brand hover:text-brand transition disabled:opacity-50";
const btn = "inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-3 h-9 text-[12px] font-semibold text-ink hover:border-brand hover:text-brand transition disabled:opacity-50";
const primary = "inline-flex items-center gap-1.5 rounded-xl bg-brand text-white px-4 h-9 text-[12px] font-semibold hover:bg-brandDark transition disabled:opacity-50";
const BASIS_TONE: Record<string, "green" | "blue" | "amber" | "gray"> = { OBSERVED: "green", RECORDED: "blue", CONFIRMED: "green", INFERRED: "amber", UNKNOWN: "gray" };
const CAT_TONE: Record<string, "green" | "amber" | "gray"> = { VERIFIED_FACT: "green", INFERENCE: "amber", UNKNOWN: "gray" };

function fmt(iso: string | null | undefined) {
  if (!iso) return "time not recorded";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function CaseAutomation({ onNavigate }: { onNavigate: (k: ScreenKey) => void }) {
  const { incidentId } = useCase();
  const [summary, setSummary] = useState<CaseSummary | null>(null);
  const [timeline, setTimeline] = useState<{ events: TimelineEvent[]; undated: TimelineEvent[] } | null>(null);
  const [workflow, setWorkflow] = useState<WorkflowInfo | null>(null);
  const [nextState, setNextState] = useState("");
  const [report, setReport] = useState<ReportRecord | null>(null);
  const [drafts, setDrafts] = useState<AlertDraft[]>([]);
  const [draftEdit, setDraftEdit] = useState<{ id: string; summary_text: string; request_text: string } | null>(null);
  const [draftMissing, setDraftMissing] = useState<string[] | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEventT[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});

  const refreshAudit = useCallback(async () => {
    if (incidentId) setAuditEvents((await api.getAudit(incidentId)).events);
  }, [incidentId]);

  const load = useCallback(async () => {
    if (!incidentId) return;
    setBusy("load"); setErr(null);
    try {
      const [s, t, w, d] = await Promise.all([api.getCaseSummary(incidentId), api.getTimeline(incidentId), api.getWorkflow(incidentId), api.listAlertDrafts(incidentId)]);
      setSummary(s); setTimeline(t); setWorkflow(w); setNextState(w.state); setDrafts(d);
      try { setReport(await api.getLatestInvestigationReport(incidentId)); } catch { setReport(null); }
      await refreshAudit();
    } catch (e: any) { setErr(e?.message ?? "Could not load the case automation data."); }
    finally { setBusy(null); }
  }, [incidentId, refreshAudit]);
  useEffect(() => { load(); }, [load]);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label); setErr(null);
    try { await fn(); await refreshAudit(); } catch (e: any) { setErr(e?.message ?? "Action failed."); } finally { setBusy(null); }
  }

  const openSource = (sourceId: string) => { setLineageFocus({ tab: "graph", sourceId }); onNavigate("lineage"); };
  const openLocation = (mapNodeId: string) => { setLineageFocus({ tab: "map", mapNodeId }); onNavigate("lineage"); };
  const openML = () => { setLineageFocus({ tab: "ml" }); onNavigate("lineage"); };
  const openEvidence = () => onNavigate("evidence");

  const factLinks = (f: SummaryFact) => (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {f.source_ids.map((s) => <button key={s} className={chip} onClick={() => openSource(s)}><Link2 size={11} /> {summary?.sources.find((x) => x.source_id === s)?.code ?? s.slice(0, 8)}</button>)}
      {f.location_ids.map((l) => <button key={l} className={chip} onClick={() => openLocation(l.replace(/^location:/, ""))}><MapPin size={11} /> location</button>)}
      {f.evidence_ids.length > 0 && <button className={chip} onClick={openEvidence}><FileText size={11} /> {f.evidence_ids.map((e) => summary?.evidence.find((x) => x.evidence_id === e)?.code ?? e.slice(0, 8)).join(", ")}</button>}
    </div>
  );

  if (!summary) {
    return <Panel className="p-6"><p className="text-[13px] text-muted">{busy ? "Building the case summary…" : err ?? "No data."}</p></Panel>;
  }
  const draft = drafts[0];

  return (
    <div className="space-y-5">
      {/* Status + export */}
      <Panel className="p-5 sm:p-6">
        <PanelHeader
          title="Case Automation"
          subtitle="Summary, evidence gaps, timeline, report and alert draft generated from recorded evidence. Every item links back to its source record."
          right={<button className={btn} onClick={load} disabled={!!busy}><RefreshCw size={13} className={busy === "load" ? "animate-spin" : ""} /> Refresh</button>}
        />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <p className="text-[11px] text-muted mb-1">Investigation status (investigator-controlled)</p>
            <div className="flex gap-2">
              <select value={nextState} onChange={(e) => setNextState(e.target.value)}
                className="h-9 rounded-xl border border-border bg-white px-3 text-[12px] font-medium text-ink">
                {workflow?.states.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
              <button className={primary} disabled={!!busy || !workflow || nextState === workflow.state}
                onClick={() => run("status", async () => { setWorkflow(await api.setWorkflow(incidentId!, nextState)); })}>Set status</button>
            </div>
            <p className="text-[10.5px] text-faint mt-1">Current: {workflow?.label}. ML analysis never changes this status.</p>
          </div>
          <div className="flex gap-2 ml-auto">
            <button className={btn} disabled={!!busy} onClick={() => run("export", () => api.exportInvestigation(incidentId!, "json"))}><FileDown size={13} /> Export JSON</button>
            <button className={btn} disabled={!!busy} onClick={() => run("export", () => api.exportInvestigation(incidentId!, "pdf"))}><FileDown size={13} /> Export PDF</button>
          </div>
        </div>
        {err && <p className="mt-3 text-[12.5px] text-[#8A4138]">{err}</p>}
      </Panel>

      <div className="grid xl:grid-cols-[1fr_380px] gap-5">
        <div className="space-y-5">
          {/* Summary */}
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Case summary" subtitle={`Graph: ${summary.graph_source.backend === "neo4j" ? "Neo4j" : "in-memory fallback"} · generated ${fmt(summary.generated_at)}`} />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12px]">
              {[["Media", summary.media.length], ["Sources", summary.sources.length], ["Evidence", summary.evidence.length], ["Locations", summary.locations.length]].map(([k, v]) => (
                <div key={k as string} className="rounded-xl bg-soft/60 p-3"><p className="text-muted">{k}</p><p className="text-[18px] font-semibold text-ink">{v}</p></div>
              ))}
            </div>
            <div className="mt-4 space-y-1 text-[12px] text-ink">
              {summary.media.map((m) => m.detections.map((d) => (
                <p key={d.detection_id}>Detection on '{m.filename}': <b>{d.model_name}</b> {d.manipulation_likelihood != null ? `${d.manipulation_likelihood.toFixed(0)}%` : "not recorded"} — <span className="text-muted">{d.note}</span></p>
              )))}
              <p>Platforms: {summary.platforms.map((p) => `${p.platform} (${p.source_count})`).join(", ") || "none recorded"}</p>
              <p>Propagation: {summary.propagation.relationships.map((r) => `${r.from} ${r.type === "PROPAGATES_TO" ? "→" : "—"} ${r.to} (${r.status})`).join("; ") || "no relationship recorded"}</p>
            </div>
            {([["Verified / recorded facts", summary.verified_facts], ["Inferences", summary.inferences], ["Unknown", summary.unknowns]] as const).map(([title, facts]) => (
              <div key={title} className="mt-5">
                <p className="text-[12.5px] font-semibold text-ink mb-2">{title} ({facts.length})</p>
                <div className="space-y-2">
                  {facts.length === 0 && <p className="text-[12px] text-muted">None.</p>}
                  {facts.map((f, i) => (
                    <div key={i} className="rounded-xl border border-border/70 p-3">
                      <div className="flex gap-2 items-start"><StatusBadge tone={CAT_TONE[f.category] ?? "gray"}>{f.status ?? f.category}</StatusBadge></div>
                      <p className="text-[12px] text-ink mt-1.5">{f.statement}</p>
                      {factLinks(f)}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </Panel>

          {/* ML findings */}
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="ML findings" subtitle="Analysis, not fact. Open ML Intelligence for factors and links." right={<button className={btn} onClick={openML}><Brain size={13} /> ML Intelligence</button>} />
            {(["similarity", "anomalies", "clusters"] as const).map((k) => {
              const a = summary.ml_findings[k];
              return (
                <div key={k} className="mb-3 last:mb-0">
                  <p className="text-[12px] font-semibold text-ink capitalize">{k} <span className="text-faint font-mono font-normal">· {a.model_name} v{a.model_version} · {fmt(a.computed_at)}</span></p>
                  {a.results.length === 0 ? <p className="text-[12px] text-muted">{a.message ?? "No results."}</p> : a.results.map((r) => (
                    <p key={r.id} className="text-[12px] text-ink mt-1">[{r.score.toFixed(2)}] {r.explanation} {r.reviewed && <span className="text-brand">(reviewed by {r.reviewed.by})</span>}</p>
                  ))}
                </div>
              );
            })}
          </Panel>

          {/* Timeline */}
          <Panel className="p-5 sm:p-6">
            <PanelHeader title="Investigation timeline" subtitle="Only stored timestamps are used. OBSERVED and INFERRED events are labelled separately." />
            <div className="space-y-2.5 border-l-2 border-border/60 ml-2 pl-4">
              {timeline?.events.map((e, i) => (
                <div key={i} className="relative">
                  <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full bg-brand ring-4 ring-card" />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-mono text-muted"><Clock size={11} className="inline mr-1" />{fmt(e.timestamp)}</span>
                    <StatusBadge tone={BASIS_TONE[e.basis]}>{e.basis}</StatusBadge>
                  </div>
                  <p className="text-[12px] text-ink mt-1">{e.event}</p>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {e.source && <button className={chip} onClick={() => openSource(e.source!.source_id)}><Link2 size={11} /> {e.source.code}{e.platform ? ` · ${e.platform}` : ""}</button>}
                    {e.location?.map_node_id && <button className={chip} onClick={() => openLocation(e.location!.map_node_id!)}><MapPin size={11} /> {e.location.label} ({e.location.status.replace("_", " ")})</button>}
                    {e.evidence_ids.length > 0 && <button className={chip} onClick={openEvidence}><FileText size={11} /> {e.evidence_ids.length} evidence</button>}
                  </div>
                </div>
              ))}
            </div>
            {timeline && timeline.undated.length > 0 && (
              <p className="text-[11.5px] text-muted mt-4">Undated (no stored timestamp, not placed on the timeline): {timeline.undated.map((u) => u.event).join("; ")}</p>
            )}
          </Panel>
        </div>

        <div className="space-y-5">
          {/* Gaps */}
          <Panel className="p-5">
            <PanelHeader title={`Evidence gaps (${summary.evidence_gaps.length})`} subtitle="Missing information is listed, never filled." />
            <ul className="space-y-2">
              {summary.evidence_gaps.map((g) => (
                <li key={g.id} className="text-[11.5px] text-ink">
                  <span className="text-faint font-mono">{g.kind.replace(/_/g, " ")}</span><br />{g.gap}
                  <div className="flex gap-1.5 mt-1">
                    {g.node_ids.filter((n) => n.startsWith("source:")).map((n) => <button key={n} className={chip} onClick={() => openSource(n.slice(7))}><Link2 size={11} /> source</button>)}
                    <button className={chip} disabled={reviewed[g.id]} onClick={() => run("review", async () => {
                      await api.recordReview(incidentId!, g.finding_id ? "ml_finding" : "gap", g.finding_id ?? g.id); setReviewed((r) => ({ ...r, [g.id]: true }));
                    })}><CheckCircle2 size={11} /> {reviewed[g.id] ? "Reviewed" : "Mark reviewed"}</button>
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          {/* Report */}
          <Panel className="p-5">
            <PanelHeader title="Investigation report" right={<button className={primary} disabled={!!busy} onClick={() => run("report", async () => setReport(await api.generateInvestigationReport(incidentId!)))}><ClipboardList size={13} /> {report ? "New version" : "Generate"}</button>} />
            {!report ? <p className="text-[12px] text-muted">No report generated yet.</p> : (<>
              <p className="text-[12px] text-ink">Version {report.version} · {fmt(report.generated_at)}</p>
              <button className={`${btn} mt-2`} onClick={() => run("pdf", () => api.downloadInvestigationReportPdf(incidentId!, report.id, report.version))}><FileDown size={13} /> Download PDF</button>
              <p className="text-[12px] font-semibold text-ink mt-4 mb-1">Recommended investigation actions</p>
              <ul className="space-y-1.5">{report.report.recommended_actions.map((a, i) => <li key={i} className="text-[11.5px] text-ink">• {a.action}</li>)}</ul>
              <p className="text-[10.5px] text-faint mt-3">{report.report.disclaimer}</p>
            </>)}
          </Panel>

          {/* Alert draft */}
          <Panel className="p-5">
            <PanelHeader title="Cyber-department alert draft" right={<button className={btn} disabled={!!busy} onClick={() => run("draft", async () => {
              setDraftMissing(null);
              try { const d = await api.createAlertDraft(incidentId!); setDrafts((x) => [d, ...x]); }
              catch (e: any) { try { setDraftMissing(JSON.parse(e.message).missing); } catch { throw e; } }
            })}><ShieldAlert size={13} /> Generate draft</button>} />
            {draftMissing && <div className="rounded-xl bg-red p-3 text-[11.5px] text-[#8A4138]"><b>Insufficient evidence for an alert draft.</b><ul>{draftMissing.map((m) => <li key={m}>• {m}</li>)}</ul></div>}
            {!draft ? !draftMissing && <p className="text-[12px] text-muted">No draft yet. Drafts are never sent automatically.</p> : (
              <div className="space-y-2">
                <div className="rounded-xl border-2 border-[#B96255] bg-red/60 px-3 py-2 text-center text-[12.5px] font-bold text-[#8A4138] tracking-wide">{draft.banner}</div>
                <p className="text-[11px] text-muted">{draft.status === "approved" ? `Approved by ${draft.approved_by_email} on ${fmt(draft.approved_at)} — not sent.` : "Status: draft — awaiting investigator approval."} {draft.content.transmission}</p>
                {draftEdit?.id === draft.id ? (<>
                  <textarea value={draftEdit.summary_text} onChange={(e) => setDraftEdit({ ...draftEdit, summary_text: e.target.value })} rows={4} className="w-full rounded-xl border border-border p-2 text-[12px]" />
                  <textarea value={draftEdit.request_text} onChange={(e) => setDraftEdit({ ...draftEdit, request_text: e.target.value })} rows={3} className="w-full rounded-xl border border-border p-2 text-[12px]" />
                  <button className={primary} onClick={() => run("draft", async () => {
                    const d = await api.editAlertDraft(incidentId!, draft.id, { summary_text: draftEdit.summary_text, request_text: draftEdit.request_text });
                    setDrafts((x) => [d, ...x.slice(1)]); setDraftEdit(null);
                  })}><Save size={13} /> Save</button>
                </>) : (<>
                  <p className="text-[12px] text-ink">{draft.summary_text}</p>
                  <p className="text-[12px] text-ink"><b>Request:</b> {draft.request_text}</p>
                </>)}
                <p className="text-[11px] text-muted">Platforms: {draft.content.observed_platforms.join(", ")} · Evidence: {draft.content.evidence_references.map((e) => e.code).join(", ")} · Timeline events: {draft.content.timeline.length}</p>
                <div className="flex flex-wrap gap-2 pt-1">
                  <button className={btn} onClick={() => setDraftEdit({ id: draft.id, summary_text: draft.summary_text, request_text: draft.request_text })}><Pencil size={13} /> Edit</button>
                  <button className={primary} disabled={draft.status === "approved" || !!busy} onClick={() => run("draft", async () => {
                    const d = await api.approveAlertDraft(incidentId!, draft.id); setDrafts((x) => [d, ...x.slice(1)]);
                  })}><CheckCircle2 size={13} /> Approve</button>
                  <button className={btn} onClick={() => run("draft", () => api.exportAlertDraft(incidentId!, draft.id, "json"))}><FileDown size={13} /> Export JSON</button>
                  <button className={btn} onClick={() => run("draft", () => api.exportAlertDraft(incidentId!, draft.id, "pdf"))}><FileDown size={13} /> Export PDF</button>
                </div>
              </div>
            )}
          </Panel>

          {/* Audit */}
          <Panel className="p-5">
            <PanelHeader title="Audit trail" />
            {auditEvents.length === 0 ? <p className="text-[12px] text-muted">No recorded actions yet.</p> : (
              <ul className="space-y-1.5 max-h-[360px] overflow-y-auto">
                {[...auditEvents].reverse().map((e) => (
                  <li key={e.id} className="text-[11px] text-ink"><History size={11} className="inline mr-1 text-faint" />
                    <span className="font-mono text-muted">{fmt(e.created_at)}</span> · <b>{e.action.replace(/_/g, " ")}</b>{e.target_type ? ` (${e.target_type})` : ""} · {e.actor?.email ?? "system"}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
