/**
 * Per-stage workload chips above the table. Answers "where is the work
 * right now?" at a glance — and surfaces the per-stage escalation
 * concentration the orchestrator's scheduler sees.
 *
 * For each stage:
 *   in_progress = appointments currently parked at this stage with a
 *                 non-escalated state (not_started or processing).
 *   escalated   = appointments whose state at this stage is escalate.
 *
 * Counts are computed client-side from the polled list. No backend agg.
 */

import type { AppointmentState, StageName } from "../types";
import { STAGE_ORDER, STAGE_LABELS } from "../types";

interface StageBreakdownProps {
  appointments: AppointmentState[];
}

interface StageCount {
  stage: StageName;
  index: number;
  in_progress: number;
  escalated: number;
}

function compute(appts: AppointmentState[]): StageCount[] {
  return STAGE_ORDER.map((stage, index) => {
    let in_progress = 0;
    let escalated = 0;
    for (const a of appts) {
      const s = a.stage_states[stage];
      if (s === "escalate") escalated += 1;
      else if (a.current_stage === stage && s !== "complete" && s !== "cleared") {
        in_progress += 1;
      }
    }
    return { stage, index, in_progress, escalated };
  });
}

export function StageBreakdown({ appointments }: StageBreakdownProps) {
  const counts = compute(appointments);
  return (
    <div className="flex flex-wrap gap-2">
      {counts.map(({ stage, index, in_progress, escalated }) => {
        const idle = in_progress === 0 && escalated === 0;
        return (
          <div
            key={stage}
            className={`px-3 py-1.5 rounded-md text-xs flex items-center gap-2 border ${
              idle
                ? "bg-zinc-900/30 border-zinc-800/60 text-zinc-600"
                : "bg-zinc-900/60 border-zinc-800 text-zinc-300"
            }`}
            title={`${STAGE_LABELS[stage]}: ${in_progress} in progress, ${escalated} escalated`}
          >
            <span className="font-mono text-zinc-500">S{index + 1}</span>
            <span className="hidden lg:inline">{STAGE_LABELS[stage]}</span>
            <span className="lg:hidden">{STAGE_LABELS[stage].split(" ")[0]}</span>
            <span className="flex items-center gap-1.5 ml-1">
              {in_progress > 0 && (
                <span className="font-mono text-amber-400">{in_progress}↺</span>
              )}
              {escalated > 0 && (
                <span className="font-mono text-rose-400">{escalated}!</span>
              )}
              {idle && <span className="font-mono text-zinc-700">·</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}
