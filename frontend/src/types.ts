/**
 * Hand-mirrored from backend/app/state.py.
 *
 * Sync rule (per CLAUDE.md): when state.py changes, edit this file. Do not
 * generate. The hand-mirroring is a forcing function — every wire-shape
 * change is a deliberate edit, not a regen artifact.
 *
 * Datetime convention: all datetimes cross the wire as ISO 8601 strings.
 * No Date objects. The frontend formats for display at the leaf component.
 */

// ──────────────────────────────────────────────────────────────────────────
// Enums (string-literal unions; mirror StrEnum on the backend)
// ──────────────────────────────────────────────────────────────────────────

export type StageName =
  | "eligibility_verification"
  | "prior_authorization"
  | "patient_intake"
  | "referral_validation"
  | "pre_visit_questionnaire"
  | "appointment_confirmation";

export const STAGE_ORDER: StageName[] = [
  "eligibility_verification",
  "prior_authorization",
  "patient_intake",
  "referral_validation",
  "pre_visit_questionnaire",
  "appointment_confirmation",
];

// Display labels for the dashboard pills and Exception Queue. Keep in
// alignment with backend StageName values; this is the only place we
// human-format the stage names.
export const STAGE_LABELS: Record<StageName, string> = {
  eligibility_verification: "Eligibility Verification",
  prior_authorization: "Prior Authorization",
  patient_intake: "Patient Intake",
  referral_validation: "Referral Validation",
  pre_visit_questionnaire: "Pre-Visit Questionnaire",
  appointment_confirmation: "Appointment Confirmation",
};

export type StageState =
  | "not_started"
  | "processing"
  | "complete"
  | "escalate"
  | "cleared";

export const TERMINAL_STAGE_STATES: ReadonlySet<StageState> = new Set([
  "complete",
  "cleared",
]);

export type Specialty =
  | "cardiology"
  | "orthopedics"
  | "dermatology"
  | "primary_care";

export type ClientId = "C-NORTHWELL" | "C-MERCY" | "C-VALLEY";

// ──────────────────────────────────────────────────────────────────────────
// Sub-models
// ──────────────────────────────────────────────────────────────────────────

export interface EscalationReason {
  code: string;
  message: string;
  suggested_action: string | null;
  agent_context: Record<string, unknown>;
  raised_at: string; // ISO 8601
  raised_at_stage: StageName;
  // Catalog hint: how this code is normally resolved. Frontend pre-selects
  // the resolution form's mode toggle from this; human concierge may override.
  default_resolution_mode: ResolutionMode;
}

export type ResolutionMode = "decisional" | "informational";

export interface ConciergeResolution {
  note: string;
  resolved_at: string; // ISO 8601
  resolver_id: string;
  resolved_stage: StageName;
  resolved_code: string;
  // "decisional" — human judgment supersedes; workflow advances to N+1.
  // "informational" — human supplies data; stage N re-runs.
  resolution_type: ResolutionMode;
  // Set on informational resolutions; consumed by the agent on re-run.
  payload: Record<string, unknown> | null;
}

export interface StageRuntime {
  started_at: string | null; // ISO 8601
  finished_at: string | null; // ISO 8601
  attempt: number;
}

// ──────────────────────────────────────────────────────────────────────────
// Aggregate root
// ──────────────────────────────────────────────────────────────────────────

export interface AppointmentState {
  // Identity
  appointment_id: string;
  patient_name: string;
  specialty: Specialty;
  procedure: string; // Clinical procedure/visit reason. Display-only.
  client_id: ClientId;

  // Scheduling
  created_at: string;
  updated_at: string;
  sla_due_at: string;
  eligible_to_run_at: string;

  // Pipeline state
  stage_states: Record<StageName, StageState>;
  current_stage: StageName | null; // null = pipeline complete
  // Sparse: only stages that have been invoked have an entry.
  stage_runtimes: Partial<Record<StageName, StageRuntime>>;

  // Priority (populated per tick by the active strategy)
  priority_score: number | null;
  priority_reasoning: string | null;

  // Escalation
  escalation_reason: EscalationReason | null;
  resolutions: ConciergeResolution[];
  // Working slot for the most recent INFORMATIONAL resolution. Set by the
  // orchestrator on informational resume; consumed and cleared by the
  // agent-node wrapper after the stage's agent re-runs. Null otherwise.
  last_resolution: ConciergeResolution | null;
}

// ──────────────────────────────────────────────────────────────────────────
// Derived selectors (derived appointment-level status — not stored)
// ──────────────────────────────────────────────────────────────────────────

/**
 * Why selectors live here, not in the dashboard:
 * The frontend filter UI ("In Progress", "Escalated", "Completed", "Resolved")
 * derives its categories from the same predicates the backend uses for
 * orchestrator selection. Centralizing them here keeps backend and frontend
 * filter semantics aligned.
 */

export const isEscalated = (a: AppointmentState): boolean =>
  a.escalation_reason !== null;

export const isCompleted = (a: AppointmentState): boolean =>
  STAGE_ORDER.every((s) => TERMINAL_STAGE_STATES.has(a.stage_states[s]));

export const isInProgress = (a: AppointmentState): boolean =>
  !isEscalated(a) && !isCompleted(a);

// "Resolved" is the lifetime fact that this appointment has had at least one
// escalation cleared. See decisions.md for why we renamed Cleared → Resolved
// at the dashboard filter level.
export const hasResolutions = (a: AppointmentState): boolean =>
  a.resolutions.length > 0;
