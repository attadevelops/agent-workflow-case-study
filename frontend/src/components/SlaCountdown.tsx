/**
 * Live SLA countdown. Re-renders every second via the shared useNow clock.
 *
 * Visual urgency tiers (color tinting):
 *   < 0           OVERDUE — rose, weighted
 *   < 1h          amber
 *   < 24h         zinc-200 (default attention)
 *   ≥ 24h         zinc-500 (calm)
 */

import { useNow } from "../lib/useNow";

interface SlaCountdownProps {
  dueIso: string;
  className?: string;
}

function formatDelta(absMs: number): string {
  const totalSec = Math.floor(absMs / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const min = Math.floor((totalSec % 3600) / 60);
  const sec = totalSec % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${min}m`;
  if (min > 0) return `${min}m ${sec}s`;
  return `${sec}s`;
}

export function SlaCountdown({ dueIso, className }: SlaCountdownProps) {
  const now = useNow(1000);
  const dueMs = new Date(dueIso).getTime();
  const diffMs = dueMs - now;
  const overdue = diffMs < 0;
  const text = formatDelta(Math.abs(diffMs));

  let tone = "text-zinc-500";
  if (overdue) tone = "text-rose-400 font-medium";
  else if (diffMs < 3_600_000) tone = "text-amber-400";
  else if (diffMs < 86_400_000) tone = "text-zinc-200";

  return (
    <span className={`font-mono text-xs tabular-nums ${tone} ${className ?? ""}`}>
      {overdue ? `OVERDUE ${text}` : text}
    </span>
  );
}
