"""Stage 1 agent: Eligibility Verification.

Real-world responsibility: verify the patient's insurance coverage is active
and matches the requested service. Common failure modes: missing insurance
ID on file, expired coverage, payer API timeouts, out-of-network plans.

In the facade this is a simulated agent — no real payer API calls. The
Complete vs Escalate decision is a weighted random roll governed by
`AgentTuning.escalation_probability`. The four-entry catalog is the source
of variety the Exception Queue surfaces during demo.

Contract (locked here, replicated by stages 2-6 at step 5):
  - Async function: `AppointmentState in -> AppointmentState out`.
  - Records its own runtime metadata on `stage_runtimes[STAGE]`.
  - Returns terminal state (Complete or Escalate) for this stage; does not
    set Processing and does not advance `current_stage`. The orchestrator
    (step 6) owns both responsibilities.
  - RNG is injected so tests are deterministic. Default = fresh `Random()`.
"""

from __future__ import annotations

import random
from typing import Optional

from app.agents._runtime import (
    DEMO_TUNING,
    AgentTuning,
    EscalationCandidate,
    build_escalation_reason,
    maybe_pick_escalation,
    simulate_work,
    utc_now,
)
from app.state import (
    AppointmentState,
    StageName,
    StageRuntime,
    StageState,
)

STAGE = StageName.ELIGIBILITY_VERIFICATION


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="member_id_mismatch",
        message=(
            "Member ID on file does not match the carrier's records, or "
            "is missing entirely. Eligibility check cannot proceed."
        ),
        suggested_action=(
            "Contact patient or referring office to retrieve the correct "
            "insurance card details; supply via informational resolution."
        ),
        weight=3.0,
        extra_context={
            "member_id_field": None,
            "last_known_carrier": "unknown",
            "carrier_lookup_attempts": 2,
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="payer_api_timeout",
        message=(
            "Payer eligibility API did not respond within 10 seconds. "
            "Cannot confirm coverage automatically."
        ),
        suggested_action=(
            "Wait for carrier portal uptime confirmation; retry once "
            "available. Concierge can mark resolved with retry instruction."
        ),
        weight=2.0,
        extra_context={
            "payer_endpoint": "eligibility/v2/check",
            "timeout_seconds": 10,
            "request_id": "REQ-pending",
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="coverage_inactive",
        message=(
            "Patient's insurance plan is inactive or terminated as of the "
            "appointment date. Carrier confirmed coverage is not in force."
        ),
        suggested_action=(
            "Discuss self-pay or alternative coverage with patient; "
            "decisional resolution if rebooking under new plan."
        ),
        weight=2.0,
        extra_context={
            "carrier_response": "coverage_terminated",
            "termination_date": "2026-04-01",
            "lookup_method": "carrier_portal_api",
        },
        default_resolution_mode="decisional",
    ),
]


async def eligibility_verification(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Eligibility Verification stage.

    Pre-conditions (caller's responsibility, not enforced here so test
    callers can exercise the agent in isolation):
      - state.current_stage == STAGE
      - state.stage_states[STAGE] in (NOT_STARTED, PROCESSING)

    Returns: an updated AppointmentState with:
      - stage_states[STAGE] set to COMPLETE or ESCALATE
      - stage_runtimes[STAGE] populated (started_at, finished_at, attempt=1)
      - escalation_reason set if escalating
      - updated_at moved to finished_at
    """
    if rng is None:
        rng = random.Random()

    started_at = utc_now()
    await simulate_work(rng, tuning)
    finished_at = utc_now()

    runtime = StageRuntime(started_at=started_at, finished_at=finished_at)
    candidate = maybe_pick_escalation(rng, CATALOG, tuning)

    new_stage_states = {**state.stage_states}
    new_stage_runtimes = {**state.stage_runtimes, STAGE: runtime}

    if candidate is None:
        new_stage_states[STAGE] = StageState.COMPLETE
        return state.model_copy(
            update={
                "stage_states": new_stage_states,
                "stage_runtimes": new_stage_runtimes,
                "updated_at": finished_at,
            }
        )

    new_stage_states[STAGE] = StageState.ESCALATE
    escalation = build_escalation_reason(
        candidate=candidate,
        appointment_id=state.appointment_id,
        patient_name=state.patient_name,
        raised_at=finished_at,
        raised_at_stage=STAGE,
    )
    return state.model_copy(
        update={
            "stage_states": new_stage_states,
            "stage_runtimes": new_stage_runtimes,
            "escalation_reason": escalation,
            "updated_at": finished_at,
        }
    )
