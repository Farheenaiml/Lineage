/**
 * Typed client for the LINEAGE backend API.
 *
 * Everything the UI needs from the server goes through this file — no
 * component calls fetch() directly. That keeps the auth header, base URL,
 * and error shape in exactly one place.
 *
 * The base URL comes from VITE_API_URL (see .env.example); it defaults to
 * the backend's local dev address so `npm run dev` works with no config.
 */

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const TOKEN_KEY = "lineage_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  { raw = false }: { raw?: boolean } = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    // Network-level failure — the server isn't running or isn't reachable.
    // Surfaced explicitly rather than as a confusing generic error, since
    // "did you start the backend?" is by far the most common cause.
    throw new ApiError(
      `Could not reach the LINEAGE API at ${API_BASE}. Is the backend running?`,
      0
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* response wasn't JSON — keep the status-based message */
    }
    throw new ApiError(detail, res.status);
  }

  if (raw) return (await res.blob()) as unknown as T;
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

/* ---------------------------------- types --------------------------------- */

export type User = { id: string; email: string; display_name: string | null };

export type IncidentStatus =
  | "created"
  | "analyzing"
  | "fingerprinted"
  | "evidence_building"
  | "gap_reviewed"
  | "report_generated"
  | "closed";

export type Incident = {
  id: string;
  title: string;
  description: string | null;
  victim_ref: string | null;
  status: IncidentStatus;
  created_at: string;
  updated_at: string;
};

export type MediaItem = {
  id: string;
  kind: "image" | "video";
  original_filename: string;
  file_size_bytes: number;
  width: number | null;
  height: number | null;
  uploaded_at: string;
};

export type DetectionResult = {
  id: string;
  manipulation_likelihood: number;
  edge_irregularity: number | null;
  compression_density: number | null;
  detected_region: string | null;
  likely_technique: string | null;
  model_name: string;
  explanation: string | null;
  created_at: string;
};

export type Fingerprint = {
  id: string;
  average_hash: string;
  face_embedding_json: string | null;
  keyframe_hashes_json: string | null;
  audio_fingerprint: string | null;
  created_at: string;
};

export type FaceEmbeddingInfo = {
  found_face: boolean;
  embedding?: number[] | null;
  box?: number[] | null;
  detection_confidence?: number | null;
  error?: string;
};

export type Source = {
  id: string;
  platform: string;
  account_identifier: string | null;
  url: string | null;
  observed_at: string;
  similarity_score: number | null;
  relationship_label: string | null;
  is_seeded: boolean;
};

export type SourceRelationship = {
  id: string;
  from_source_id: string;
  to_source_id: string;
  relationship_type: string;
  confidence: number | null;
};

export type EvidenceItem = {
  id: string;
  source_id: string | null;
  item_type: string;
  notes: string | null;
  captured_at: string;
};

export type AttributionGapEntry = {
  id: string;
  category: "known" | "unresolved" | "evidence_needed";
  statement: string;
};

export type IncidentReport = {
  id: string;
  incident_id: string;
  generated_at: string;
  payload: {
    summary: string;
    confidence_breakdown: { label: string; value: number; note: string | null }[];
    recommended_actions: { title: string; detail: string }[];
    source_count: number;
    evidence_count: number;
  };
};

export type WebSearchQuery = {
  query: string;
  google_url: string;
  bing_url: string;
};

export type WebSearchRun = {
  id: string;
  image_description: string;
  summary: string;
  model_name: string;
  created_at: string;
  search_queries: WebSearchQuery[];
};

/* ----------------------------------- api ---------------------------------- */

