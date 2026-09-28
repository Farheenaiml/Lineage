import { Loader2, AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { ReactNode } from "react";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 justify-center text-muted">
      <Loader2 size={18} className="animate-spin" />
      <span className="text-[13px]">{label}</span>
    </div>
  );
}

export function InlineLoading({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-muted text-[12.5px]">
      <Loader2 size={13} className="animate-spin" />
      {label}
    </span>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="border border-red-300 bg-red-50 rounded-lg p-4 flex items-start gap-3">
      <AlertTriangle size={16} className="text-red-600 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-[13px] text-red-900 font-medium">Something went wrong</p>
        <p className="text-[12.5px] text-red-800 mt-0.5 break-words">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 inline-flex items-center gap-1.5 text-[12px] text-red-900 underline"
          >
            <RefreshCw size={12} /> Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="border border-dashed border-border rounded-lg p-8 text-center">
      <Inbox size={22} className="text-faint mx-auto mb-3" />
      <p className="text-[13.5px] text-ink">{title}</p>
      {detail && <p className="text-[12.5px] text-muted mt-1 max-w-md mx-auto">{detail}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * Wraps the three states so screens don't each re-implement the same
 * branching. `empty` renders when the request succeeded but returned nothing.
 */
export function AsyncBlock({
  loading,
  error,
  isEmpty,
  empty,
  onRetry,
  loadingLabel,
  children,
}: {
  loading: boolean;
  error: string | null;
  isEmpty?: boolean;
  empty?: ReactNode;
  onRetry?: () => void;
  loadingLabel?: string;
  children: ReactNode;
}) {
  if (loading) return <LoadingState label={loadingLabel} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (isEmpty && empty) return <>{empty}</>;
  return <>{children}</>;
}
