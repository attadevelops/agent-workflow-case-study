"""Stage 6 agent: Appointment Confirmation.

Real-world responsibility: final confirmation pass before the appointment
date — verify patient is reachable, that scheduling has not drifted, that
upstream stage data is coherent, and that any logistical needs (transport,
interpreter, mobility assistance) are arranged.

Common failure modes: patient unreachable, last-minute scheduling conflict
on the provider side, an upstream stage's record turning out stale at
confirmation time, transport assistance flagged but not arranged.

Same contract as eligibility_verification (see that file's docstring for
the agent contract spec).
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

STAGE = StageName.APPOINTMENT_CONFIRMATION


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="patient_unreachable",
        message=(
            "Failed to reach patient for confirmation across SMS, email, "
            "and phone after 3 attempts. Cannot confirm appointment."
        ),
        suggested_action=(
            "One more attempt with alternate contact (emergency contact "
            "or referring office); if no luck, mark as a likely no-show "
            "and free the slot 24h before."
        ),
        weight=2.5,
        extra_context={
            "outreach_attempts": 3,
            "last_attempt_channel": "phone",
            "alt_contact_available": True,
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="scheduling_conflict_detected",
        message=(
            "Provider has an overlapping commitment that was not flagged "
            "at booking time. Confirmation cannot proceed without resolution."
        ),
        suggested_action=(
            "Coordinate with scheduling team to either move the conflicting "
            "commitment or reschedule this appointment to the next available slot."
        ),
        weight=1.5,
        extra_context={
            "conflict_type": "provider_double_booking",
            "conflicting_appointment": "OTHER-pending",
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="prior_stage_unresolved",
        message=(
            "Upstream stage data is incoherent at confirmation time "
            "(eligibility marked verified but coverage status drifted). "
            "Cannot safely confirm without re-validation."
        ),
        suggested_action=(
            "Re-run eligibility verification or escalate to the ops lead "
            "to inspect the data inconsistency."
        ),
        weight=1.0,
        extra_context={
            "drifted_stage": "eligibility_verification",
            "drift_indicator": "coverage_status_changed_post_verification",
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="transport_arrangement_needed",
        message=(
            "Patient indicated a need for transport assistance during intake "
            "but no arrangement is in place. Visit cannot be confirmed safely."
        ),
        suggested_action=(
            "Engage social services or insurance-provided NEMT to schedule "
            "transport for both legs of the appointment."
        ),
        weight=2.0,
        extra_context={
            "transport_type_requested": "wheelchair_accessible",
            "arrangement_status": "not_started",
        },
        default_resolution_mode="decisional",
    ),
]


async def appointment_confirmation(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Appointment Confirmation stage."""
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
