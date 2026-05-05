/**
 * Dashboard: appointment list with pipeline visualization.
 *
 * Anatomy (top to bottom):
 *   - Stat cards (total / pickable / escalated / complete) — pulled from /health
 *   - StageBreakdown chips (per-stage workload at a glance)
 *   - DashboardFilters (status / stages / clients / specialty, all client-side)
 *   - Table header with sortable columns
 *   - One row per appointment: name, pipeline pills, current stage, score, SLA, tags
 *
 * Why client-side filter/sort:
 *   - Polled list is at most ~25 rows. Server-side filtering would shift state
 *     into URL params and force re-fetches on every chip toggle. Pure client
 *     UX is faster and the dataset is small.
 *
 * Why a derived useMemo and not a useEffect-set state:
 *   - filtered/sorted is a function of (appointments, filter, sort). Recomputing
 *     on render is O(n log n) on 25 items — cheap. State duplication (a "view
 *     model" mirror) would add a sync bug surface for zero benefit.
 */

import { useMemo, useState } from "react";
import type { PollingData } from "../lib/usePollingData";
import type { AppointmentState, StageName } from "../types";
import {
  STAGE_LABELS,
  STAGE_ORDER,
  hasResolutions,
  isCompleted,
  isEscalated,
  isInProgress,
} from "../types";
import { PipelinePills } from "../components/PipelinePills";
import { SlaCountdown } from "../components/SlaCountdown";
import { StageBreakdown } from "../components/StageBreakdown";
import {
  DashboardFilters,
  EMPTY_FILTERS,
  isFilterEmpty,
  type DashboardFilterState,
} from "../components/DashboardFilters";

interface DashboardProps {
  data: PollingData;
}

type SortKey = "priority_score" | "patient_name" | "sla_due_at" | "current_stage";
type SortDir = "asc" | "desc";

const STAGE_INDEX: Record<StageName, number> = STAGE_ORDER.reduce(
  (acc, s, i) => ({ ...acc, [s]: i }),
  {} as Record<StageName, number>
);

export function Dashboard({ data }: DashboardProps) {
  const { appointments, health, error, loading } = data;
  const [filters, setFilters] = useState<DashboardFilterState>(EMPTY_FILTERS);
  const [sortKey, setSortKey] = useState<SortKey>("priority_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const visible = useMemo(
    () => sortAppointments(filterAppointments(appointments, filters), sortKey, sortDir),
    [appointments, filters, sortKey, sortDir]
  );

  if (loading && appointments.length === 0) {
    return <Shell>Loading appointments…</Shell>;
  }
  if (error) {
    return (
      <Shell tone="error">
        <div className="font-mono text-sm text-rose-300">
          Backend unreachable: {error.message}
        </div>
        <div className="text-xs text-zinc-500 mt-2">
          Try{" "}
          <code className="font-mono">
            .venv/bin/uvicorn app.main:app --port 8765
          </code>{" "}
          from the backend directory.
        </div>
      </Shell>
    );
  }

  function handleSortClick(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "priority_score" || key === "sla_due_at" ? "desc" : "asc");
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex items-baseline gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <span className="text-sm text-zinc-500 font-mono">
          {appointments.length} appointments · polled every 2s
          {!isFilterEmpty(filters) && (
            <span className="text-zinc-300 ml-2">
              · {visible.length} match filters
            </span>
          )}
        </span>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="total" value={health?.stats.total ?? appointments.length} />
        <StatCard label="pickable" value={health?.stats.pickable ?? "-"} tone="emerald" />
        <StatCard label="escalated" value={health?.stats.escalated ?? "-"} tone="amber" />
        <StatCard label="complete" value={health?.stats.complete ?? "-"} tone="zinc" />
      </div>

      <StageBreakdown appointments={appointments} />

      <DashboardFilters value={filters} onChange={setFilters} />

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 overflow-hidden">
        <TableHeader sortKey={sortKey} sortDir={sortDir} onSort={handleSortClick} />
        <div className="divide-y divide-zinc-800">
          {visible.length === 0 ? (
            <div className="p-12 text-center">
              <div className="text-zinc-400 mb-1">
                No appointments match.
              </div>
              <button
                type="button"
                onClick={() => setFilters(EMPTY_FILTERS)}
                className="text-xs font-mono text-zinc-500 hover:text-zinc-200 underline-offset-2 hover:underline"
              >
                Clear filters to see all {appointments.length}.
              </button>
            </div>
          ) : (
            visible.map((a) => <Row key={a.appointment_id} appointment={a} />)
          )}
        </div>
      </div>
    </div>
  );
}

// ───── Filtering / sorting ───────────────────────────────────────────────

function filterAppointments(
  appts: AppointmentState[],
  f: DashboardFilterState
): AppointmentState[] {
  return appts.filter((a) => {
    if (f.status === "in_progress" && !isInProgress(a)) return false;
    if (f.status === "escalated" && !isEscalated(a)) return false;
    if (f.status === "complete" && !isCompleted(a)) return false;
    if (f.status === "resolved" && !hasResolutions(a)) return false;
    if (f.stages.size > 0) {
      if (a.current_stage === null) return false;
      if (!f.stages.has(a.current_stage)) return false;
    }
    if (f.clients.size > 0 && !f.clients.has(a.client_id)) return false;
    if (f.specialties.size > 0 && !f.specialties.has(a.specialty)) return false;
    return true;
  });
}

