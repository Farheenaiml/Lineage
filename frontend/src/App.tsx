import { useEffect, useState } from "react";
import Sidebar, { ScreenKey } from "./components/Sidebar";
import TopBar from "./components/TopBar";
import Dashboard from "./screens/Dashboard";
import Overview from "./screens/Overview";
import UploadDetection from "./screens/UploadDetection";
import FingerprintScreen from "./screens/Fingerprint";
import EvidenceLocker from "./screens/EvidenceLocker";
import LineageMap from "./screens/LineageMap";
import AttributionGap from "./screens/AttributionGap";
import IncidentReport from "./screens/IncidentReport";
import CaseAutomation from "./screens/CaseAutomation";
import Roadmap from "./screens/Roadmap";
import Landing from "./screens/Landing";
import Login from "./screens/Login";
import NewInvestigation from "./screens/NewInvestigation";
import Settings from "./screens/Settings";
import Investigations from "./screens/Investigations";
import InvestigationLayout from "./components/InvestigationLayout";
import { CaseProvider, useCase } from "./context/CaseContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LoadingState } from "./components/states";

function screenFromPath(path: string): ScreenKey | "landing" | "login" {
  if (path === "/" || path === "") return "landing";
  if (path === "/login") return "login";
  if (path === "/dashboard") return "dashboard";
  if (path === "/investigations" || path === "/investigations/") return "investigations";
  if (path === "/investigations/new") return "new";
  if (path.includes("/detection")) return "detection";
  if (path.includes("/fingerprint")) return "fingerprint";
  if (path.includes("/evidence")) return "evidence";
  if (path.includes("/lineage")) return "lineage";
  if (path.includes("/attribution")) return "gap";
  if (path.includes("/report")) return "report";
  if (path.includes("/automation")) return "automation";
  if (path.startsWith("/investigations/")) return "overview";
  if (path === "/roadmap") return "roadmap";
  if (path === "/settings") return "settings";
  return "dashboard";
}

const paths: Record<ScreenKey, string> = {
  dashboard: "/dashboard",
  investigations: "/investigations",
  new: "/investigations/new",
  overview: "/investigations/INC-2024-012",
  detection: "/investigations/INC-2024-012/detection",
  fingerprint: "/investigations/INC-2024-012/fingerprint",
  evidence: "/investigations/INC-2024-012/evidence",
  lineage: "/investigations/INC-2024-012/lineage",
  gap: "/investigations/INC-2024-012/attribution",
  report: "/investigations/INC-2024-012/report",
  automation: "/investigations/INC-2024-012/automation",
  roadmap: "/roadmap",
  settings: "/settings",
};

const investigationScreenKeys = new Set<ScreenKey>([
  "overview",
  "detection",
  "fingerprint",
  "evidence",
  "lineage",
  "gap",
  "report",
  "automation",
]);

export default function App() {
  return (
    <AuthProvider>
      <CaseProvider>
        <AppShell />
      </CaseProvider>
    </AuthProvider>
  );
}

function AppShell() {
  const { user, loading: authLoading, logout } = useAuth();
  const { incidentId } = useCase();
  const [route, setRoute] = useState<ScreenKey | "landing" | "login">(screenFromPath(window.location.pathname));
  const [collapsed, setCollapsed] = useState(false);
  const [dark, setDark] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const navigate = (s: ScreenKey | "landing" | "login") => {
    const p = s === "landing" ? "/" : s === "login" ? "/login" : paths[s];
    window.history.pushState({}, "", p);
    setRoute(s);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    const f = () => setRoute(screenFromPath(window.location.pathname));
    window.addEventListener("popstate", f);
    return () => window.removeEventListener("popstate", f);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("theme-dark", dark);
  }, [dark]);

  // Wait for the stored token to be validated before deciding what to show —
  // otherwise a logged-in user briefly sees the landing page on every reload.
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <LoadingState label="Restoring your session…" />
      </div>
    );
  }

  if (route === "landing") return <Landing onStart={() => navigate("login")} onLogin={() => navigate("login")} />;
  if (route === "login") return <Login onLogin={() => navigate("dashboard")} onBack={() => navigate("landing")} />;

  // Auth guard: every screen past this point needs a real session.
  if (!user) return <Login onLogin={() => navigate("dashboard")} onBack={() => navigate("landing")} />;

  // Investigation screens need an active case — send the user to pick one
  // rather than rendering a case view with nothing loaded.
  if (investigationScreenKeys.has(route as ScreenKey) && !incidentId) {
    return (
      <div className="min-h-screen flex bg-bg text-ink">
        <div className="m-auto text-center max-w-md px-6">
          <h2 className="font-display text-2xl text-ink">No investigation selected</h2>
          <p className="text-[13px] text-muted mt-2">
            Open an existing investigation or start a new one to view its analysis.
          </p>
          <div className="flex gap-2 justify-center mt-5">
            <button onClick={() => navigate("investigations")} className="rounded-xl border border-border px-4 py-2.5 text-[12.5px] font-medium">
              Browse Investigations
            </button>
            <button onClick={() => navigate("new")} className="rounded-xl bg-brand text-white px-4 py-2.5 text-[12.5px] font-semibold">
              New Investigation
            </button>
          </div>
        </div>
      </div>
    );
  }

  const isInvestigationRoute = typeof route === "string" && investigationScreenKeys.has(route as ScreenKey);

  return (
    <>
      <div className={`min-h-screen flex bg-bg text-ink ${dark ? "dark-ui" : ""}`}>
        <Sidebar
          active={route as ScreenKey}
          onSelect={navigate}
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          mobileOpen={mobileNavOpen}
          onCloseMobile={() => setMobileNavOpen(false)}
        />
        <div className="min-w-0 flex-1 flex flex-col min-h-screen">
          <TopBar
            dark={dark}
            setDark={setDark}
            onMenuClick={() => setMobileNavOpen(true)}
            user={user}
            onLogout={() => { logout(); navigate("landing"); }}
          />
          <main className="flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 py-7">
            {isInvestigationRoute ? (
              <InvestigationLayout activeTab={route as ScreenKey} onNavigate={navigate}>
                {route === "overview" && <Overview onNavigate={navigate} />}
                {route === "detection" && <UploadDetection />}
                {route === "fingerprint" && <FingerprintScreen />}
                {route === "evidence" && <EvidenceLocker />}
                {route === "lineage" && <LineageMap onNavigate={navigate} />}
                {route === "gap" && <AttributionGap onNavigate={navigate} />}
                {route === "report" && <IncidentReport />}
                {route === "automation" && <CaseAutomation onNavigate={navigate} />}
              </InvestigationLayout>
            ) : (
              <div className="max-w-[1400px] mx-auto">
                {route === "dashboard" && <Dashboard onNavigate={navigate} />}
                {route === "investigations" && <Investigations onNavigate={navigate} />}
                {route === "new" && <NewInvestigation onNavigate={navigate} />}
                {route === "roadmap" && <Roadmap />}
                {route === "settings" && <Settings dark={dark} setDark={setDark} />}
              </div>
            )}
          </main>
        </div>
      </div>
    </>
  );
}
