import { useState } from "react";
import { Bell, Database, Lock, Palette, Shield, User, Download, Trash2, ChevronRight, CheckCircle2 } from "lucide-react";
import { Panel, PanelHeader, StatusBadge, SectionTitle } from "../components/ui";

type Category = "Profile" | "Security" | "Privacy" | "Notifications" | "Data Management" | "Appearance";

export default function Settings({ dark, setDark }: { dark: boolean; setDark: (v: boolean) => void }) {
  const [activeCategory, setActiveCategory] = useState<Category>("Profile");

  const categories: [Category, any][] = [
    ["Profile", User],
    ["Security", Lock],
    ["Privacy", Shield],
    ["Notifications", Bell],
    ["Data Management", Database],
    ["Appearance", Palette],
  ];

  return (
    <div className="max-w-[1250px] mx-auto space-y-6">
      <SectionTitle title="Settings" description="Manage your account, privacy, security, and preferences." />

      <div className="grid lg:grid-cols-[240px_1fr] gap-6 items-start">
        {/* Left Menu Bar */}
        <Panel className="p-2 sm:p-3 overflow-x-auto no-scrollbar">
          <div className="flex lg:flex-col gap-1 min-w-max lg:min-w-0">
            {categories.map(([t, Icon]) => {
              const isActive = activeCategory === t;
              return (
                <button
                  key={t}
                  onClick={() => setActiveCategory(t)}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-[13px] font-medium text-left transition-all ${
                    isActive
                      ? "bg-soft text-brand font-semibold shadow-xs"
                      : "text-muted hover:text-ink hover:bg-soft/40"
                  }`}
                >
                  <Icon size={18} className={isActive ? "text-brand" : "text-muted"} />
                  {t}
                </button>
              );
            })}
          </div>
        </Panel>

        {/* Right Pane — Single Expanded Active Card */}
        <div className="w-full">
          {activeCategory === "Profile" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader
                title="Profile Information"
                subtitle="Manage your investigator details and pseudonymous profile."
                right={<button className="text-[12px] font-medium border border-border rounded-lg px-3.5 py-1.5 hover:bg-soft transition">Edit</button>}
              />
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-5 p-5 rounded-2xl bg-soft/50 border border-border/60">
                <div className="h-16 w-16 rounded-2xl bg-brand text-white flex items-center justify-center font-display text-2xl shadow-sm shrink-0">
                  A
                </div>
                <div>
                  <h3 className="font-semibold text-lg text-ink">Demo Investigator</h3>
                  <p className="text-[13px] text-muted mt-0.5">investigator@example.com</p>
                  <div className="flex gap-2 mt-2">
                    <StatusBadge tone="green">Verified Investigator</StatusBadge>
                  </div>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-4 pt-4 border-t border-border/60">
                <div className="p-4 rounded-xl border border-border/60 bg-[#FAFBF9]">
                  <p className="text-muted text-[12px] font-medium">Role</p>
                  <p className="mt-1 font-semibold text-ink text-[14px]">Lead Investigator</p>
                </div>
                <div className="p-4 rounded-xl border border-border/60 bg-[#FAFBF9]">
                  <p className="text-muted text-[12px] font-medium">Account Privacy Mode</p>
                  <p className="mt-1 font-semibold text-ink text-[14px]">Pseudonymous ID</p>
                </div>
                <div className="p-4 rounded-xl border border-border/60 bg-[#FAFBF9]">
                  <p className="text-muted text-[12px] font-medium">Organization</p>
                  <p className="mt-1 font-semibold text-ink text-[14px]">LINEAGE Defense Team</p>
                </div>
                <div className="p-4 rounded-xl border border-border/60 bg-[#FAFBF9]">
                  <p className="text-muted text-[12px] font-medium">Member Since</p>
                  <p className="mt-1 font-semibold text-ink text-[14px]">October 2024</p>
                </div>
              </div>
            </Panel>
          )}

          {activeCategory === "Security" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader title="Security Settings" subtitle="Keep your account secure with strong credentials and two-factor authentication." />
              <div className="divide-y divide-border/60">
                <SettingRow icon={Lock} title="Password" sub="Last changed 2 months ago" buttonText="Change Password" />
                <SettingRow icon={Shield} title="Two-Factor Authentication" sub="Add an extra layer of security via TOTP authenticator" badge="Enabled" />
                <SettingRow icon={User} title="Active Sessions" sub="Currently logged in on 1 active desktop device" buttonText="Manage Sessions" />
              </div>
            </Panel>
          )}

          {activeCategory === "Privacy" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader title="Privacy Preferences" subtitle="Control your data visibility and analytical tracking." />
              <div className="divide-y divide-border/60">
                <ToggleRow title="Profile visibility" sub="Keep your investigator profile hidden from public search" initialOn={true} />
                <ToggleRow title="Usage analytics" sub="Share anonymous platform usage metrics to help improve LINEAGE" initialOn={false} />
                <ToggleRow title="Data sharing" sub="Allow investigation metadata cross-referencing across verified cases" initialOn={false} />
              </div>
            </Panel>
          )}

          {activeCategory === "Notifications" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader title="Notification Preferences" subtitle="Choose when and how you receive investigation alerts." />
              <div className="divide-y divide-border/60">
                <ToggleRow title="Investigation updates" sub="Get notified on analysis progress and case changes" initialOn={true} />
                <ToggleRow title="System & Security alerts" sub="Important security alerts and system service updates" initialOn={true} />
                <ToggleRow title="Product updates" sub="New feature announcements and platform improvements" initialOn={false} />
              </div>
            </Panel>
          )}

          {activeCategory === "Data Management" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader title="Data Management" subtitle="Manage your storage quota, export investigation logs, or delete your account." />
              
              <div className="p-5 rounded-2xl bg-soft/50 border border-border/60 space-y-3">
                <div className="flex justify-between items-center text-[13px] font-semibold text-ink">
                  <span>Storage Quota Used</span>
                  <span>2.4 GB / 10 GB</span>
                </div>
                <div className="h-3 rounded-full bg-[#EEF1ED] overflow-hidden">
                  <div className="h-full w-[24%] bg-brand rounded-full transition-all" />
                </div>
                <p className="text-[12px] text-muted">24% of your allocated 10 GB cloud storage is in use.</p>
              </div>

              <div className="space-y-3 pt-2">
                <button className="w-full flex items-center justify-between border border-border rounded-xl p-4 text-[13px] font-medium text-ink hover:bg-soft transition group">
                  <span className="flex items-center gap-3">
                    <Download size={18} className="text-brand" />
                    Download All My Investigation Data (.zip)
                  </span>
                  <ChevronRight size={16} className="text-muted group-hover:translate-x-0.5 transition-transform" />
                </button>
                
                <button className="w-full flex items-center justify-between border border-[#E9D4D0] text-[#8A4138] rounded-xl p-4 text-[13px] font-semibold hover:bg-[#FDF6F5] transition group">
                  <span className="flex items-center gap-3">
                    <Trash2 size={18} />
                    Delete Account & Purge Data
                  </span>
                  <ChevronRight size={16} className="text-[#8A4138] group-hover:translate-x-0.5 transition-transform" />
                </button>
              </div>
            </Panel>
          )}

          {activeCategory === "Appearance" && (
            <Panel className="p-6 sm:p-8 space-y-6 w-full">
              <PanelHeader title="Appearance & Interface" subtitle="Customize theme and visual preferences." />
              
              <div className="space-y-4">
                <div className="flex items-center justify-between py-4 border-b border-border/60">
                  <div>
                    <p className="text-[13.5px] font-semibold text-ink">Color Theme</p>
                    <p className="text-[12px] text-muted mt-0.5">Currently using {dark ? "Dark" : "Light"} mode</p>
                  </div>
                  <button
                    onClick={() => setDark(!dark)}
                    className="rounded-xl border border-border px-4 py-2.5 text-[12.5px] font-semibold text-ink hover:bg-soft transition"
                  >
                    {dark ? "Switch to Light Mode" : "Switch to Dark Mode"}
                  </button>
                </div>

                <div className="flex items-center justify-between py-4 border-b border-border/60">
                  <div>
                    <p className="text-[13.5px] font-semibold text-ink">Brand Accent Color</p>
                    <p className="text-[12px] text-muted mt-0.5">LINEAGE Signature Green · #3E503C</p>
                  </div>
                  <span className="h-8 w-8 rounded-full bg-brand border-4 border-soft shadow-xs" />
                </div>
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function SettingRow({
  icon: Icon,
  title,
  sub,
  badge,
  buttonText,
}: {
  icon: any;
  title: string;
  sub: string;
  badge?: string;
  buttonText?: string;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-4 first:pt-0 last:pb-0">
      <div className="flex items-start gap-3.5">
        <div className="h-9 w-9 rounded-xl bg-soft text-brand flex items-center justify-center shrink-0 mt-0.5">
          <Icon size={18} />
        </div>
        <div>
          <p className="text-[13.5px] font-semibold text-ink">{title}</p>
          <p className="text-[12px] text-muted mt-0.5">{sub}</p>
        </div>
      </div>
      <div className="shrink-0 self-end sm:self-center">
        {badge ? (
          <StatusBadge tone="green">{badge}</StatusBadge>
        ) : (
          <button className="text-[12px] font-medium border border-border rounded-lg px-3 py-1.5 hover:bg-soft transition text-ink">
            {buttonText || "Configure"}
          </button>
        )}
      </div>
    </div>
  );
}

function ToggleRow({ title, sub, initialOn = false }: { title: string; sub: string; initialOn?: boolean }) {
  const [on, setOn] = useState(initialOn);
  return (
    <div className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div>
        <p className="text-[13.5px] font-semibold text-ink">{title}</p>
        <p className="text-[12px] text-muted mt-0.5">{sub}</p>
      </div>
      <button
        onClick={() => setOn(!on)}
        className={`w-11 h-6 rounded-full p-1 transition-colors shrink-0 ${on ? "bg-brand" : "bg-[#DCE1DC]"}`}
      >
        <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${on ? "translate-x-5" : ""}`} />
      </button>
    </div>
  );
}
