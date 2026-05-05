/**
 * Filter bar above the dashboard table.
 *
 * Four facets, all client-side:
 *   status      single-select (chips)   All | In Progress | Escalated | Complete | Resolved
 *   stages      multi-select (chips)    one per StageName
 *   clients     multi-select (chips)    one per ClientId
 *   specialty   multi-select (chips)    one per Specialty
 *
 * Empty multi-select = "no filter" (all values pass).
 *
 * "Resolved" is the lifetime fact: appointment has had at least one
 * concierge resolution applied. Different from currently-Cleared at one
 * stage. See types.ts → hasResolutions for the predicate.
 */

import type { ClientId, Specialty, StageName } from "../types";
import { STAGE_LABELS, STAGE_ORDER } from "../types";

export type StatusFilter =
  | "all"
  | "in_progress"
  | "escalated"
  | "complete"
  | "resolved";

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In Progress" },
  { value: "escalated", label: "Escalated" },
  { value: "complete", label: "Complete" },
  { value: "resolved", label: "Resolved" },
];

const CLIENT_OPTIONS: { value: ClientId; label: string }[] = [
  { value: "C-NORTHWELL", label: "Northwell" },
  { value: "C-MERCY", label: "Mercy" },
  { value: "C-VALLEY", label: "Valley" },
];

const SPECIALTY_OPTIONS: { value: Specialty; label: string }[] = [
  { value: "cardiology", label: "Cardiology" },
  { value: "orthopedics", label: "Orthopedics" },
  { value: "dermatology", label: "Dermatology" },
  { value: "primary_care", label: "Primary Care" },
];

export interface DashboardFilterState {
  status: StatusFilter;
  stages: Set<StageName>;
  clients: Set<ClientId>;
  specialties: Set<Specialty>;
}

export const EMPTY_FILTERS: DashboardFilterState = {
  status: "all",
  stages: new Set(),
  clients: new Set(),
  specialties: new Set(),
};

export function isFilterEmpty(f: DashboardFilterState): boolean {
  return (
    f.status === "all" &&
    f.stages.size === 0 &&
    f.clients.size === 0 &&
    f.specialties.size === 0
  );
}

interface DashboardFiltersProps {
  value: DashboardFilterState;
  onChange: (next: DashboardFilterState) => void;
}

export function DashboardFilters({ value, onChange }: DashboardFiltersProps) {
  function setStatus(status: StatusFilter) {
    onChange({ ...value, status });
  }
  function toggleSet<T>(set: Set<T>, item: T): Set<T> {
    const next = new Set(set);
    if (next.has(item)) next.delete(item);
    else next.add(item);
    return next;
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 space-y-2 text-xs">
      <FilterRow label="Status">
        {STATUS_OPTIONS.map((o) => (
          <Chip
            key={o.value}
            active={value.status === o.value}
            onClick={() => setStatus(o.value)}
          >
            {o.label}
          </Chip>
        ))}
      </FilterRow>

      <FilterRow label="Stages">
        {STAGE_ORDER.map((s, i) => (
          <Chip
            key={s}
            active={value.stages.has(s)}
            onClick={() =>
              onChange({ ...value, stages: toggleSet(value.stages, s) })
            }
            title={STAGE_LABELS[s]}
          >
            <span className="font-mono text-zinc-500 mr-1">S{i + 1}</span>
            {STAGE_LABELS[s]}
          </Chip>
        ))}
      </FilterRow>

      <FilterRow label="Clients">
        {CLIENT_OPTIONS.map((o) => (
          <Chip
            key={o.value}
            active={value.clients.has(o.value)}
            onClick={() =>
              onChange({ ...value, clients: toggleSet(value.clients, o.value) })
            }
          >
            {o.label}
          </Chip>
        ))}
      </FilterRow>

      <FilterRow label="Specialty">
        {SPECIALTY_OPTIONS.map((o) => (
          <Chip
            key={o.value}
            active={value.specialties.has(o.value)}
            onClick={() =>
              onChange({
                ...value,
                specialties: toggleSet(value.specialties, o.value),
              })
            }
          >
            {o.label}
          </Chip>
        ))}
        {!isFilterEmpty(value) && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            className="ml-auto text-zinc-500 hover:text-zinc-200 underline-offset-2 hover:underline"
          >
            clear all filters
          </button>
        )}
      </FilterRow>
    </div>
  );
}

function FilterRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="font-mono text-zinc-500 w-20 shrink-0">{label}</span>
      <div className="flex flex-wrap gap-1.5 items-center flex-1">
        {children}
      </div>
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`px-2 py-0.5 rounded-md border transition-colors ${
        active
          ? "bg-zinc-100 text-zinc-900 border-zinc-100"
          : "bg-zinc-900 text-zinc-300 border-zinc-800 hover:border-zinc-600"
      }`}
    >
      {children}
    </button>
  );
}
