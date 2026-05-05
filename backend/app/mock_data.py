"""
Mock dataset for the Agentic Workflow Management facade.

This dataset is hand-tuned (not procedurally generated) to exercise:

  • PRIORITY SCORING. The 25 appointments span five SLA bands, from "on-fire"
    (under 4h to deadline, just arrived) to "stale" (created 4+ days ago
    with low SLA pressure). On-fire vs. stale creates intentional tension
    between sla_urgency and queue_age weights — the scoring function has to
    pick a side, and the demoer can show that the priority changes if the
    weights change.

  • LLM RULE STRATEGY. Client distribution is intentionally skewed (Northwell
    13 / Mercy 8 / Valley 4) and specialty distribution favors Cardiology and
    Orthopedics over Dermatology. Rules like "Cardiology before Dermatology"
    or "Northwell first" therefore produce visible reordering when the LLM
    strategy is selected, not noise.

  • EXCEPTION QUEUE FROM TICK ZERO. Two appointments are pre-escalated so the
    Exception Queue is populated when the demo starts — no waiting for an
    agent to escalate live. One additional appointment carries a prior
    resolution to demonstrate the recovery trail (escalated → resolved →
    workflow continued from the next stage).

  • PIPELINE PROGRESS. Five appointments are mid-pipeline (stages 1-2
    Complete), two are deeper (stages 1-3 Complete), and one is fully Complete
    (closed lifecycle). The dashboard pipeline visualization therefore shows
    a non-uniform set of pills from the first frame, not 25 rows of "all
    NotStarted."

The 25 specs themselves are static across runs. The only nondeterminism is
the timestamp anchor (`now`), which the caller passes in. All offsets are
computed relative to `now`, so the SLA banding stays consistent regardless
of when the orchestrator boots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.state import (
    AppointmentState,
    ClientId,
    ConciergeResolution,
    EscalationReason,
    STAGE_ORDER,
    Specialty,
    StageName,
    StageState,
)


# ──────────────────────────────────────────────────────────────────────────
# Seed spec (private DSL for the table below)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _PreEscalation:
    """A pre-seeded active escalation. Becomes EscalationReason on the appointment
    + sets the corresponding stage to Escalate."""

    stage: StageName
    code: str
    message: str
    suggested_action: str
    agent_context: dict
    raised_hours_ago: float
    # Catalog hint for the resolution form's mode toggle. Defaults to decisional
    # to preserve the original semantic; pre-escalations that are inherently
    # data-supplied (member ID, missing document) opt into informational.
    default_resolution_mode: str = "decisional"


@dataclass
class _PriorResolution:
    """A pre-seeded resolution in the appointment's history. The named stage
    is set to Cleared in stage_states (rather than Complete), and a
    ConciergeResolution entry is appended to the history."""

    stage: StageName
    resolved_code: str
    note: str
    resolved_hours_ago: float


@dataclass
class _AppointmentSeed:
    appointment_id: str
    patient_name: str
    specialty: Specialty
    procedure: str
    client_id: ClientId
    # Hours from `now`. Negative means past, positive means future.
    sla_hours: float
    age_hours: float  # how long ago this appointment was created (positive)
    # 0 = no stages complete; 3 = stages 1-3 are Complete (or Cleared);
    # 6 = fully Complete. Escalation overrides this for the named stage.
    completed_through: int = 0
    pre_escalation: Optional[_PreEscalation] = None
    prior_resolution: Optional[_PriorResolution] = None


# ──────────────────────────────────────────────────────────────────────────
# The 25 hand-tuned appointments
# ──────────────────────────────────────────────────────────────────────────

_SEEDS: list[_AppointmentSeed] = [
    # ─── On-fire band: SLA under 4h, recently arrived. Top of the queue. ───
    _AppointmentSeed(
        appointment_id="APT-01", patient_name="Maria Rodriguez",
        specialty=Specialty.CARDIOLOGY, procedure="Stress test",
        client_id=ClientId.NORTHWELL,
        sla_hours=2.5, age_hours=8.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-02", patient_name="James Park",
        specialty=Specialty.ORTHOPEDICS, procedure="Knee MRI",
        client_id=ClientId.MERCY,
        sla_hours=1.5, age_hours=6.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-03", patient_name="Aisha Patel",
        specialty=Specialty.PRIMARY_CARE, procedure="Diabetes follow-up",
        client_id=ClientId.NORTHWELL,
        sla_hours=3.5, age_hours=10.0,
    ),

    # ─── Urgent band: SLA 5-12h. Some mid-pipeline; one escalated; one
    # carries a prior resolution to show the recovery trail. ───
    _AppointmentSeed(
        appointment_id="APT-04", patient_name="David Chen",
        specialty=Specialty.CARDIOLOGY, procedure="Echocardiogram",
        client_id=ClientId.VALLEY,
        sla_hours=8.0, age_hours=16.0,
        completed_through=2,  # stages 1-2 Complete, currently at stage 3
    ),
    _AppointmentSeed(
        appointment_id="APT-05", patient_name="Sarah O'Connor",
        specialty=Specialty.ORTHOPEDICS, procedure="ACL post-op evaluation",
        client_id=ClientId.NORTHWELL,
        sla_hours=10.0, age_hours=14.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-06", patient_name="Marcus Williams",
        specialty=Specialty.DERMATOLOGY, procedure="Mole screening",
        client_id=ClientId.MERCY,
        sla_hours=6.0, age_hours=22.0,
        pre_escalation=_PreEscalation(
            stage=StageName.ELIGIBILITY_VERIFICATION,
            code="member_id_mismatch",
            message="Member ID on patient record is missing. Eligibility check cannot proceed.",
            suggested_action="Contact patient or referring office to retrieve correct insurance card details; supply via informational resolution.",
            agent_context={
                "patient_record_id": "PR-44218",
                "member_id_field": None,
                "last_known_carrier": "Aetna (expired 2024-11)",
                "carrier_lookup_attempts": 2,
            },
            raised_hours_ago=4.0,
            default_resolution_mode="informational",
        ),
    ),
    _AppointmentSeed(
        # The recovery-trail showcase: stage 1 was escalated for expired
        # coverage, concierge resolved it, workflow advanced. Now at stage 3.
        appointment_id="APT-07", patient_name="Elena Kowalski",
        specialty=Specialty.CARDIOLOGY, procedure="Holter monitor placement",
        client_id=ClientId.NORTHWELL,
        sla_hours=11.0, age_hours=18.0,
        completed_through=2,  # stages 1-2 done; stage 1 was Cleared, not Complete
        prior_resolution=_PriorResolution(
            stage=StageName.ELIGIBILITY_VERIFICATION,
            resolved_code="coverage_inactive",
            note=(
                "Patient confirmed insurance carrier change to BCBS Massachusetts effective 2026-04-01. "
                "Updated record with new policy ID; eligibility verified manually via carrier portal."
            ),
            resolved_hours_ago=9.0,
        ),
    ),

    # ─── Middle band: SLA 12-48h. Bulk of the dataset. Mix of fresh and
    # mid-pipeline; one escalation deeper in the pipeline. ───
    _AppointmentSeed(
        appointment_id="APT-08", patient_name="Yuki Tanaka",
        specialty=Specialty.PRIMARY_CARE, procedure="Annual physical",
        client_id=ClientId.MERCY,
        sla_hours=24.0, age_hours=10.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-09", patient_name="Ahmed Hassan",
        specialty=Specialty.ORTHOPEDICS, procedure="Rotator cuff evaluation",
        client_id=ClientId.NORTHWELL,
        sla_hours=20.0, age_hours=14.0,
        completed_through=2,
    ),
    _AppointmentSeed(
        appointment_id="APT-10", patient_name="Olivia Bennett",
        specialty=Specialty.CARDIOLOGY, procedure="Valve replacement consult",
        client_id=ClientId.NORTHWELL,
        sla_hours=30.0, age_hours=18.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-11", patient_name="Carlos Mendoza",
        specialty=Specialty.PRIMARY_CARE, procedure="Hypertension management",
        client_id=ClientId.VALLEY,
        sla_hours=36.0, age_hours=8.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-12", patient_name="Priya Sharma",
        specialty=Specialty.DERMATOLOGY, procedure="Biopsy follow-up",
        client_id=ClientId.NORTHWELL,
        sla_hours=18.0, age_hours=22.0,
        completed_through=2,
    ),
    _AppointmentSeed(
        appointment_id="APT-13", patient_name="Wei Liu",
        specialty=Specialty.ORTHOPEDICS, procedure="Hip replacement consult",
        client_id=ClientId.MERCY,
        sla_hours=42.0, age_hours=12.0,
    ),
    _AppointmentSeed(
        # Second pre-escalation: deeper in the pipeline (stage 2, prior auth).
        # Different code class than APT-06, so the queue shows variety.
        appointment_id="APT-14", patient_name="Hannah Goldstein",
        specialty=Specialty.CARDIOLOGY, procedure="Cardiac MRI",
        client_id=ClientId.NORTHWELL,
        sla_hours=40.0, age_hours=10.0,
        completed_through=1,  # stage 1 (eligibility) complete; escalated at stage 2
        pre_escalation=_PreEscalation(
            stage=StageName.PRIOR_AUTHORIZATION,
            code="auth_pending_clinical_info",
            message=(
                "Insurance carrier returned 'auth pending medical necessity review' "
                "for cardiac MRI. Initial submission lacked recent EKG."
            ),
            suggested_action=(
                "Attach last EKG (file in patient record dated 2026-04-22) "
                "and resubmit auth request via carrier portal."
            ),
            agent_context={
                "carrier": "United Healthcare",
                "auth_id": "AUTH-7821",
                "denial_reason_code": "MN-REVIEW-REQ",
                "required_documents": ["recent_ekg", "cardiology_consult_note"],
                "submission_attempts": 1,
            },
            raised_hours_ago=6.0,
            default_resolution_mode="informational",
        ),
    ),
    _AppointmentSeed(
        appointment_id="APT-15", patient_name="Dmitri Volkov",
        specialty=Specialty.PRIMARY_CARE, procedure="Vaccination",
        client_id=ClientId.NORTHWELL,
        sla_hours=15.0, age_hours=6.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-16", patient_name="Fatima Al-Rashid",
        specialty=Specialty.ORTHOPEDICS, procedure="Fracture follow-up",
        client_id=ClientId.MERCY,
        sla_hours=46.0, age_hours=16.0,
        completed_through=3,  # deeper: stages 1-3 Complete
    ),
    _AppointmentSeed(
        appointment_id="APT-17", patient_name="Christopher Lee",
        specialty=Specialty.CARDIOLOGY, procedure="Ablation consult",
        client_id=ClientId.VALLEY,
        sla_hours=22.0, age_hours=8.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-18", patient_name="Sophia Romano",
        specialty=Specialty.PRIMARY_CARE, procedure="Chronic pain consult",
        client_id=ClientId.NORTHWELL,
        sla_hours=28.0, age_hours=20.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-19", patient_name="Emma Schultz",
        specialty=Specialty.DERMATOLOGY, procedure="Mohs surgery prep",
        client_id=ClientId.MERCY,
        sla_hours=32.0, age_hours=14.0,
    ),

    # ─── Low-pressure band: SLA 50-70h. Lower priority, deeper in pipeline
    # for one of them. ───
    _AppointmentSeed(
        appointment_id="APT-20", patient_name="Jose Garcia",
        specialty=Specialty.ORTHOPEDICS, procedure="Knee replacement consult",
        client_id=ClientId.NORTHWELL,
        sla_hours=58.0, age_hours=12.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-21", patient_name="Thomas Anderson",
        specialty=Specialty.PRIMARY_CARE, procedure="Flu evaluation",
        client_id=ClientId.VALLEY,
        sla_hours=64.0, age_hours=8.0,
    ),
    _AppointmentSeed(
        appointment_id="APT-22", patient_name="Zara Khan",
        specialty=Specialty.ORTHOPEDICS, procedure="Shoulder injection",
        client_id=ClientId.NORTHWELL,
        sla_hours=68.0, age_hours=16.0,
        completed_through=3,  # deeper: stages 1-3 Complete
    ),
    _AppointmentSeed(
        appointment_id="APT-23", patient_name="Naomi Watanabe",
        specialty=Specialty.CARDIOLOGY, procedure="EKG follow-up",
        client_id=ClientId.MERCY,
        sla_hours=52.0, age_hours=10.0,
    ),

    # ─── Stale band: created days ago, still pending. Low SLA pressure but
    # high queue_age — tension test for the priority function. ───
    _AppointmentSeed(
        appointment_id="APT-24", patient_name="Robert Sullivan",
        specialty=Specialty.ORTHOPEDICS, procedure="Lumbar spine consult",
        client_id=ClientId.NORTHWELL,
        sla_hours=78.0, age_hours=96.0,  # 4 days old
    ),

    # ─── Closed lifecycle: fully Complete. Demonstrates the dashboard's
    # handling of finished appointments. ───
    _AppointmentSeed(
        appointment_id="APT-25", patient_name="Linh Nguyen",
        specialty=Specialty.PRIMARY_CARE, procedure="Diabetes follow-up",
        client_id=ClientId.MERCY,
        sla_hours=24.0, age_hours=48.0,
        completed_through=6,  # all stages Complete
    ),
]


# ──────────────────────────────────────────────────────────────────────────
# Builder
# ──────────────────────────────────────────────────────────────────────────


def _build_stage_states(
    completed_through: int,
    pre_escalation: Optional[_PreEscalation],
    prior_resolution: Optional[_PriorResolution],
) -> tuple[dict[StageName, StageState], Optional[StageName]]:
    """Compute stage_states and current_stage cursor from a seed spec.

    Order of effects (each layered on the previous):
      1. Seed all 6 stages to NOT_STARTED.
      2. Mark stages [0 .. completed_through) as COMPLETE.
      3. If prior_resolution is set, that stage becomes CLEARED instead.
      4. If pre_escalation is set, that stage becomes ESCALATE (overrides
         the COMPLETE from step 2 if it falls within the completed range).
    """
    stages: dict[StageName, StageState] = {s: StageState.NOT_STARTED for s in STAGE_ORDER}

    for i in range(completed_through):
        stages[STAGE_ORDER[i]] = StageState.COMPLETE

    if prior_resolution is not None:
        stages[prior_resolution.stage] = StageState.CLEARED

    if pre_escalation is not None:
        stages[pre_escalation.stage] = StageState.ESCALATE

    # Cursor: first non-terminal stage. None if all terminal.
    cursor: Optional[StageName] = None
    for s in STAGE_ORDER:
        if stages[s] in (StageState.NOT_STARTED, StageState.PROCESSING, StageState.ESCALATE):
            cursor = s
            break

    return stages, cursor


def _build_appointment(seed: _AppointmentSeed, now: datetime) -> AppointmentState:
    created_at = now - timedelta(hours=seed.age_hours)
    sla_due_at = now + timedelta(hours=seed.sla_hours)

    stage_states, current_stage = _build_stage_states(
        seed.completed_through, seed.pre_escalation, seed.prior_resolution
    )

    escalation_reason: Optional[EscalationReason] = None
    if seed.pre_escalation is not None:
        escalation_reason = EscalationReason(
            code=seed.pre_escalation.code,
            message=seed.pre_escalation.message,
            suggested_action=seed.pre_escalation.suggested_action,
            agent_context=seed.pre_escalation.agent_context,
            raised_at=now - timedelta(hours=seed.pre_escalation.raised_hours_ago),
            raised_at_stage=seed.pre_escalation.stage,
            default_resolution_mode=seed.pre_escalation.default_resolution_mode,  # type: ignore[arg-type]
        )

    resolutions: list[ConciergeResolution] = []
    if seed.prior_resolution is not None:
        resolutions.append(
            ConciergeResolution(
                note=seed.prior_resolution.note,
                resolved_at=now - timedelta(hours=seed.prior_resolution.resolved_hours_ago),
                resolver_id="concierge_demo",
                resolved_stage=seed.prior_resolution.stage,
                resolved_code=seed.prior_resolution.resolved_code,
            )
        )

    return AppointmentState(
        appointment_id=seed.appointment_id,
        patient_name=seed.patient_name,
        specialty=seed.specialty,
        procedure=seed.procedure,
        client_id=seed.client_id,
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=1),
        sla_due_at=sla_due_at,
        # Eligible to run from creation time. Modeled but not enforced —
        # in production this would be `appointment_time - 24h`.
        eligible_to_run_at=created_at,
        stage_states=stage_states,
        current_stage=current_stage,
        priority_score=None,  # populated on first orchestrator tick
        priority_reasoning=None,
        escalation_reason=escalation_reason,
        resolutions=resolutions,
    )


def seed_appointments(now: datetime) -> list[AppointmentState]:
    """Build the full mock dataset of 25 appointments anchored to `now`.

    The caller (typically the FastAPI store at startup or the /admin/seed
    endpoint) passes `datetime.now(timezone.utc)`. All offsets are relative,
    so the SLA bands are stable across runs.
    """
    return [_build_appointment(s, now) for s in _SEEDS]
