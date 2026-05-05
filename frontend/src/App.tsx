/**
 * Root component.
 *
 * View switching is a single state variable (no router). Polling lives in
 * the usePollingData hook and is shared with both views via props.
 */

import { useState } from "react";
import { TopNav, type ViewName } from "./components/TopNav";
import { Dashboard } from "./views/Dashboard";
import { ExceptionQueue } from "./views/ExceptionQueue";
import { usePollingData } from "./lib/usePollingData";

function App() {
  const [view, setView] = useState<ViewName>("dashboard");
  const data = usePollingData(2000);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <TopNav
        active={view}
        onChange={setView}
        exceptionCount={data.exceptions.length}
        strategyName={data.health?.strategy ?? null}
        onAdminAction={data.refresh}
      />
      <main className="max-w-[1400px] mx-auto px-6 py-6">
        {view === "dashboard" ? (
          <Dashboard data={data} />
        ) : (
          <ExceptionQueue data={data} />
        )}
      </main>
    </div>
  );
}

export default App;
