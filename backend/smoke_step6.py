"""Step 6 smoke test — full graph lifecycle on a single appointment.

This is the architectural keystone deliverable: prove that the LangGraph
orchestrator correctly:

  1. Routes a fresh appointment through stage prep + agent nodes in order.
  2. Pauses on Escalate via interrupt() with a structured payload.
  3. Resumes via Command(resume=resolution) and advances to stage N+1
     (per the 'Cleared = N+1' commitment), NOT re-running stage N.
  4. Continues through remaining stages until completion.
  5. Ends with the appointment fully Complete or Cleared, no active
     escalation, current_stage=None, and the resolution recorded.

Run from backend/:
    .venv/bin/python smoke_step6.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from random import Random

from app.agents._runtime import AgentTuning
from app.mock_data import seed_appointments
from app.orchestrator import (
    build_graph,
    extract_interrupt_value,
    thread_config,
)
from app.state import AppointmentState, StageName, StageState

# Shortened jitter so the smoke test runs in seconds. The probabilistic
# escalation is forced via per-stage tuning overrides.
FAST_JITTER = {"work_seconds_min": 0.02, "work_seconds_max": 0.05}
FAST_COMPLETE = AgentTuning(escalation_probability=0.0, **FAST_JITTER)
FAST_ESCALATE = AgentTuning(escalation_probability=1.0, **FAST_JITTER)


def _print_pipeline(label: str, state: AppointmentState) -> None:
    """One-line-per-stage pipeline view + active escalation summary."""
    print(f"\n── {label} ──")
    print(f"  appt: {state.appointment_id} ({state.patient_name}, "
          f"{state.specialty.value}, {state.procedure!r})")
    print(f"  current_stage: {state.current_stage.value if state.current_stage else 'None (done)'}")
    for stage in [
        StageName.ELIGIBILITY_VERIFICATION,
        StageName.PRIOR_AUTHORIZATION,
        StageName.PATIENT_INTAKE,
        StageName.REFERRAL_VALIDATION,
        StageName.PRE_VISIT_QUESTIONNAIRE,
        StageName.APPOINTMENT_CONFIRMATION,
    ]:
        s = state.stage_states[stage]
        rt = state.stage_runtimes.get(stage)
        rt_str = ""
        if rt and rt.started_at and rt.finished_at:
            d = (rt.finished_at - rt.started_at).total_seconds()
            rt_str = f"  ({d:.2f}s)"
        print(f"    {stage.value:30s}  {s.value:11s}{rt_str}")
    if state.escalation_reason:
        e = state.escalation_reason
        print(f"  ACTIVE ESCALATION: code={e.code}, stage={e.raised_at_stage.value}")
        print(f"    message: {e.message}")
    if state.resolutions:
        print(f"  resolutions in history: {len(state.resolutions)}")
        for r in state.resolutions:
            print(f"    - {r.resolved_stage.value}: {r.resolved_code} "
                  f"(@ {r.resolved_at.strftime('%H:%M:%S')})")


def _state_from_invoke(result: dict) -> AppointmentState:
    """LangGraph returns a dict for pydantic state. Reconstruct the model.
    Excludes the synthetic __interrupt__ key the framework adds on pause."""
    cleaned = {k: v for k, v in result.items() if not k.startswith("__")}
    return AppointmentState.model_validate(cleaned)


async def main() -> None:
    now = datetime.now(timezone.utc)
    appointments = seed_appointments(now=now)
    apt = appointments[7]  # APT-08 Yuki Tanaka, primary care, fully NotStarted

    print(f"step 6 smoke: orchestrator end-to-end on {apt.appointment_id} "
          f"({apt.patient_name})")
    print(f"plan: stage 3 (PATIENT_INTAKE) is forced to Escalate; all "
          f"others forced to Complete.")

    # All stages forced to Complete except stage 3, which forces Escalate.
    # Pre-Visit Questionnaire ignores escalation_probability (decision-based);
    # primary care + fast jitter + most seeds keep it on Complete.
    overrides = {s: FAST_COMPLETE for s in StageName}
    overrides[StageName.PATIENT_INTAKE] = FAST_ESCALATE

    graph, _saver = build_graph(rng=Random(42), tuning_overrides=overrides)
    config = thread_config(apt.appointment_id)

    # ── First invoke: graph runs stages 1-2 (Complete) then 3 (Escalate) ──
    print("\n━━━ INVOKE 1: expect interrupt at PATIENT_INTAKE ━━━")
    result = await graph.ainvoke(apt, config=config)
    state_1 = _state_from_invoke(result)
    _print_pipeline("after first invoke", state_1)

    # Verify we paused at the exception node with the right payload.
    interrupt_value = extract_interrupt_value(result)
    assert interrupt_value is not None, "expected interrupt; got clean completion"
    assert interrupt_value["current_stage"] == StageName.PATIENT_INTAKE.value
    assert interrupt_value["escalation_reason"]["raised_at_stage"] == "patient_intake"
    print(f"\n  [interrupt payload] code={interrupt_value['escalation_reason']['code']}")
    print(f"                      stage={interrupt_value['current_stage']}")

    # Stage 3 should be Escalate, stages 1-2 Complete, stages 4-6 NotStarted.
    assert state_1.stage_states[StageName.ELIGIBILITY_VERIFICATION] == StageState.COMPLETE
    assert state_1.stage_states[StageName.PRIOR_AUTHORIZATION] == StageState.COMPLETE
    assert state_1.stage_states[StageName.PATIENT_INTAKE] == StageState.ESCALATE
    assert state_1.stage_states[StageName.REFERRAL_VALIDATION] == StageState.NOT_STARTED
    assert state_1.escalation_reason is not None
    assert state_1.current_stage == StageName.PATIENT_INTAKE
    print("  [assertions pass] stages 1-2 Complete, stage 3 Escalate, 4-6 NotStarted")

    # ── Concierge resolves ───────────────────────────────────────────
    print("\n━━━ CONCIERGE RESOLVES ━━━")
    resolution_payload = {
        "note": (
            "Reviewed case with ops lead. Out-of-network exception approved "
            "by lead per patient's prior auth letter on file. Cleared by "
            "judgment, no further intake needed."
        ),
        "resolver_id": "concierge_smoke_test",
        # Explicit decisional mode: human judgment supersedes; advance to N+1.
        "resolution_type": "decisional",
    }
    print(f"  resolution note: {resolution_payload['note'][:60]}...")

    # ── Second invoke: resume; expect graph to advance to stage 4+ ───
    from langgraph.types import Command
    print("\n━━━ INVOKE 2: resume; expect stages 4-6 to execute ━━━")
    result = await graph.ainvoke(Command(resume=resolution_payload), config=config)
    state_2 = _state_from_invoke(result)
    _print_pipeline("after resume", state_2)

    # Verify the workflow advanced from stage 4 onward (NOT re-ran stage 3).
    assert state_2.stage_states[StageName.PATIENT_INTAKE] == StageState.CLEARED, (
        "stage 3 should be CLEARED post-resolution, not re-run as Complete"
    )
    assert state_2.stage_states[StageName.REFERRAL_VALIDATION] == StageState.COMPLETE
    assert state_2.stage_states[StageName.APPOINTMENT_CONFIRMATION] == StageState.COMPLETE
    assert state_2.escalation_reason is None, "active escalation should be cleared"
    assert state_2.current_stage is None, "pipeline should be done"
    assert len(state_2.resolutions) == 1
    assert state_2.resolutions[0].resolved_stage == StageName.PATIENT_INTAKE
    assert state_2.resolutions[0].resolved_code is not None
    print("\n  [assertions pass] stage 3 Cleared, stages 4-6 Complete, "
          "no active escalation, 1 resolution recorded")

    # ── No further interrupt expected ────────────────────────────────
    interrupt_value_2 = extract_interrupt_value(result)
    assert interrupt_value_2 is None, "should not interrupt again — graph done"

    # ── Verify checkpoint state via get_state (the dashboard's read path) ──
    print("\n━━━ CHECKPOINT VERIFICATION ━━━")
    snapshot = graph.get_state(config)
    print(f"  snapshot.next: {snapshot.next}  (empty tuple = graph fully done)")
    assert snapshot.next == (), f"expected empty next, got {snapshot.next}"

    print("\n[OK] step 6 orchestrator smoke test passed")
    print("\n  full lifecycle verified:")
    print("  fresh -> Eligibility ✓ -> Prior Auth ✓ -> Patient Intake ✗ "
          "-> [interrupt] -> [resolve] -> Referral ✓ -> Questionnaire ✓ "
          "-> Confirmation ✓ -> done")


if __name__ == "__main__":
    asyncio.run(main())
