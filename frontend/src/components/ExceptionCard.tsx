/**
 * One escalated appointment, fully expanded for the human concierge.
 *
 * Vertical anatomy:
 *   header        identity + SLA countdown
 *   reason        code chip + stage label + message + suggested_action
 *   pipeline      six-pill strip (same color semantics as Dashboard)
 *   context       collapsible <details> with the agent_context JSON
 *   form          the resolution form (always visible — this card exists for resolution)
 *
 * The form is always visible (not behind a "Resolve" button) because the
 * Exception Queue is a single-purpose view: every card here exists to be
 * resolved. Hiding the form behind a click would add friction for zero gain.
 */

import type { AppointmentState, EscalationReason, StageName } from "../types";
import { STAGE_LABELS, STAGE_ORDER } from "../types";
import { PipelinePills } from "./PipelinePills";
import { SlaCountdown } from "./SlaCountdown";
import { ResolutionForm } from "./ResolutionForm";

interface ExceptionCardProps {
  appointment: AppointmentState;
  onResolved?: () => void;
}

const STAGE_INDEX: Record<StageName, number> = STAGE_ORDER.reduce(
  (acc, s, i) => ({ ...acc, [s]: i }),
  {} as Record<StageName, number>
);

function clientShort(c: string): string {
  if (c === "C-NORTHWELL") return "Northwell";
  if (c === "C-MERCY") return "Mercy";
  if (c === "C-VALLEY") return "Valley";
  return c;
}

function formatTimeAgo(iso: string, now: number = Date.now()): string {
  const diffMs = now - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function ExceptionCard({ appointment, onResolved }: ExceptionCardProps) {
  const e = appointment.escalation_reason as EscalationReason;
  const stageIdx = STAGE_INDEX[e.raised_at_stage];
  const contextEntries = Object.entries(e.agent_context);
  const priorResolutions = appointment.resolutions.length;

  return (
    <div className="rounded-lg bg-zinc-900/60 border border-rose-900/40 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800 bg-rose-950/20">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div className="flex items-baseline gap-3 min-w-0">
            <span className="font-mono text-xs text-zinc-500">
              {appointment.appointment_id}
            </span>
            <span className="font-medium text-zinc-100 text-base truncate">
              {appointment.patient_name}
            </span>
            <span className="text-xs text-zinc-400 truncate">
              {appointment.specialty.replace("_", " ")} · {appointment.procedure}
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-[11px] text-zinc-500 font-mono">
              {clientShort(appointment.client_id)}
            </span>
            <SlaCountdown dueIso={appointment.sla_due_at} />
          </div>
        </div>
      </div>

      <div className="px-4 py-3 space-y-3">
        <div>
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider font-mono text-rose-400">
              Stage {stageIdx + 1} escalation
            </span>
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-amber-900/40 text-amber-200 border border-amber-800/60">
              {e.code}
            </span>
            <span className="text-xs text-zinc-400 font-mono">
              @ {STAGE_LABELS[e.raised_at_stage]}
            </span>
            <span className="text-[11px] text-zinc-600 font-mono ml-auto">
              raised {formatTimeAgo(e.raised_at)}
            </span>
          </div>
          <p className="mt-2 text-sm text-zinc-100 leading-relaxed">{e.message}</p>
          {e.suggested_action && (
            <p className="mt-1.5 text-xs text-zinc-400">
              <span className="font-mono text-zinc-500">suggested:</span>{" "}
              {e.suggested_action}
            </p>
          )}
        </div>

        <div className="flex items-center gap-3">
          <PipelinePills appointment={appointment} />
          {priorResolutions > 0 && (
            <span
              className="text-[11px] font-mono text-zinc-500"
              title={`This appointment has ${priorResolutions} prior resolution${
                priorResolutions === 1 ? "" : "s"
              } in its history.`}
            >
              {priorResolutions} prior resolution{priorResolutions === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {contextEntries.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-zinc-400 hover:text-zinc-100 select-none">
              <span className="font-mono">▶</span> Agent context (
              {contextEntries.length} field{contextEntries.length === 1 ? "" : "s"})
            </summary>
            <pre className="mt-2 font-mono text-[11px] bg-zinc-950 rounded p-3 overflow-x-auto text-zinc-300 border border-zinc-800">
              {JSON.stringify(e.agent_context, null, 2)}
            </pre>
          </details>
        )}

        <ResolutionForm
          appointmentId={appointment.appointment_id}
          defaultMode={e.default_resolution_mode}
          onResolved={onResolved}
        />
      </div>
    </div>
  );
}
