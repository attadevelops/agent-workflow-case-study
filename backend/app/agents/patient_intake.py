"""Stage 3 agent: Patient Intake.

Real-world responsibility: gather and verify the patient's demographic
data, emergency contacts, current medication list, and other pre-visit
record requirements. Common failure modes: missing emergency contact,
demographic data drift between source systems, patient unresponsive to
intake outreach, stale or empty medication list.

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

STAGE = StageName.PATIENT_INTAKE


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="missing_emergency_contact",
        message=(
            "Patient record has no emergency contact on file. "
            "Ops policy requires one before the appointment."
        ),
        suggested_action=(
            "Reach out to patient via portal or phone; capture contact "
            "name, relationship, and phone before check-in."
        ),
        weight=2.0,
        extra_context={
            "required_field": "emergency_contact",
            "policy_ref": "OPS-INTAKE-04",
            "outreach_channels_available": ["sms", "phone"],
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="demographic_mismatch",
        message=(
            "Patient demographic data on file (DOB, address, name spelling) "
            "does not match the insurance carrier's records."
        ),
        suggested_action=(
            "Confirm the canonical demographics with the patient; update "
            "the record or insurance file as appropriate before billing runs."
        ),
        weight=2.0,
        extra_context={
            "mismatched_fields": ["address", "dob"],
            "source_of_truth": "patient_self_report_pending",
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="patient_unresponsive_to_outreach",
        message=(
            "Patient did not respond to intake outreach across SMS, email, "
            "and voicemail. Pre-appointment data remains incomplete."
        ),
        suggested_action=(
            "Plan to administer intake at check-in; flag the appointment "
            "for an extra 15-minute buffer."
        ),
        weight=2.0,
        extra_context={
            "outreach_attempts": 3,
            "last_attempt_channel": "voicemail",
            "preferred_contact_method": "sms",
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="incomplete_medication_list",
        message=(
            "Patient's medication list is empty or was last updated more "
            "than 12 months ago. Provider needs an accurate current list."
        ),
        suggested_action=(
            "Send a structured medication review form to patient, or "
            "schedule a brief pre-visit call with the MA."
        ),
        weight=1.5,
        extra_context={
            "med_list_last_updated": "2024-09-01",
            "med_list_count": 0,
        },
        default_resolution_mode="informational",
    ),
]


async def patient_intake(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Patient Intake stage."""
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
