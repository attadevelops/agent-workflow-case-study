/**
 * Backend API client.
 *
 * One thin layer of fetch wrappers — no SWR/React Query (per CLAUDE.md, polling
 * via setInterval is the contract). Polling logic lives in `lib/usePollingData.ts`.
 *
 * Base URL is overridable via `VITE_API_BASE` env var. Default targets the dev
 * uvicorn at 127.0.0.1:8765.
 */

import type {
  AppointmentState,
  ConciergeResolution,
  ResolutionMode,
} from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "http://localhost:8765";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} -> ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j && typeof j === "object" && "detail" in j) detail = `${j.detail}`;
    } catch {
      /* ignore */
    }
    throw new Error(`POST ${path} -> ${detail}`);
  }
  return (await res.json()) as T;
}

// ─── Read endpoints ───────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  stats: {
    total: number;
    pickable: number;
    escalated: number;
    complete: number;
  };
  strategy: string | null;
  tick_interval_s: number;
}

export const fetchHealth = () => getJson<HealthResponse>("/health");
export const fetchAppointments = () =>
  getJson<AppointmentState[]>("/appointments");
export const fetchAppointment = (id: string) =>
  getJson<AppointmentState>(`/appointments/${id}`);
export const fetchExceptions = () =>
  getJson<AppointmentState[]>("/exceptions");

// ─── Admin / write endpoints ──────────────────────────────────────────

export interface TickResponse {
  ticked: string | null;
  stats: HealthResponse["stats"];
}

export const adminTick = () => postJson<TickResponse>("/admin/tick");
export const adminSeed = () =>
  postJson<{ status: string; stats: HealthResponse["stats"] }>("/admin/seed");
export const adminSetStrategy = (name: "weighted_sum" | "llm_rule") =>
  postJson<{ strategy: string }>("/admin/strategy", { name });

// ─── Concierge resolution ────────────────────────────────────────────

export interface ResolutionRequest {
  note: string;
  resolver_id?: string;
  resolution_type: ResolutionMode;
  payload?: Record<string, unknown> | null;
}

export const resolveException = (
  appointmentId: string,
  body: ResolutionRequest
) =>
  postJson<AppointmentState>(
    `/exceptions/${appointmentId}/resolve`,
    body
  );

// Re-export for convenience.
export type { ConciergeResolution };
