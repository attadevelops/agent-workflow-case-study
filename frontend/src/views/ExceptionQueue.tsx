/**
 * Exception Queue view.
 *
 * The named UI/UX evaluation criterion. Lists every appointment whose pipeline
 * is paused on an Escalate, expanded for the human concierge with full context
 * + resolution form per card.
 *
 * Sort order: newest escalation first (raised_at desc). The orchestrator's
 * priority strategy is what gets the appointment escalated; once escalated,
 * "most recent first" is the most useful concierge default — fresh issues
 * are usually fastest to resolve, and the queue acts as a chronological log.
 *
 * No filter UI here (deferred per step 11 scope). When the queue grows
 * past ~10 items in a real demo, sort/filter pays off; the current 5-min
 * walkthrough fits in one scroll.
 */

import type { PollingData } from "../lib/usePollingData";
import { ExceptionCard } from "../components/ExceptionCard";

interface ExceptionQueueProps {
  data: PollingData;
}

export function ExceptionQueue({ data }: ExceptionQueueProps) {
  const { exceptions, error, loading, refresh } = data;

  if (loading && exceptions.length === 0) {
    return (
      <div className="p-6 rounded-lg bg-zinc-900/40 border border-zinc-800">
        Loading exceptions…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 rounded-lg bg-rose-950/30 border border-rose-900/60 font-mono text-sm text-rose-300">
        Backend unreachable: {error.message}
      </div>
    );
  }

  const sorted = [...exceptions].sort((a, b) => {
    const ar = a.escalation_reason?.raised_at ?? "";
    const br = b.escalation_reason?.raised_at ?? "";
    return new Date(br).getTime() - new Date(ar).getTime();
  });

  return (
    <div className="space-y-5">
      <header className="flex items-baseline gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Exception Queue</h1>
        <span className="text-sm text-zinc-500 font-mono">
          {exceptions.length} active escalation
          {exceptions.length === 1 ? "" : "s"} · polled every 2s
        </span>
      </header>

      {sorted.length === 0 ? (
        <div className="p-12 rounded-lg bg-zinc-900/40 border border-zinc-800 text-center">
          <div className="text-zinc-300 mb-1.5 text-base">All clear.</div>
          <div className="text-xs text-zinc-500 font-mono">
            The orchestrator will surface escalations here as they happen.
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {sorted.map((a) => (
            <ExceptionCard
              key={a.appointment_id}
              appointment={a}
              onResolved={refresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}
