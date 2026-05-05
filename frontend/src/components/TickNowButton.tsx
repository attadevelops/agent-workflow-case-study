/**
 * Manual tick control. Hits POST /admin/tick.
 *
 * This is Atta's pacing control during the live demo: when he wants to
 * advance the orchestrator on his cue rather than waiting for the
 * background tick (default every 4s).
 */

import { useCallback, useState } from "react";
import { adminTick } from "../api";

interface TickNowButtonProps {
  onAfterTick?: () => Promise<void> | void;
}

export function TickNowButton({ onAfterTick }: TickNowButtonProps) {
  const [busy, setBusy] = useState(false);
  const [lastTicked, setLastTicked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handle = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await adminTick();
      setLastTicked(r.ticked);
      if (onAfterTick) await onAfterTick();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [onAfterTick]);

  return (
    <div className="flex items-center gap-2">
      {lastTicked && !error && (
        <span className="text-xs font-mono text-zinc-500 hidden sm:inline">
          last: {lastTicked}
        </span>
      )}
      {error && (
        <span className="text-xs font-mono text-rose-400" title={error}>
          err
        </span>
      )}
      <button
        type="button"
        onClick={handle}
        disabled={busy}
        className="px-3 py-1.5 rounded-md text-sm font-medium bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {busy ? "Ticking…" : "Tick Now"}
      </button>
    </div>
  );
}
