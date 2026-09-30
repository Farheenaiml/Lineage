/**
 * Cross-screen navigation hint: another screen (e.g. Case Automation) asks the Lineage screen to open on a given tab
 * with a source selected or a map location focused. Stored in sessionStorage and consumed once on mount.
 */
export type LineageFocus = { tab: "map" | "graph" | "copilot" | "ml"; sourceId?: string; mapNodeId?: string };

const KEY = "lineage_focus";

export function setLineageFocus(f: LineageFocus) {
  try { sessionStorage.setItem(KEY, JSON.stringify(f)); } catch { /* storage unavailable: navigation still works */ }
}

export function consumeLineageFocus(): LineageFocus | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return raw ? (JSON.parse(raw) as LineageFocus) : null;
  } catch {
    return null;
  }
}
