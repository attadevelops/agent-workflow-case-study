/**
 * Strategy switcher. The single best architecture-as-spectacle moment in
 * the demo: live-swap WeightedSum ⇄ LLMRule and watch the priority
 * ranking shift in real time.
 *
 * One interaction (a select), not buried in settings. Visible on both views.
 */

import { useCallback, useState } from "react";
import { adminSetStrategy } from "../api";

type StrategyName = "weighted_sum" | "llm_rule";

interface StrategySwitcherProps {
  current: string | null;
  onAfterSwap?: () => Promise<void> | void;
}

const LABELS: Record<StrategyName, string> = {
  weighted_sum: "WeightedSum",
  llm_rule: "LLMRule (mock)",
};

export function StrategySwitcher({
  current,
  onAfterSwap,
}: StrategySwitcherProps) {
  const [busy, setBusy] = useState(false);

  const value: StrategyName =
    current === "llm_rule" ? "llm_rule" : "weighted_sum";

  const handle = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const next = e.target.value as StrategyName;
      setBusy(true);
      try {
        await adminSetStrategy(next);
        if (onAfterSwap) await onAfterSwap();
      } finally {
        setBusy(false);
      }
    },
    [onAfterSwap]
  );

  return (
    <div className="flex items-center gap-2">
      <label className="text-xs font-mono text-zinc-500">strategy</label>
      <select
        value={value}
        onChange={handle}
        disabled={busy}
        className="px-2 py-1 rounded-md text-sm bg-zinc-900 border border-zinc-800 text-zinc-100 hover:border-zinc-700 focus:outline-none focus:border-zinc-600 disabled:opacity-50"
      >
        {(Object.keys(LABELS) as StrategyName[]).map((k) => (
          <option key={k} value={k}>
            {LABELS[k]}
          </option>
        ))}
      </select>
    </div>
  );
}
