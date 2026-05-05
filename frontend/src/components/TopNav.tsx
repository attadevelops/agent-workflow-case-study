/**
 * Top nav: title + view tabs + strategy switcher + Tick Now button.
 *
 * No router. View switching is a single state variable in App.tsx.
 *
 * The strategy switcher and Tick Now button are visible on BOTH views per
 * the demo-control requirement (Atta needs them as live demo controls).
 */

import { StrategySwitcher } from "./StrategySwitcher";
import { TickNowButton } from "./TickNowButton";

export type ViewName = "dashboard" | "exceptions";

interface TopNavProps {
  active: ViewName;
  onChange: (view: ViewName) => void;
  exceptionCount: number;
  strategyName: string | null;
  onAdminAction: () => Promise<void> | void;
}

const tabClass = (isActive: boolean) =>
  [
    "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
    isActive
      ? "bg-zinc-800 text-zinc-50"
      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900",
  ].join(" ");

export function TopNav({
  active,
  onChange,
  exceptionCount,
  strategyName,
  onAdminAction,
}: TopNavProps) {
  return (
    <nav className="border-b border-zinc-800 bg-zinc-950/95 backdrop-blur-sm sticky top-0 z-10">
      <div className="max-w-[1400px] mx-auto px-6 h-14 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="font-semibold text-zinc-100 tracking-tight">
            IKS Workflow
          </span>
          <span className="text-xs text-zinc-500 font-mono">/ orchestrator</span>
        </div>

        <div className="flex gap-1 ml-4">
          <button
            type="button"
            className={tabClass(active === "dashboard")}
            onClick={() => onChange("dashboard")}
          >
            Dashboard
          </button>
          <button
            type="button"
            className={tabClass(active === "exceptions")}
            onClick={() => onChange("exceptions")}
          >
            Exception Queue
            {exceptionCount > 0 && (
              <span className="ml-2 inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-amber-500/20 text-amber-300 text-xs font-mono">
                {exceptionCount}
              </span>
            )}
          </button>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <StrategySwitcher
            current={strategyName}
            onAfterSwap={onAdminAction}
          />
          <TickNowButton onAfterTick={onAdminAction} />
        </div>
      </div>
    </nav>
  );
}
