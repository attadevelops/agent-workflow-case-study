"""Stage 2 agent: Prior Authorization.

Real-world responsibility: submit authorization requests to the patient's
insurance carrier and confirm coverage approval before the procedure occurs.
Common failure modes: outright carrier denial, "pending clinical info"
hold, payer portal outage, plan-level procedure ineligibility.

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

STAGE = StageName.PRIOR_AUTHORIZATION


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="carrier_denial",
        message=(
            "Insurance carrier denied authorization. Cited reason: "
            "service does not meet plan's medical necessity criteria."
        ),
        suggested_action=(
            "Review denial letter; gather supporting clinical documentation "
            "and submit a peer-to-peer review request, or appeal in writing."
        ),
        weight=2.0,
        extra_context={
            "denial_reason_code": "MN-DENY",
            "appeal_window_days": 30,
            "carrier_response_id": "DENY-pending",
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="auth_pending_clinical_info",
        message=(
            "Carrier returned 'auth pending - additional clinical information "
            "required.' Initial submission lacked supporting documentation."
        ),
        suggested_action=(
            "Attach the requested clinical notes (typically recent labs, "
            "imaging, or specialist consult) and resubmit via portal."
        ),
        weight=3.0,
        extra_context={
            "required_documents": ["recent_labs", "specialist_consult_note"],
            "carrier_response": "auth_pending_review",
            "submission_attempts": 1,
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="payer_portal_unreachable",
        message=(
            "Could not reach payer authorization portal after 3 retries. "
            "Carrier system likely experiencing an outage."
        ),
        suggested_action=(
            "Wait for carrier ops to confirm uptime, or submit via fax as "
            "a fallback. Re-attempt automated submission once portal is up."
        ),
        weight=1.5,
        extra_context={
            "portal_endpoint": "auth/v3/submit",
            "retry_count": 3,
            "last_error": "503 Service Unavailable",
        },
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="ineligible_procedure_for_plan",
        message=(
            "Patient's plan does not cover the requested procedure category. "
            "Authorization is not applicable; procedure would be self-pay."
        ),
        suggested_action=(
            "Discuss self-pay estimate with patient, or coordinate with "
            "PCP to substitute a covered alternative procedure."
        ),
        weight=1.0,
        extra_context={
            "plan_type": "HMO_basic",
            "procedure_category": "elective_diagnostic",
            "coverage_status": "excluded",
        },
        default_resolution_mode="decisional",
    ),
]


async def prior_authorization(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Prior Authorization stage."""
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
