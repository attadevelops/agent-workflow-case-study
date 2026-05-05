"""Step 6 informational-mode smoke test.

Verifies the second resume path that smoke_step6.py doesn't exercise:

  • Stage 1 (Eligibility Verification) escalates with an informational-default
    code (e.g., member_id_mismatch).
  • Concierge resolves with `resolution_type=informational` and a `payload`
    supplying the corrected data.
  • Orchestrator does NOT advance the cursor. Instead:
      - stage_states[stage_1] is reset to NOT_STARTED
      - current_stage stays at stage_1
      - last_resolution is populated with the resolution
  • Stage 1's prep + agent re-execute. The agent has access to
    state.last_resolution.payload during the re-run.
  • After the re-run, the agent-node wrapper clears last_resolution and
    bumps stage_runtimes[stage_1].attempt to 2.

If the agent re-escalates on the re-run (FAST_ESCALATE keeps it forced),
the smoke test verifies the re-escalation is a fresh one — that's the
whole point: the routing worked, the agent re-evaluated, attempt=2,
last_resolution was consumed and cleared.

Run from backend/:
    .venv/bin/python smoke_step6_informational.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from random import Random

from langgraph.types import Command

from app.agents._runtime import AgentTuning
from app.mock_data import seed_appointments
from app.orchestrator import (
    build_graph,
    extract_interrupt_value,
    thread_config,
)
from app.state import AppointmentState, StageName, StageState

FAST_JITTER = {"work_seconds_min": 0.02, "work_seconds_max": 0.05}
FAST_COMPLETE = AgentTuning(escalation_probability=0.0, **FAST_JITTER)
FAST_ESCALATE = AgentTuning(escalation_probability=1.0, **FAST_JITTER)


def _state_from_invoke(result: dict) -> AppointmentState:
    cleaned = {k: v for k, v in result.items() if not k.startswith("__")}
    return AppointmentState.model_validate(cleaned)


def _summarize_stage(label: str, state: AppointmentState, stage: StageName) -> None:
    s = state.stage_states[stage]
    rt = state.stage_runtimes.get(stage)
    attempt = rt.attempt if rt else None
    print(f"  [{label}] stage_states[{stage.value}]={s.value}  attempt={attempt}")


async def main() -> None:
    now = datetime.now(timezone.utc)
    appointments = seed_appointments(now=now)
    apt = appointments[0]  # APT-01 Maria Rodriguez, cardiology
    stage_1 = StageName.ELIGIBILITY_VERIFICATION

    print(f"step 6 informational smoke: {apt.appointment_id} ({apt.patient_name})")
    print("plan: stage 1 force-escalates; resolve INFORMATIONAL with payload; "
          "verify stage 1 re-runs (cursor stays at stage 1).")

    # Stage 1 force-escalates; other stages don't matter for this test.
    overrides = {s: FAST_COMPLETE for s in StageName}
    overrides[stage_1] = FAST_ESCALATE

    graph, _ = build_graph(rng=Random(11), tuning_overrides=overrides)
    config = thread_config(apt.appointment_id)

    # ── Invoke 1: expect interrupt at stage 1 ──────────────────────────
    print("\n━━━ INVOKE 1: stage 1 ran, expected to escalate ━━━")
    result_1 = await graph.ainvoke(apt, config=config)
    state_1 = _state_from_invoke(result_1)

    interrupt_value = extract_interrupt_value(result_1)
    assert interrupt_value is not None, "expected interrupt; got clean completion"
    code = interrupt_value["escalation_reason"]["code"]
    print(f"  escalated at stage 1 with code: {code}")
    _summarize_stage("after invoke 1", state_1, stage_1)
    assert state_1.stage_states[stage_1] == StageState.ESCALATE
    assert state_1.escalation_reason is not None
    assert state_1.current_stage == stage_1
    rt_1 = state_1.stage_runtimes[stage_1]
    assert rt_1.attempt == 1, f"expected attempt=1 on first run, got {rt_1.attempt}"
    started_at_first_run = rt_1.started_at

    # ── Concierge resolves INFORMATIONAL with payload ──────────────────
    print("\n━━━ CONCIERGE RESOLVES (informational + payload) ━━━")
    informational_payload = {
        "note": (
            "Patient called back with corrected member ID. Re-running "
            "eligibility with the new value."
        ),
        "resolver_id": "concierge_informational_test",
        "resolution_type": "informational",
        "payload": {
            "corrected_member_id": "M-NEW-77321",
            "carrier_confirmed": True,
        },
    }
    print(f"  resolution_type: {informational_payload['resolution_type']}")
    print(f"  payload: {informational_payload['payload']}")

    # ── Invoke 2 (resume): stage 1 should RE-RUN, NOT advance to stage 2 ─
    print("\n━━━ INVOKE 2: resume; expect stage 1 RE-RUN (not advance) ━━━")
    result_2 = await graph.ainvoke(Command(resume=informational_payload), config=config)
    state_2 = _state_from_invoke(result_2)

    interrupt_value_2 = extract_interrupt_value(result_2)
    if interrupt_value_2 is not None:
        code_2 = interrupt_value_2["escalation_reason"]["code"]
        print(f"  re-escalated with code: {code_2}  (expected — FAST_ESCALATE forces it)")

    _summarize_stage("after invoke 2", state_2, stage_1)

    # ── KEY ROUTING ASSERTIONS ───────────────────────────────────────────
    rt_2 = state_2.stage_runtimes[stage_1]
    assert rt_2.attempt == 2, (
        f"stage 1 attempt counter should be 2 on re-run, got {rt_2.attempt}"
    )
    assert rt_2.started_at != started_at_first_run, (
        "stage 1 started_at should be a new timestamp; the agent re-ran"
    )
    # Cursor should still be at stage 1 (re-escalated) OR stage 2 (re-completed),
    # depending on the agent's roll on re-run. Either is fine — what we're
    # verifying is that stage 1 re-executed, not that it succeeded.
    assert state_2.stage_states[StageName.PRIOR_AUTHORIZATION] == StageState.NOT_STARTED, (
        "stage 2 must NOT have run (informational must NOT advance the cursor)"
    )
    print("  [routing pass] stage 1 re-ran (attempt=2, fresh started_at), "
          "stage 2 was NOT touched")

    # ── LIFECYCLE: last_resolution was set by exception, cleared by agent_node ─
    assert state_2.last_resolution is None, (
        f"last_resolution should be cleared by the agent-node wrapper after "
        f"the stage re-runs; got: {state_2.last_resolution}"
    )
    print("  [lifecycle pass] last_resolution cleared after agent consumed it")

    # ── Audit trail records the informational resolution ───────────────
    assert len(state_2.resolutions) == 1, (
        f"expected exactly 1 resolution recorded, got {len(state_2.resolutions)}"
    )
    only_resolution = state_2.resolutions[0]
    assert only_resolution.resolution_type == "informational"
    assert only_resolution.resolved_stage == stage_1
    assert only_resolution.payload == informational_payload["payload"]
    print("  [audit pass] resolutions[0] is informational, with the corrected "
          "member ID payload preserved")

    print("\n[OK] step 6 informational-mode smoke test passed")
    print("\n  trace: stage 1 escalated -> informational resolve -> "
          "stage 1 re-ran (attempt=2) -> stage 2 untouched")


if __name__ == "__main__":
    asyncio.run(main())
