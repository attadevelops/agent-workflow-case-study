/**
 * Six-pill pipeline visualization. The single most-watched visual on the
 * dashboard — what makes the system feel agentic at a glance.
 *
 * Color semantics (locked):
 *   not_started  muted gray
 *   processing   amber, animate-pulse
 *   complete     emerald solid
 *   escalate     rose solid
 *   cleared      emerald outline (visually distinct from complete; signals
 *                "human-resolved" rather than "agent-completed")
 *
 * The amber→green fade between polls is achieved with transition-colors
 * duration-300 — no animation library, no useEffect, no state machine.
 * The "live system" feel costs zero JS once the data flow is right.
 *
 * Tooltips use the native title attribute. Sufficient for a demo; can be
 * upgraded to a real popover later if accessibility/styling demand it.
 */

import type { AppointmentState, StageName, StageState, StageRuntime } from "../types";
import { STAGE_ORDER, STAGE_LABELS } from "../types";

const PILL_CLASSES: Record<StageState, string> = {
  not_started: "bg-zinc-700/40 border border-zinc-700",
  processing: "bg-amber-500 border border-amber-400 animate-pulse",
  complete: "bg-emerald-500 border border-emerald-400",
  escalate: "bg-rose-500 border border-rose-400",
  cleared: "bg-transparent border-2 border-emerald-400",
};

const STATE_LABELS: Record<StageState, string> = {
  not_started: "Not Started",
  processing: "Processing",
  complete: "Complete",
  escalate: "Escalated",
  cleared: "Cleared (human-resolved)",
};

function formatDuration(rt: StageRuntime | undefined): string {
  if (!rt?.started_at) return "";
  if (!rt.finished_at) return " (running)";
  const ms = new Date(rt.finished_at).getTime() - new Date(rt.started_at).getTime();
  return ` (${(ms / 1000).toFixed(1)}s)`;
}

interface PipelinePillsProps {
  appointment: AppointmentState;
  size?: "sm" | "md";
}

export function PipelinePills({ appointment, size = "md" }: PipelinePillsProps) {
  const dim = size === "sm" ? "w-4 h-2" : "w-5 h-2.5";
  return (
    <div className="flex items-center gap-1">
      {STAGE_ORDER.map((stage: StageName, i) => {
        const state = appointment.stage_states[stage];
        const rt = appointment.stage_runtimes[stage];
        const tip = `Stage ${i + 1}: ${STAGE_LABELS[stage]} — ${STATE_LABELS[state]}${formatDuration(rt)}`;
        return (
          <div
            key={stage}
            title={tip}
            aria-label={tip}
            className={`${dim} rounded-full transition-colors duration-300 ${PILL_CLASSES[state]}`}
          />
        );
      })}
    </div>
  );
}
