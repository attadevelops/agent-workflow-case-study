"""
Domain state for the Agentic Workflow Management facade.

The single source of truth for what flows through the LangGraph orchestrator
and what the FastAPI surface serves to the frontend.

Design notes (long-form rationale lives in /decisions.md):
- StrEnum so JSON serialization is the string value, not "StageName.X".
- `stage_states` is the canonical record of what happened at each stage.
  `current_stage` is the orchestrator's cursor, separate by design.
- `priority_score` and `priority_reasoning` live on AppointmentState (not on
  a wrapper) so the wire shape stays single-typed for the frontend.
- `escalation_reason` is 0..1 (active). Resolution history lives in
  `resolutions`, append-only.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ResolutionMode = Literal["decisional", "informational"]


# ──────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────


class StageName(StrEnum):
    """The 6 locked stages, in pipeline order. See STAGE_ORDER for the order."""

    ELIGIBILITY_VERIFICATION = "eligibility_verification"
    PRIOR_AUTHORIZATION = "prior_authorization"
    PATIENT_INTAKE = "patient_intake"
    REFERRAL_VALIDATION = "referral_validation"
    PRE_VISIT_QUESTIONNAIRE = "pre_visit_questionnaire"
    APPOINTMENT_CONFIRMATION = "appointment_confirmation"


# Canonical pipeline order. Used by the orchestrator to advance, and by the
# frontend to render the pipeline pills left-to-right. Source of truth.
STAGE_ORDER: list[StageName] = [
    StageName.ELIGIBILITY_VERIFICATION,
    StageName.PRIOR_AUTHORIZATION,
    StageName.PATIENT_INTAKE,
    StageName.REFERRAL_VALIDATION,
    StageName.PRE_VISIT_QUESTIONNAIRE,
    StageName.APPOINTMENT_CONFIRMATION,
]


class StageState(StrEnum):
    """Per-stage state. The 4 from the brief plus Cleared (concierge resolution)."""

    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ESCALATE = "escalate"
    CLEARED = "cleared"


# Set of states that count as "stage is done, advance the cursor". Cleared is
# treated identically to Complete for orchestrator advancement (per decisions.md).
TERMINAL_STAGE_STATES: set[StageState] = {StageState.COMPLETE, StageState.CLEARED}


class Specialty(StrEnum):
    CARDIOLOGY = "cardiology"
    ORTHOPEDICS = "orthopedics"
    DERMATOLOGY = "dermatology"
    PRIMARY_CARE = "primary_care"


class ClientId(StrEnum):
    NORTHWELL = "C-NORTHWELL"
    MERCY = "C-MERCY"
    VALLEY = "C-VALLEY"


# ──────────────────────────────────────────────────────────────────────────
# Sub-models
# ──────────────────────────────────────────────────────────────────────────


class EscalationReason(BaseModel):
    """Structured payload an agent emits when returning Escalate.

    The Exception Queue UI consumes this directly. `code` is machine-readable
    (used for filtering / grouping); `message` is human-readable; `agent_context`
    is whatever the agent saw, rendered as a collapsible JSON pane.

    `default_resolution_mode` is the catalog's hint about how this code is
    normally resolved (decisional vs. informational). Frontend pre-selects
    the resolution form's mode toggle from this field; the human concierge
    may override before submitting.
    """

    code: str
    message: str
    suggested_action: str | None = None
    agent_context: dict[str, Any] = Field(default_factory=dict)
    raised_at: datetime
    raised_at_stage: StageName
    default_resolution_mode: ResolutionMode = "decisional"


class ConciergeResolution(BaseModel):
    """One resolution event. Append-only history; an appointment can have many
    over its lifetime as different stages escalate independently.

    `resolution_type` captures whether the human's resolution supersedes the
    agent's judgment ("decisional", workflow advances) or supplies missing
    data the agent should re-evaluate ("informational", stage re-runs).
    Defaults to "decisional" — preserves the original single-mode semantic
    when the field is omitted from a payload.

    `payload` carries informational resolution data (e.g., a corrected
    member ID, a re-uploaded referral). The agent reads it from
    `AppointmentState.last_resolution.payload` on re-run.
    """

    note: str
    resolved_at: datetime
    resolver_id: str = "concierge_demo"
    resolved_stage: StageName
    # Echo of the EscalationReason this resolved, for audit trail.
    resolved_code: str
    resolution_type: ResolutionMode = "decisional"
    payload: dict[str, Any] | None = None


class StageRuntime(BaseModel):
    """Per-stage execution record. Sparse on AppointmentState — only stages
    that have been invoked (or are running) have an entry in stage_runtimes.

    The agent populates `started_at` on entry and `finished_at` before return.
    `attempt` is forward-compat for v2 retry semantics; v1 never increments it
    (escalation is the failure mode), so attempt is always 1.
    """

    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt: int = 1


# ──────────────────────────────────────────────────────────────────────────
# Aggregate root
# ──────────────────────────────────────────────────────────────────────────


def _default_stage_states() -> dict[StageName, StageState]:
    return {stage: StageState.NOT_STARTED for stage in STAGE_ORDER}


class AppointmentState(BaseModel):
    """The single Pydantic model that flows through every node in the graph.

    Naming nuance: this is named `AppointmentState` (not `Appointment`) because
    LangGraph's `StateGraph` operates over a state object — that's the type
    name the framework expects to see.
    """

    # ── Identity ─────────────────────────────────────────────────────
    appointment_id: str
    patient_name: str
    specialty: Specialty
    procedure: str  # Clinical procedure/visit reason. Display-only on the dashboard.
    client_id: ClientId

    # ── Scheduling ───────────────────────────────────────────────────
    created_at: datetime
    updated_at: datetime
    sla_due_at: datetime
    # Production: don't run pipeline until T-24h before appointment.
    # Demo: usually equals created_at. Modeled but not enforced. See decisions.md.
    eligible_to_run_at: datetime

    # ── Pipeline state ───────────────────────────────────────────────
    # All 6 stages always present. Validator below enforces this.
    stage_states: dict[StageName, StageState] = Field(default_factory=_default_stage_states)
    # Cursor: next stage to run, currently running, or just-escalated stage.
    # None when the pipeline is fully complete.
    current_stage: StageName | None = StageName.ELIGIBILITY_VERIFICATION
    # Sparse: only stages that have been invoked have an entry. Populated by
    # agents on entry/exit so the dashboard can show per-stage durations.
    stage_runtimes: dict[StageName, StageRuntime] = Field(default_factory=dict)

    # ── Priority (populated by the active strategy on each tick) ─────
    # Strategy contract: at least one of these is populated after rank().
    # WeightedSum populates `priority_score`; LLMRule populates `priority_reasoning`.
    priority_score: float | None = None
    priority_reasoning: str | None = None

    # ── Escalation ───────────────────────────────────────────────────
    # Active escalation only. Cleared by the orchestrator after concierge resolution.
    escalation_reason: EscalationReason | None = None
    # Append-only history. Survives across multiple escalation/resolution cycles.
    resolutions: list[ConciergeResolution] = Field(default_factory=list)
    # Working slot for the most recent INFORMATIONAL resolution. Set by the
    # orchestrator's exception node on informational resume; consumed and
    # cleared by the agent-node wrapper after the stage's agent re-runs.
    # None for decisional resolutions (those don't propagate data into the
    # agent — they only advance the cursor).
    last_resolution: ConciergeResolution | None = None

    # ── Validators ───────────────────────────────────────────────────

    @field_validator("stage_states")
    @classmethod
    def _all_stages_present(
        cls, v: dict[StageName, StageState]
    ) -> dict[StageName, StageState]:
        missing = set(STAGE_ORDER) - set(v.keys())
        if missing:
            raise ValueError(f"stage_states missing required stages: {sorted(missing)}")
        return v

    @model_validator(mode="after")
    def _coherent_escalation(self) -> AppointmentState:
        # If escalation_reason is set, some stage must be in Escalate state.
        # Catches drift where the orchestrator forgets to clear one or the other.
        if self.escalation_reason is not None:
            if not any(s == StageState.ESCALATE for s in self.stage_states.values()):
                raise ValueError(
                    "escalation_reason is set but no stage is in Escalate state"
                )
        return self


# ──────────────────────────────────────────────────────────────────────────
# Priority strategy contract
# ──────────────────────────────────────────────────────────────────────────


class PriorityContext(BaseModel):
    """Inputs the strategy may use beyond the appointment list itself.

    Lives as a typed model (not dict) because the LLM strategy's `rules` field
    is the highest-signal config in the system — it deserves a typed home.
    """

    # Per-client multiplier (e.g., {"C-NORTHWELL": 1.5}). Used by WeightedSum.
    client_weights: dict[ClientId, float] = Field(default_factory=dict)
    # Per-specialty multiplier. Used by WeightedSum.
    specialty_weights: dict[Specialty, float] = Field(default_factory=dict)
    # Free-text rules string. Used by LLMRule. Example:
    #   "Premium clients first; oncology before dermatology;
    #    appointments due within 48h get max boost."
    rules: str | None = None
    # When this rank was computed. Strategies may read for SLA-relative scoring.
    now: datetime


# Note: the PriorityStrategy interface itself (rank() function) lives in
# orchestrator.py at step 6/7. The state module owns only the data contracts.
