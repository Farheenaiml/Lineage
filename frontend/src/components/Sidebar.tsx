import {
  LayoutDashboard,
  FolderOpen,
  Plus,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Map,
  X,
} from "lucide-react";

export type ScreenKey =
  | "dashboard"
  | "investigations"
  | "new"
  | "overview"
  | "detection"
  | "fingerprint"
  | "evidence"
  | "lineage"
  | "gap"
  | "report"
  | "roadmap"
  | "settings";

export default function Sidebar({
  active,
  onSelect,
  collapsed,
  setCollapsed,
  mobileOpen = false,
  onCloseMobile,
}: {
  active: ScreenKey;
  onSelect: (k: ScreenKey) => void;
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  /** Whether the off-canvas drawer is open on small/medium screens. */
  mobileOpen?: boolean;
  /** Called to close the drawer (backdrop tap, nav select, Esc). */
  onCloseMobile?: () => void;
}) {
  const select = (k: ScreenKey) => {
    onSelect(k);
    onCloseMobile?.();
  };

  const Item = ({ k, label, Icon }: { k: ScreenKey; label: string; Icon: any }) => {
    const isActive = active === k;
    return (
      <button
        onClick={() => select(k)}
        title={collapsed ? label : undefined}
        className={`w-full flex items-center gap-3.5 rounded-xl px-4 py-3 text-left transition ${
          isActive ? "bg-white/12 text-white font-semibold shadow-xs" : "text-white/70 hover:bg-white/8 hover:text-white"
        } ${collapsed ? "lg:justify-center lg:px-3" : ""}`}
      >
        <Icon size={19} strokeWidth={1.8} className={isActive ? "text-white" : "text-white/70"} />
        <span className={`text-[13.5px] tracking-[-.01em] ${collapsed ? "lg:hidden" : ""}`}>{label}</span>
      </button>
    );
  };

  return (
    <>
      {/* Backdrop — only rendered/interactive on small & medium screens while the drawer is open */}
      {mobileOpen && (
        <div
          onClick={onCloseMobile}
          aria-hidden="true"
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px] lg:hidden"
        />
      )}

      <aside
        role="navigation"
        aria-label="Main navigation"
        className={`fixed inset-y-0 left-0 z-50 h-screen bg-brandDark text-white flex flex-col justify-between
          transition-transform duration-300 ease-out w-[248px]
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}
          lg:static lg:translate-x-0 lg:shrink-0 lg:transition-[width] lg:duration-300
          ${collapsed ? "lg:w-[76px]" : "lg:w-[248px]"}`}
      >
        {/* Top Header & Navigation */}
        <div>
          {/* Brand Header */}
          <div className={`px-6 pt-7 pb-6 flex items-start justify-between ${collapsed ? "lg:px-3" : ""}`}>
            <button onClick={() => select("dashboard")} className={`text-left ${collapsed ? "lg:mx-auto lg:block" : ""}`}>
              <div className="font-display text-[26px] tracking-[.16em] font-semibold text-white">LINEAGE</div>
              <p className={`text-[9px] tracking-[.14em] text-white/60 mt-1 uppercase font-medium ${collapsed ? "lg:hidden" : ""}`}>
                TRACE TRUTH. PROTECT PEOPLE.
              </p>
            </button>
            {/* Close button — mobile drawer only */}
            <button onClick={onCloseMobile} className="lg:hidden text-white/70 hover:text-white p-1 -mr-1" aria-label="Close menu">
              <X size={20} />
            </button>
          </div>

          {/* Primary Sidebar Items */}
          <nav className="px-3 space-y-1.5">
            <Item k="dashboard" label="Dashboard" Icon={LayoutDashboard} />
            <Item k="investigations" label="Investigations" Icon={FolderOpen} />
            <Item k="new" label="New Case" Icon={Plus} />
            <Item k="roadmap" label="Roadmap" Icon={Map} />
          </nav>
        </div>

        {/* Bottom Controls & Card */}
        <div className="px-3 pb-5 space-y-2.5">
          <Item k="settings" label="Settings" Icon={Settings} />

          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`hidden lg:flex w-full items-center gap-3 rounded-xl px-4 py-2.5 text-white/50 hover:text-white hover:bg-white/8 transition ${
              collapsed ? "justify-center px-3" : ""
            }`}
            title="Collapse sidebar"
          >
            {collapsed ? (
              <ChevronRight size={18} />
            ) : (
              <>
                <ChevronLeft size={18} />
                <span className="text-[12px] font-medium">Collapse sidebar</span>
              </>
            )}
          </button>

          <div className={`mt-3 rounded-2xl border border-white/12 bg-white/5 p-4 flex items-center gap-3.5 shadow-xs ${collapsed ? "lg:hidden" : ""}`}>
            <div className="h-9 w-9 rounded-xl bg-white/10 flex items-center justify-center text-white/90 shrink-0">
              <Shield size={18} />
            </div>
            <div>
              <p className="text-[12.5px] font-semibold text-white/95 leading-tight">A safer</p>
              <p className="text-[11.5px] text-white/70 leading-tight mt-0.5">digital tomorrow.</p>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
