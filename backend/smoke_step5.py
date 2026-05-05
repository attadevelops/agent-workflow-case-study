"""Step 5 smoke test — invokes all six agents in both Complete and Escalate paths.

Pre-step-6 checkpoint per the agreed sequence: prove the agent contract
holds across the full set before LangGraph wiring.

Run from backend/:
    .venv/bin/python smoke_step5.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from random import Random
from typing import Any, Awaitable, Callable

from app.agents._runtime import AgentTuning
from app.agents.appointment_confirmation import appointment_confirmation
from app.agents.eligibility_verification import eligibility_verification
from app.agents.patient_intake import patient_intake
from app.agents.pre_visit_questionnaire import pre_visit_questionnaire
from app.agents.prior_authorization import prior_authorization
from app.agents.referral_validation import referral_validation
from app.mock_data import seed_appointments
from app.state import AppointmentState, Specialty, StageName, StageState

# Shortened jitter so the smoke test runs quickly. Probability overrides
# force the path on mechanical agents.
FAST_COMPLETE = AgentTuning(
    escalation_probability=0.0, work_seconds_min=0.02, work_seconds_max=0.05
)
FAST_ESCALATE = AgentTuning(
    escalation_probability=1.0, work_seconds_min=0.02, work_seconds_max=0.05
)
FAST_DEFAULT = AgentTuning(work_seconds_min=0.02, work_seconds_max=0.05)


AgentFn = Callable[..., Awaitable[AppointmentState]]


# (StageName, agent_fn). Order = pipeline order.
AGENTS: list[tuple[StageName, AgentFn]] = [
    (StageName.ELIGIBILITY_VERIFICATION, eligibility_verification),
    (StageName.PRIOR_AUTHORIZATION, prior_authorization),
    (StageName.PATIENT_INTAKE, patient_intake),
    (StageName.REFERRAL_VALIDATION, referral_validation),
    (StageName.PRE_VISIT_QUESTIONNAIRE, pre_visit_questionnaire),  # special path
    (StageName.APPOINTMENT_CONFIRMATION, appointment_confirmation),
]


def _row(label: str, stage: StageName, after: AppointmentState, extra: str = "") -> str:
    state_value = after.stage_states[stage].value
    runtime = after.stage_runtimes.get(stage)
    duration = (
        f"{(runtime.finished_at - runtime.started_at).total_seconds():.2f}s"
        if runtime and runtime.started_at and runtime.finished_at
        else "-"
    )
    code = (
        f"code={after.escalation_reason.code}"
        if after.escalation_reason and after.escalation_reason.raised_at_stage == stage
        else ""
    )
    return f"  [{label}] {stage.value:30s} {state_value:9s} {duration:>6s}  {code} {extra}".rstrip()


async def _force_questionnaire_escalate(apt: AppointmentState) -> AppointmentState:
    """The questionnaire's escalation is decision-based, not RNG-based. We
    brute-force seeds 0..200 with a cardiology appointment until the mock
    extraction trips the clinical_flag policy."""
    if apt.specialty != Specialty.CARDIOLOGY:
        raise ValueError("questionnaire escalation seed search needs a cardiology appt")

    for seed in range(200):
        candidate_state = await pre_visit_questionnaire(
            apt, rng=Random(seed), tuning=FAST_DEFAULT
        )
        if (
            candidate_state.stage_states[StageName.PRE_VISIT_QUESTIONNAIRE]
            == StageState.ESCALATE
        ):
            return candidate_state
    raise RuntimeError("no escalating seed found in 0..200")


async def main() -> None:
    now = datetime.now(timezone.utc)
    appointments = seed_appointments(now=now)
    by_id: dict[str, AppointmentState] = {a.appointment_id: a for a in appointments}

    # Use APT-01 (Maria Rodriguez, cardiology) as the universal target —
    # cardio works for the questionnaire's mock-flag path. Other agents
    # don't care about specialty.
    apt = by_id["APT-01"]

    print(f"step 5 smoke: {len(AGENTS)} agents on {apt.appointment_id} "
          f"({apt.patient_name}, {apt.specialty.value}, {apt.procedure!r})")

    # ── PATH 1: forced Complete on every agent ──────────────────────────
    print("\n── PATH 1: Complete ────────────────────────────────────────────")
    for stage, agent in AGENTS:
        if stage == StageName.PRE_VISIT_QUESTIONNAIRE:
            # Decision-based: default tuning + seed=1 lands on Complete
            # (cardiology mock with seed=1 doesn't trip the 30% flag).
            after = await agent(apt, rng=Random(1), tuning=FAST_DEFAULT)
        else:
            after = await agent(apt, rng=Random(1), tuning=FAST_COMPLETE)
        assert after.stage_states[stage] == StageState.COMPLETE, (
            f"{stage.value}: expected COMPLETE, got {after.stage_states[stage]}"
        )
        assert after.escalation_reason is None, f"{stage.value}: unexpected escalation"
        print(_row("OK ", stage, after))

    # ── PATH 2: forced Escalate on every agent ──────────────────────────
    print("\n── PATH 2: Escalate ────────────────────────────────────────────")
    for stage, agent in AGENTS:
        if stage == StageName.PRE_VISIT_QUESTIONNAIRE:
            after = await _force_questionnaire_escalate(apt)
            extra = "(decision-based; seed-search)"
        else:
            after = await agent(apt, rng=Random(7), tuning=FAST_ESCALATE)
            extra = ""
        assert after.stage_states[stage] == StageState.ESCALATE, (
            f"{stage.value}: expected ESCALATE, got {after.stage_states[stage]}"
        )
        assert after.escalation_reason is not None, (
            f"{stage.value}: missing escalation_reason"
        )
        assert after.escalation_reason.raised_at_stage == stage
        assert after.escalation_reason.agent_context["appointment_id"] == apt.appointment_id
        print(_row("ESC", stage, after, extra))

    print("\n[OK] step 5 multi-agent smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
