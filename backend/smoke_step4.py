"""Step 4 smoke test — exercises the Eligibility Verification agent.

End-of-step-4 observability checkpoint: prove that we can invoke the agent
on a seeded appointment (APT-01) and watch state mutate correctly along
both the Complete and Escalate paths.

Run from the backend/ directory with the project venv active:

    .venv/bin/python smoke_step4.py

Both paths are forced via tuning override (escalation_probability 0.0 or
1.0) so the test is fully deterministic and doesn't depend on a magic seed.
The default-tuning probabilistic behavior is exercised at the orchestrator
level in step 6+.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from random import Random

from app.agents._runtime import AgentTuning
from app.agents.eligibility_verification import (
    CATALOG,
    eligibility_verification,
)
from app.mock_data import seed_appointments
from app.state import AppointmentState, StageName, StageState


def _print_transition(label: str, before: AppointmentState, after: AppointmentState) -> None:
    stage = StageName.ELIGIBILITY_VERIFICATION
    print(f"\n── {label} ─────────────────────────────────")
    print(f"  appt: {after.appointment_id} ({after.patient_name})")
    print(
        f"  stage state: "
        f"{before.stage_states[stage].value} -> {after.stage_states[stage].value}"
    )
    runtime = after.stage_runtimes.get(stage)
    if runtime and runtime.started_at and runtime.finished_at:
        duration = (runtime.finished_at - runtime.started_at).total_seconds()
        print(f"  runtime: {duration:.2f}s, attempt={runtime.attempt}")
    if after.escalation_reason is not None:
        e = after.escalation_reason
        print(f"  escalated:")
        print(f"    code: {e.code}")
        print(f"    message: {e.message}")
        print(f"    suggested_action: {e.suggested_action}")
        print(f"    agent_context keys: {sorted(e.agent_context.keys())}")


async def _run_complete_path(apt: AppointmentState) -> AppointmentState:
    forced = AgentTuning(escalation_probability=0.0, work_seconds_min=0.05, work_seconds_max=0.1)
    after = await eligibility_verification(apt, rng=Random(1), tuning=forced)
    _print_transition("Path 1: forced Complete (probability=0.0)", apt, after)
    stage = StageName.ELIGIBILITY_VERIFICATION
    assert after.stage_states[stage] == StageState.COMPLETE, "expected COMPLETE"
    assert after.escalation_reason is None, "expected no escalation"
    runtime = after.stage_runtimes[stage]
    assert runtime.started_at is not None and runtime.finished_at is not None
    assert runtime.finished_at >= runtime.started_at, "finished_at must be >= started_at"
    return after


async def _run_escalate_path(apt: AppointmentState) -> AppointmentState:
    forced = AgentTuning(escalation_probability=1.0, work_seconds_min=0.05, work_seconds_max=0.1)
    after = await eligibility_verification(apt, rng=Random(7), tuning=forced)
    _print_transition("Path 2: forced Escalate (probability=1.0)", apt, after)
    stage = StageName.ELIGIBILITY_VERIFICATION
    assert after.stage_states[stage] == StageState.ESCALATE, "expected ESCALATE"
    assert after.escalation_reason is not None, "expected escalation_reason populated"
    e = after.escalation_reason
    catalog_codes = {c.code for c in CATALOG}
    assert e.code in catalog_codes, f"escalation code {e.code!r} not in catalog"
    assert e.agent_context["appointment_id"] == apt.appointment_id
    assert e.agent_context["patient_name"] == apt.patient_name
    assert e.raised_at_stage == stage
    return after


async def main() -> None:
    now = datetime.now(timezone.utc)
    appointments = seed_appointments(now=now)
    apt_01 = appointments[0]

    print(f"loaded {len(appointments)} mock appointments")
    print(f"smoke target: {apt_01.appointment_id} ({apt_01.patient_name}), "
          f"specialty={apt_01.specialty.value}, procedure={apt_01.procedure!r}")

    await _run_complete_path(apt_01)
    await _run_escalate_path(apt_01)

    print("\n[OK] step 4 smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
