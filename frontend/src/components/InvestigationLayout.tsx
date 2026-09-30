import { ReactNode } from "react";
import { motion } from "framer-motion";
import { StatusBadge } from "./ui";
import { useCase } from "../context/CaseContext";
import { statusLabel } from "../lib/pipeline";
import { ScreenKey } from "./Sidebar";

export interface InvestigationLayoutProps {
  activeTab: ScreenKey;
  onNavigate: (key: ScreenKey) => void;
  children: ReactNode;
}

const tabs: { key: ScreenKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "detection", label: "Detection Analysis" },
  { key: "fingerprint", label: "Fingerprinting" },
  { key: "evidence", label: "Evidence Locker" },
  { key: "lineage", label: "Lineage / Propagation" },
  { key: "gap", label: "Attribution Gap" },
  { key: "report", label: "Incident Report" },
  { key: "automation", label: "Case Automation" },
];

function formatDate(iso: string | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function relativeTime(iso: string | undefined) {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export default function InvestigationLayout({ activeTab, onNavigate, children }: InvestigationLayoutProps) {
  const { incident } = useCase();
  const c = incident.data;
  return (
    <div className="max-w-[1400px] mx-auto space-y-6">
      {/* Persistent Case Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-1 border-b border-border/50">
        <div>
          <button
            onClick={() => onNavigate("dashboard")}
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted hover:text-brand transition-colors mb-2.5"
          >
            <span className="text-base leading-none">←</span> Back to Investigations
          </button>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-3xl sm:text-4xl tracking-[-.03em] text-ink font-semibold">
              {incident.loading && !c ? "Loading…" : c?.title ?? "No investigation selected"}
            </h1>
            <span className="rounded-full bg-[#EEF1ED] px-3 py-1 text-[11.5px] font-mono font-medium text-ink/80 border border-border/60">
              {c ? c.id.slice(0, 8).toUpperCase() : "—"}
            </span>
          </div>
          <p className="text-[12.5px] text-muted mt-1.5 flex flex-wrap items-center gap-2">
            <span>Created {formatDate(c?.created_at)}</span>
            <span>•</span>
            <span>Last updated {relativeTime(c?.updated_at)}</span>
          </p>
        </div>

        <div className="shrink-0 self-start sm:self-end mb-1">
          <StatusBadge tone="amber">{statusLabel(c?.status)}</StatusBadge>
        </div>
      </div>

      {/* Persistent Horizontal Tabs Navigation */}
      <div className="border-b border-border overflow-x-auto no-scrollbar scroll-smooth">
        <nav className="flex gap-1 min-w-max pb-px" aria-label="Investigation tabs">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => onNavigate(tab.key)}
                className={`relative px-4 py-3 text-[13px] font-medium transition-all duration-150 border-b-2 whitespace-nowrap rounded-t-lg ${
                  isActive
                    ? "border-brand text-brand font-semibold bg-soft/30"
                    : "border-transparent text-muted hover:text-ink hover:bg-soft/20"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Active Tab View */}
      <motion.div
        key={activeTab}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="pt-1"
      >
        {children}
      </motion.div>
    </div>
  );
}
