/**
 * Resolution form. The most architecturally meaningful interaction in the demo:
 * the human concierge picks between two semantically distinct resolution paths.
 *
 *   Decisional      The human's judgment supersedes the agent's escalation.
 *                   Workflow advances to the next stage. No data flows into the
 *                   agent. Use when the issue is "agent was being conservative,
 *                   I've assessed the situation, proceed."
 *
 *   Informational   The human supplies missing data. The current stage re-runs
 *                   with the resolution payload available to the agent (via
 *                   AppointmentState.last_resolution.payload). Use when the
 *                   issue is "agent needed X, here's X, try again."
 *
 * The toggle is pre-selected from EscalationReason.default_resolution_mode
 * (the catalog's hint), but the human may override.
 *
 * The payload textarea only appears for Informational. Empty / whitespace-only
 * payloads are sent as null. JSON parse errors block submit with inline help.
 */

import { useEffect, useState } from "react";
import { resolveException } from "../api";
import type { ResolutionMode } from "../types";

interface ResolutionFormProps {
  appointmentId: string;
  defaultMode: ResolutionMode;
  onResolved?: () => void;
}

const MODE_HELP: Record<ResolutionMode, string> = {
  decisional:
    "Makes a judgment call. Workflow advances to the next stage; no data flows back to the agent.",
  informational:
    "Supplies missing data. Current stage re-runs with the payload available to the agent.",
};

const SUBMIT_LABEL: Record<ResolutionMode, string> = {
  decisional: "Mark Cleared & Resume",
  informational: "Submit Data & Re-run",
};

export function ResolutionForm({
  appointmentId,
  defaultMode,
  onResolved,
}: ResolutionFormProps) {
  const [mode, setMode] = useState<ResolutionMode>(defaultMode);
  const [note, setNote] = useState("");
  const [payloadText, setPayloadText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If a different escalation lands on the same card slot (rare but
  // possible during a live tick), reset the mode to the new default.
  useEffect(() => {
    setMode(defaultMode);
  }, [defaultMode]);

  const trimmedPayload = payloadText.trim();
  let parsedPayload: Record<string, unknown> | null = null;
  let payloadParseError: string | null = null;
  if (mode === "informational" && trimmedPayload.length > 0) {
    try {
      const parsed = JSON.parse(trimmedPayload);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        parsedPayload = parsed as Record<string, unknown>;
      } else {
        payloadParseError = "Payload must be a JSON object (e.g. {\"key\": \"value\"}).";
      }
    } catch (e) {
      payloadParseError = `Invalid JSON: ${(e as Error).message}`;
    }
  }

  const canSubmit = !submitting && (mode === "decisional" || !payloadParseError);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await resolveException(appointmentId, {
        note: note.trim(),
        resolution_type: mode,
        payload: mode === "informational" ? parsedPayload : null,
      });
      if (onResolved) onResolved();
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-md bg-zinc-950/40 border border-zinc-800 p-3 space-y-3"
    >
      <div>
        <div className="text-[11px] uppercase tracking-wider font-mono text-zinc-500 mb-1.5">
          Resolution mode
        </div>
        <div className="flex gap-2">
          <ModeButton
            label="Decisional"
            active={mode === "decisional"}
            recommended={defaultMode === "decisional"}
            onClick={() => setMode("decisional")}
          />
          <ModeButton
            label="Informational"
            active={mode === "informational"}
            recommended={defaultMode === "informational"}
            onClick={() => setMode("informational")}
          />
        </div>
        <p className="mt-2 text-xs text-zinc-400">{MODE_HELP[mode]}</p>
      </div>

      <div>
        <label
          htmlFor={`note-${appointmentId}`}
          className="block text-[11px] uppercase tracking-wider font-mono text-zinc-500 mb-1.5"
        >
          Concierge note
        </label>
        <textarea
          id={`note-${appointmentId}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder={
            mode === "decisional"
              ? "e.g. confirmed coverage with patient by phone"
              : "e.g. patient supplied corrected member ID via portal"
          }
          className="w-full px-2.5 py-1.5 rounded-md bg-zinc-900 border border-zinc-800 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 resize-none"
        />
      </div>

      {mode === "informational" && (
        <div>
          <label
            htmlFor={`payload-${appointmentId}`}
            className="block text-[11px] uppercase tracking-wider font-mono text-zinc-500 mb-1.5"
          >
            Payload (JSON object, optional)
          </label>
          <textarea
            id={`payload-${appointmentId}`}
            value={payloadText}
            onChange={(e) => setPayloadText(e.target.value)}
            rows={3}
            spellCheck={false}
            placeholder='{"member_id": "M-12345-CORRECTED"}'
            className={`w-full px-2.5 py-1.5 rounded-md bg-zinc-900 border text-sm font-mono text-zinc-100 placeholder:text-zinc-700 focus:outline-none ${
              payloadParseError
                ? "border-rose-700 focus:border-rose-500"
                : "border-zinc-800 focus:border-zinc-600"
            }`}
          />
          {payloadParseError && (
            <p className="mt-1 text-xs text-rose-400 font-mono">
              {payloadParseError}
            </p>
          )}
          {!payloadParseError && trimmedPayload.length === 0 && (
            <p className="mt-1 text-xs text-zinc-600">
              Empty payload is allowed; the agent will re-run with no extra
              data, but `last_resolution.note` is still available.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="text-xs text-rose-400 font-mono">
          Resolve failed: {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className={`w-full px-3 py-2 rounded-md text-sm font-medium transition-colors ${
          mode === "decisional"
            ? "bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700"
            : "bg-sky-600 hover:bg-sky-500 active:bg-sky-700"
        } disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        {submitting ? "Submitting…" : SUBMIT_LABEL[mode]}
      </button>
    </form>
  );
}

function ModeButton({
  label,
  active,
  recommended,
  onClick,
}: {
  label: string;
  active: boolean;
  recommended: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
        active
          ? "bg-zinc-100 text-zinc-900 border-zinc-100"
          : "bg-zinc-900 text-zinc-300 border-zinc-800 hover:border-zinc-600"
      }`}
    >
      {label}
      {recommended && (
        <span
          className={`ml-1.5 text-[10px] font-mono ${
            active ? "text-zinc-500" : "text-emerald-400"
          }`}
          title="Catalog default for this escalation code"
        >
          ★
        </span>
      )}
    </button>
  );
}