function sortAppointments(
  appts: AppointmentState[],
  key: SortKey,
  dir: SortDir
): AppointmentState[] {
  const sign = dir === "asc" ? 1 : -1;
  const cmp = (a: AppointmentState, b: AppointmentState): number => {
    switch (key) {
      case "priority_score":
        return sign * ((a.priority_score ?? -Infinity) - (b.priority_score ?? -Infinity));
      case "patient_name":
        return sign * a.patient_name.localeCompare(b.patient_name);
      case "sla_due_at":
        return sign * (new Date(a.sla_due_at).getTime() - new Date(b.sla_due_at).getTime());
      case "current_stage": {
        const ai = a.current_stage ? STAGE_INDEX[a.current_stage] : Infinity;
        const bi = b.current_stage ? STAGE_INDEX[b.current_stage] : Infinity;
        return sign * (ai - bi);
      }
    }
  };
  return [...appts].sort(cmp);
}

// ───── Row + table chrome ────────────────────────────────────────────────

const ROW_GRID =
  "grid grid-cols-[minmax(190px,1.6fr)_180px_minmax(150px,1fr)_80px_110px_minmax(150px,1fr)] gap-3 items-center";

function TableHeader({
  sortKey,
  sortDir,
  onSort,
}: {
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  return (
    <div
      className={`${ROW_GRID} px-4 py-2 bg-zinc-900/80 border-b border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500 font-mono`}
    >
      <SortHeader k="patient_name" current={sortKey} dir={sortDir} onClick={onSort}>
        Patient
      </SortHeader>
      <span>Pipeline</span>
      <SortHeader k="current_stage" current={sortKey} dir={sortDir} onClick={onSort}>
        Current Stage
      </SortHeader>
      <SortHeader k="priority_score" current={sortKey} dir={sortDir} onClick={onSort} alignRight>
        Score
      </SortHeader>
      <SortHeader k="sla_due_at" current={sortKey} dir={sortDir} onClick={onSort} alignRight>
        SLA
      </SortHeader>
      <span className="text-right">Tags</span>
    </div>
  );
}

function SortHeader({
  k,
  current,
  dir,
  onClick,
  children,
  alignRight,
}: {
  k: SortKey;
  current: SortKey;
  dir: SortDir;
  onClick: (k: SortKey) => void;
  children: React.ReactNode;
  alignRight?: boolean;
}) {
  const active = k === current;
  const arrow = active ? (dir === "asc" ? " ↑" : " ↓") : "";
  return (
    <button
      type="button"
      onClick={() => onClick(k)}
      className={`${alignRight ? "text-right" : "text-left"} ${
        active ? "text-zinc-200" : "text-zinc-500"
      } hover:text-zinc-100`}
    >
      {children}
      <span className="font-mono">{arrow}</span>
    </button>
  );
}

function Row({ appointment: a }: { appointment: AppointmentState }) {
  const stageIdx = a.current_stage ? STAGE_INDEX[a.current_stage] : null;
  const stageLabel = a.current_stage ? STAGE_LABELS[a.current_stage] : null;
  const escalated = isEscalated(a);
  const completed = isCompleted(a);

  return (
    <div
      className={`${ROW_GRID} px-4 py-2.5 hover:bg-zinc-900/60 ${
        escalated ? "bg-rose-950/10" : ""
      }`}
    >
      <div className="min-w-0">
        <div className="text-sm text-zinc-100 truncate">{a.patient_name}</div>
        <div className="text-[11px] text-zinc-500 font-mono">{a.appointment_id}</div>
      </div>

      <PipelinePills appointment={a} />

      <div className="min-w-0 text-xs">
        {completed ? (
          <span className="text-emerald-400 font-mono">✓ done</span>
        ) : a.current_stage ? (
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-mono text-zinc-500">S{(stageIdx ?? 0) + 1}</span>
            <span
              className={`truncate ${escalated ? "text-rose-300" : "text-zinc-200"}`}
            >
              {stageLabel}
            </span>
            {escalated && (
              <span
                className="text-[10px] uppercase tracking-wider font-mono text-rose-400"
                title={a.escalation_reason?.code ?? ""}
              >
                escalated
              </span>
            )}
          </div>
        ) : (
          <span className="text-zinc-500">—</span>
        )}
      </div>

      <div
        className="text-right font-mono text-xs tabular-nums text-zinc-200"
        title={a.priority_reasoning ?? ""}
      >
        {a.priority_score !== null ? a.priority_score.toFixed(3) : "—"}
      </div>

      <div className="text-right">
        <SlaCountdown dueIso={a.sla_due_at} />
      </div>

      <div className="text-right text-[11px] font-mono text-zinc-500 truncate">
        {clientShort(a.client_id)} · {a.specialty.replace("_", " ")}
      </div>
    </div>
  );
}

function clientShort(c: string): string {
  if (c === "C-NORTHWELL") return "Northwell";
  if (c === "C-MERCY") return "Mercy";
  if (c === "C-VALLEY") return "Valley";
  return c;
}

// ───── Stat card / shell ─────────────────────────────────────────────────

function StatCard({
  label,
  value,
  tone = "zinc",
}: {
  label: string;
  value: number | string;
  tone?: "zinc" | "emerald" | "amber";
}) {
  const tones: Record<string, string> = {
    zinc: "text-zinc-100",
    emerald: "text-emerald-300",
    amber: "text-amber-300",
  };
  return (
    <div className="p-4 rounded-lg bg-zinc-900/60 border border-zinc-800">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-mono">
        {label}
      </div>
      <div className={`text-2xl font-semibold mt-1 ${tones[tone]}`}>{value}</div>
    </div>
  );
}

function Shell({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "error";
}) {
  const cls =
    tone === "error"
      ? "bg-rose-950/30 border-rose-900/60"
      : "bg-zinc-900/40 border-zinc-800";
  return <div className={`p-6 rounded-lg border ${cls}`}>{children}</div>;
}