export const api = {
  /* auth */
  async register(email: string, password: string, displayName?: string): Promise<User> {
    return request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName ?? null }),
    });
  },

  async login(email: string, password: string): Promise<string> {
    // The backend's /auth/login uses OAuth2's form format, where the
    // "username" field carries the email address.
    const form = new URLSearchParams();
    form.append("username", email);
    form.append("password", password);

    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    }).catch(() => {
      throw new ApiError(`Could not reach the LINEAGE API at ${API_BASE}. Is the backend running?`, 0);
    });

    if (!res.ok) {
      let detail = "Incorrect email or password.";
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch { /* keep default */ }
      throw new ApiError(detail, res.status);
    }
    const data = await res.json();
    setToken(data.access_token);
    return data.access_token;
  },

  async me(): Promise<User> {
    return request<User>("/auth/me");
  },

  /* incidents */
  listIncidents: () => request<Incident[]>("/incidents"),
  getIncident: (id: string) => request<Incident>(`/incidents/${id}`),
  createIncident: (title: string, description?: string, victimRef?: string) =>
    request<Incident>("/incidents", {
      method: "POST",
      body: JSON.stringify({ title, description: description ?? null, victim_ref: victimRef ?? null }),
    }),

  /* media + analysis */
  listMedia: (incidentId: string) => request<MediaItem[]>(`/incidents/${incidentId}/media`),
  getMediaPreview: (incidentId: string, mediaId: string) =>
    request<Blob>(`/incidents/${incidentId}/media/${mediaId}/file`, {}, { raw: true }),
  uploadMedia: (incidentId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<MediaItem>(`/incidents/${incidentId}/media`, { method: "POST", body: fd });
  },
  runDetection: (incidentId: string, mediaId: string) =>
    request<DetectionResult>(`/incidents/${incidentId}/media/${mediaId}/detect`, { method: "POST" }),
  getDetection: (incidentId: string, mediaId: string) =>
    request<DetectionResult>(`/incidents/${incidentId}/media/${mediaId}/detection`),
  runFingerprint: (incidentId: string, mediaId: string) =>
    request<Fingerprint>(`/incidents/${incidentId}/media/${mediaId}/fingerprint`, { method: "POST" }),
  getFingerprint: (incidentId: string, mediaId: string) =>
    request<Fingerprint>(`/incidents/${incidentId}/media/${mediaId}/fingerprint`),

  /* consent-gated Gemini query generation for manual public-web search */
  getWebSearchStatus: () => request<{ configured: boolean; provider: string }>("/incidents/web-search/status"),
  generateImageSearchLinks: (incidentId: string, mediaId: string) =>
    request<WebSearchRun>(`/incidents/${incidentId}/media/${mediaId}/web-search`, {
      method: "POST",
      body: JSON.stringify({ consent: true }),
    }),
  getLatestWebSearch: (incidentId: string, mediaId: string) =>
    request<WebSearchRun | null>(`/incidents/${incidentId}/media/${mediaId}/web-search`),

  /* sources + lineage */
  listSources: (incidentId: string) => request<Source[]>(`/incidents/${incidentId}/sources`),
  listRelationships: (incidentId: string) =>
    request<SourceRelationship[]>(`/incidents/${incidentId}/sources/relationships`),

  /* evidence */
  listEvidence: (incidentId: string) => request<EvidenceItem[]>(`/incidents/${incidentId}/evidence`),
  downloadEvidenceFile: (incidentId: string, evidenceId: string) =>
    request<Blob>(`/incidents/${incidentId}/evidence/${evidenceId}/file`, {}, { raw: true }),

  /* attribution gap */
  generateAttributionGap: (incidentId: string) =>
    request<AttributionGapEntry[]>(`/incidents/${incidentId}/attribution-gap`, { method: "POST" }),
  getAttributionGap: (incidentId: string) =>
    request<AttributionGapEntry[]>(`/incidents/${incidentId}/attribution-gap`),

  /* report */
  generateReport: (incidentId: string) =>
    request<IncidentReport>(`/incidents/${incidentId}/report`, { method: "POST" }),
  getReport: (incidentId: string) => request<IncidentReport>(`/incidents/${incidentId}/report`),
  downloadReportPdf: async (incidentId: string): Promise<Blob> =>
    request<Blob>(`/incidents/${incidentId}/report/pdf`, {}, { raw: true }),

  /* sources — real, user-entered */
  addSource: (
    incidentId: string,
    source: {
      platform: string;
      account_identifier?: string;
      url?: string;
      observed_at: string;
      similarity_score?: number;
      relationship_label?: string;
    }
  ) =>
    request<Source>(`/incidents/${incidentId}/sources`, {
      method: "POST",
      body: JSON.stringify({ ...source, is_seeded: false }),
    }),

  addRelationship: (
    incidentId: string,
    rel: { from_source_id: string; to_source_id: string; relationship_type: string; confidence?: number }
  ) =>
    request<SourceRelationship>(`/incidents/${incidentId}/sources/relationships`, {
      method: "POST",
      body: JSON.stringify(rel),
    }),
};

export { API_BASE };
