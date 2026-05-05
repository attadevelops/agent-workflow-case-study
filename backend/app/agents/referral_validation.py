"""Stage 4 agent: Referral Validation.

Real-world responsibility: confirm a valid referral exists for the booked
specialty appointment, signed by the patient's PCP, dated within the plan's
required window, and matching the booked specialty. Common failure modes:
missing PCP signature, referral expired, referral specialty mismatch,
referral simply not on file.

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

STAGE = StageName.REFERRAL_VALIDATION


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="missing_pcp_signature",
        message=(
            "Referral document is on file but is missing the PCP's signature "
            "or stamp. Carrier will not honor unsigned referrals."
        ),
        suggested_action=(
            "Contact PCP office to obtain a signed copy; update record "
            "with the corrected document."
        ),
        weight=2.0,
        extra_context={
            "referral_id": "REF-pending",
            "missing_field": "pcp_signature",
            "carrier_requirement": "signature_required",
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="expired_referral",
        message=(
            "Referral on file is dated more than 90 days ago. Carrier "
            "considers this expired; a fresh referral is required."
        ),
        suggested_action=(
            "Request a new referral from the PCP citing current clinical "
            "indication; reschedule appointment if needed."
        ),
        weight=2.0,
        extra_context={
            "referral_date": "2026-01-15",
            "max_age_days": 90,
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="referral_specialty_mismatch",
        message=(
            "Referral specifies a different specialty than the booked "
            "appointment. Carrier will not honor mismatched referrals."
        ),
        suggested_action=(
            "Confirm with PCP which specialty was clinically intended; "
            "either correct the referral or rebook the appointment."
        ),
        weight=1.5,
        extra_context={
            "referral_specialty": "internal_medicine",
            "booked_specialty": "cardiology",
        },
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="referral_not_on_file",
        message=(
            "No referral document found in the patient record despite the "
            "plan requiring one for this specialty visit."
        ),
        suggested_action=(
            "Reach out to PCP for the original referral fax/upload; in "
            "parallel, alert patient that visit may need rescheduling."
        ),
        weight=1.5,
        extra_context={
            "plan_requires_referral": True,
            "record_check_attempts": 2,
        },
        default_resolution_mode="informational",
    ),
]


async def referral_validation(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Referral Validation stage."""
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
