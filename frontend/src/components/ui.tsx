import { ReactNode } from "react";
import { Check, CircleAlert, Info, ArrowRight } from "lucide-react";

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`bg-card border border-border rounded-2xl shadow-card ${className}`}>{children}</div>;
}

export function PanelHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-5">
      <div>
        <h2 className="text-[18px] font-semibold tracking-[-.02em] text-ink">{title}</h2>
        {subtitle && <p className="text-[13px] text-muted mt-1.5 leading-relaxed">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function StatusBadge({ children, tone = "amber" }: { children: ReactNode; tone?: "green"|"amber"|"blue"|"red"|"gray" }) {
  const styles = {
    green: "bg-soft text-brand",
    amber: "bg-amber text-[#78571A]",
    blue: "bg-blue text-[#3B5A7D]",
    red: "bg-red text-[#8A4138]",
    gray: "bg-[#EEF0ED] text-muted",
  };
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium ${styles[tone]}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{children}</span>;
}


export function StatCard({ label, value, sub, icon: Icon }: { label: string; value: string; sub?: string; icon?: any }) {
  return (
    <div className="bg-card border border-border rounded-2xl p-5 shadow-card">
      <div className="flex items-start justify-between">
        {Icon && <div className="h-10 w-10 rounded-xl bg-soft flex items-center justify-center text-brand"><Icon size={20} strokeWidth={1.7}/></div>}
      </div>
      <p className="text-[12px] text-muted mt-4">{label}</p>
      <p className="text-[28px] leading-none font-semibold mt-1.5 text-ink">{value}</p>
      {sub && <p className="text-[11.5px] text-muted mt-2">{sub}</p>}
    </div>
  );
}

export function ConfidenceBar({ value, label, tone = "green", note }: { value: number; label: string; tone?: "green"|"amber"|"red"|"blue"; note?: string }) {
  const bar = { green: "bg-brand", amber: "bg-[#C79B42]", red: "bg-[#B96255]", blue: "bg-[#6585A8]" }[tone];
  return <div className="mb-4 last:mb-0">
    <div className="flex items-center justify-between mb-2"><span className="text-[13px] text-ink">{label}</span><span className="text-[12px] font-medium text-muted">{note || `${value}%`}</span></div>
    <div className="h-2 bg-[#EEF1ED] rounded-full overflow-hidden"><div className={`h-full ${bar} rounded-full transition-all duration-700`} style={{width:`${Math.max(0,Math.min(100,value))}%`}} /></div>
  </div>;
}

export function StageTracker({ stages }: { stages: {key:string;label:string;done:boolean;current?:boolean}[] }) {
  return <div className="flex items-start w-full overflow-x-auto pb-2">
    {stages.map((s,i)=><div key={s.key} className="flex items-start min-w-[120px] flex-1">
      <div className="flex flex-col items-center min-w-[34px]">
        <div className={`h-8 w-8 rounded-full flex items-center justify-center border ${s.done ? "bg-brand border-brand text-white" : s.current ? "bg-amber border-[#D4AE62] text-[#76591E]" : "bg-white border-border text-faint"}`}>
          {s.done ? <Check size={15}/> : <span className="text-[11px]">{i+1}</span>}
        </div>
        <span className={`text-[11px] mt-2 text-center leading-tight ${s.done || s.current ? "text-ink font-medium" : "text-faint"}`}>{s.label}</span>
      </div>
      {i<stages.length-1 && <div className={`h-px flex-1 mt-4 mx-1 ${s.done && stages[i+1].done ? "bg-brand" : "bg-border"}`} />}
    </div>)}
  </div>;
}

export function EmptyState({ title, description, action }: { title:string; description:string; action?:ReactNode }) {
  return <div className="py-14 text-center"><div className="mx-auto h-12 w-12 rounded-full bg-soft text-brand flex items-center justify-center"><Info size={20}/></div><h3 className="mt-4 text-[16px] font-semibold">{title}</h3><p className="max-w-md mx-auto text-[13px] text-muted mt-2">{description}</p>{action && <div className="mt-5">{action}</div>}</div>;
}

export function Notice({ children, tone="info" }: {children:ReactNode; tone?: "info"|"warning"|"success"}) {
  const styles = {info:"bg-blue text-[#3B5A7D]",warning:"bg-red text-[#8A4138]",success:"bg-soft text-brand"};
  return <div className={`rounded-2xl p-4 flex gap-3 text-[12.5px] leading-relaxed ${styles[tone]}`}><CircleAlert size={17} className="shrink-0 mt-0.5"/><div>{children}</div></div>;
}

export function SectionTitle({ eyebrow, title, description }: {eyebrow?:string;title:string;description?:string}) {
  return <div className="mb-6">{eyebrow && <p className="text-[11px] tracking-[.16em] uppercase text-brand font-semibold mb-2">{eyebrow}</p>}<h1 className="font-display text-[34px] md:text-[40px] leading-tight tracking-[-.03em] text-ink">{title}</h1>{description && <p className="text-[14px] text-muted mt-3 max-w-2xl leading-relaxed">{description}</p>}</div>;
}

export function PrimaryButton({children,onClick,className="",type="button"}:{children:ReactNode;onClick?:()=>void;className?:string;type?:"button"|"submit"}) {
  return <button type={type} onClick={onClick} className={`inline-flex items-center justify-center gap-2 rounded-xl bg-brand text-white px-5 py-3 text-[13px] font-semibold hover:bg-brandDark transition-all shadow-sm ${className}`}>{children}<ArrowRight size={15}/></button>;
}
