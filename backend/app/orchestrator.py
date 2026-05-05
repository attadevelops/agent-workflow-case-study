"""LangGraph orchestrator for the Agentic Workflow Management facade.

Architecture (the architectural keystone of the project):

  • Each of the 6 stages becomes TWO nodes in the graph:
      - `prep_<stage>`: flips stage_state to PROCESSING and writes a
        checkpoint. This is what makes Processing visible to consumers
        polling between checkpoints — visibility is a function of node
        count, not of intra-function state mutation.
      - `agent_<stage>`: invokes the actual agent function (decides
        Complete/Escalate, populates stage_runtimes).
    Wired: prep -> agent (unconditional) -> conditional(next prep | exception).

  • One `exception` node interrupts via `interrupt(...)` and resumes via
    `Command(resume=resolution_payload)`. On resume, the node:
      1. Marks the escalated stage as CLEARED (per "Cleared = N+1" decision)
      2. Appends the ConciergeResolution to history
      3. Clears the active escalation_reason
      4. Advances current_stage to the next stage (or None if at end)
    Then a conditional edge routes to `prep_<next_stage>` or END.

  • thread_id = appointment_id. Each appointment is its own graph thread,
    independently pause-able and resume-able.

  • InMemorySaver checkpointer holds graph state across pause/resume cycles.

  • One injected RNG per orchestrator instance, threaded to all agents via
    closure. Determinism is per-orchestrator-run (use IKS_SEED to set).

  • Optional `tuning_overrides` lets demos / tests force specific stages
    to Complete or Escalate. Default is `DEMO_TUNING` for every stage.

What is NOT here:
  - Priority scoring / tick loop (step 7).
  - FastAPI surface (step 7+8).
  - The store / appointment registry (step 7).
This module exposes a `build_graph()` function. The smoke test (step 6)
drives it directly. The store and tick loop wrap it at step 7.
"""

from __future__ import annotations

import os
import random
from typing import Any, Awaitable, Callable, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents._runtime import DEMO_TUNING, AgentTuning, utc_now
from app.agents.appointment_confirmation import appointment_confirmation
from app.agents.eligibility_verification import eligibility_verification
from app.agents.patient_intake import patient_intake
from app.agents.pre_visit_questionnaire import pre_visit_questionnaire
from app.agents.prior_authorization import prior_authorization
from app.agents.referral_validation import referral_validation
from app.state import (
    AppointmentState,
    ConciergeResolution,
    STAGE_ORDER,
    StageName,
    StageRuntime,
    StageState,
)


# Wired in pipeline order; mirrors STAGE_ORDER.
AgentFn = Callable[..., Awaitable[AppointmentState]]
AGENTS_BY_STAGE: dict[StageName, AgentFn] = {
    StageName.ELIGIBILITY_VERIFICATION: eligibility_verification,
    StageName.PRIOR_AUTHORIZATION: prior_authorization,
    StageName.PATIENT_INTAKE: patient_intake,
    StageName.REFERRAL_VALIDATION: referral_validation,
    StageName.PRE_VISIT_QUESTIONNAIRE: pre_visit_questionnaire,
    StageName.APPOINTMENT_CONFIRMATION: appointment_confirmation,
}


# ──────────────────────────────────────────────────────────────────────────
# Node-name conventions and stage helpers
# ──────────────────────────────────────────────────────────────────────────


def _prep_node_name(stage: StageName) -> str:
    return f"prep_{stage.value}"


def _agent_node_name(stage: StageName) -> str:
    return f"agent_{stage.value}"


EXCEPTION_NODE = "exception"


def _next_stage(stage: StageName) -> Optional[StageName]:
    idx = STAGE_ORDER.index(stage)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]


# ──────────────────────────────────────────────────────────────────────────
# Node factories
# ──────────────────────────────────────────────────────────────────────────


def _make_prep_node(stage: StageName) -> Callable[..., Awaitable[AppointmentState]]:
    """Sets stage_states[stage]=PROCESSING and writes a checkpoint. The
    checkpoint between this node and the agent node is what polling sees
    as Processing."""

    async def prep(state: AppointmentState) -> AppointmentState:
        new_stage_states = {**state.stage_states, stage: StageState.PROCESSING}
        return state.model_copy(
            update={
                "stage_states": new_stage_states,
                "current_stage": stage,
                "updated_at": utc_now(),
            }
        )

    return prep


def _make_agent_node(
    stage: StageName,
    agent_fn: AgentFn,
    rng: random.Random,
    tuning: AgentTuning,
) -> Callable[..., Awaitable[AppointmentState]]:
    """Wraps an agent so it can run as a LangGraph node. Threads the
    orchestrator's RNG and per-stage tuning via closure, and post-processes
    the agent's return:

      • On COMPLETE: advance `current_stage` to the next stage (or None
        if at end). Agent owns the decision; orchestrator owns the cursor.
      • On ESCALATE: leave `current_stage` so the exception node can read
        which stage tripped.
      • Always: bump the stage's `attempt` counter (informational re-runs
        produce attempt=2, attempt=3, etc.) and clear `last_resolution`
        (consumed by the agent that just ran).
    """
    next_stg = _next_stage(stage)

    async def node(state: AppointmentState) -> AppointmentState:
        prior_runtime = state.stage_runtimes.get(stage)
        result = await agent_fn(state, rng=rng, tuning=tuning)

        # Fix up attempt counter on the runtime the agent just produced.
        agent_runtime = result.stage_runtimes.get(stage)
        if agent_runtime is not None and prior_runtime is not None:
            bumped = StageRuntime(
                started_at=agent_runtime.started_at,
                finished_at=agent_runtime.finished_at,
                attempt=prior_runtime.attempt + 1,
            )
            new_runtimes = {**result.stage_runtimes, stage: bumped}
            result = result.model_copy(update={"stage_runtimes": new_runtimes})

        update: dict = {"last_resolution": None}
        if result.stage_states[stage] == StageState.COMPLETE:
            update["current_stage"] = next_stg
        return result.model_copy(update=update)

    return node


async def _exception_node(state: AppointmentState) -> AppointmentState:
    """Pauses the graph until the concierge resolves the active escalation.

    Resume payload shape (dict):
      • note: str (required) — concierge's explanation
      • resolver_id: str (optional) — defaults to "concierge_demo"
      • resolution_type: "decisional" | "informational" (optional) —
        defaults to "decisional" (preserves the original single-mode
        semantic from the prior decision)
      • payload: dict (optional) — informational data the agent reads on
        re-run, e.g., {"corrected_member_id": "M-12345"}

    Branching on `resolution_type`:
      • DECISIONAL: human judgment supersedes the agent.
          - stage_states[N] = CLEARED
          - current_stage advances to N+1 (or None if at end)
          - last_resolution stays None (decisional doesn't propagate data)

      • INFORMATIONAL: human supplies missing data; agent re-evaluates.
          - stage_states[N] = NOT_STARTED
          - current_stage stays at N (cursor unchanged)
          - last_resolution = the resolution (agent reads payload on re-run)
            The agent-node wrapper clears last_resolution after the agent
            re-runs, regardless of outcome.

    Both branches:
      • Append the resolution to `resolutions` (append-only audit trail)
      • Clear `escalation_reason` (active slot empty until next escalation)
    """
    escalated_stage = state.current_stage
    if escalated_stage is None:
        raise RuntimeError(
            "exception_node entered with current_stage=None; coherence violation"
        )
    if state.escalation_reason is None:
        raise RuntimeError(
            "exception_node entered without an active escalation_reason"
        )

    # interrupt(value) pauses execution. The value is what the consumer
    # sees in the __interrupt__ key. The return value of interrupt() is
    # whatever Command(resume=...) supplied on continuation.
    payload: Any = interrupt(
        {
            "appointment_id": state.appointment_id,
            "current_stage": escalated_stage.value,
            "escalation_reason": state.escalation_reason.model_dump(mode="json"),
        }
    )

    if not isinstance(payload, dict) or "note" not in payload:
        raise ValueError(
            "Resume payload must be a dict with at least a 'note' key. "
            f"Got: {type(payload).__name__}"
        )

    resolution_type = payload.get("resolution_type", "decisional")
    if resolution_type not in ("decisional", "informational"):
        raise ValueError(
            f"resolution_type must be 'decisional' or 'informational'; "
            f"got: {resolution_type!r}"
        )

    resolved_at = utc_now()
    resolution = ConciergeResolution(
        note=payload["note"],
        resolved_at=resolved_at,
        resolver_id=payload.get("resolver_id", "concierge_demo"),
        resolved_stage=escalated_stage,
        resolved_code=state.escalation_reason.code,
        resolution_type=resolution_type,
        payload=payload.get("payload"),
    )

    new_resolutions = [*state.resolutions, resolution]

    if resolution_type == "decisional":
        # Stage cleared by human judgment; advance cursor.
        new_stage_states = {
            **state.stage_states,
            escalated_stage: StageState.CLEARED,
        }
        return state.model_copy(
            update={
                "stage_states": new_stage_states,
                "resolutions": new_resolutions,
                "escalation_reason": None,
                "current_stage": _next_stage(escalated_stage),
                "last_resolution": None,
                "updated_at": resolved_at,
            }
        )

    # Informational: stage re-runs with the resolution payload available.
    new_stage_states = {
        **state.stage_states,
        escalated_stage: StageState.NOT_STARTED,
    }
    return state.model_copy(
        update={
            "stage_states": new_stage_states,
            "resolutions": new_resolutions,
            "escalation_reason": None,
            "current_stage": escalated_stage,  # cursor unchanged
            "last_resolution": resolution,  # propagated to the agent's re-run
            "updated_at": resolved_at,
        }
    )


# ──────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────


def _start_router(state: AppointmentState) -> str:
    """The graph may be invoked on appointments at any pipeline position
    (mid-pipeline due to seed data, for example). Route to the prep node
    of the appointment's current_stage, or END if the pipeline is done.

    If the appointment arrives already-escalated (i.e., a seed-time
    pre-escalation, or any appointment whose escalation_reason is set
    when the graph is invoked), route directly to the exception node so
    a checkpoint is created and the concierge resolution path can resume.
    Without this, fresh graph invokes would re-enter prep_<stage> and the
    agent would overwrite the pre-existing escalation.
    """
    if state.current_stage is None:
        return END
    if state.escalation_reason is not None:
        return EXCEPTION_NODE
    return _prep_node_name(state.current_stage)


def _make_post_agent_router(stage: StageName) -> Callable[[AppointmentState], str]:
    """Routes after an agent runs based on the stage's terminal state.
    Complete -> next prep (or END). Escalate -> exception node."""
    next_stg = _next_stage(stage)

    def router(state: AppointmentState) -> str:
        s = state.stage_states[stage]
        if s == StageState.ESCALATE:
            return EXCEPTION_NODE
        if s == StageState.COMPLETE:
            if next_stg is None:
                return END
            return _prep_node_name(next_stg)
        # Caught by the AppointmentState model validators upstream, but
        # also a defensive runtime check.
        raise ValueError(
            f"unexpected post-agent state for {stage.value}: {s.value}"
        )

    return router


def _post_exception_router(state: AppointmentState) -> str:
    """After the exception node executes (post-resume), route to the new
    current_stage's prep, or END if the cleared stage was the last one."""
    if state.current_stage is None:
        return END
    return _prep_node_name(state.current_stage)


# ──────────────────────────────────────────────────────────────────────────
# Graph builder
# ──────────────────────────────────────────────────────────────────────────


def _resolve_seed(rng: Optional[random.Random]) -> random.Random:
    if rng is not None:
        return rng
    seed_env = os.environ.get("IKS_SEED")
    if seed_env:
        try:
            return random.Random(int(seed_env))
        except ValueError:
            return random.Random(seed_env)  # accept string seeds too
    return random.Random()


def build_graph(
    *,
    rng: Optional[random.Random] = None,
    tuning_overrides: Optional[dict[StageName, AgentTuning]] = None,
) -> tuple[Any, InMemorySaver]:
    """Build and compile the orchestrator StateGraph.

    Args:
      rng: an injected `random.Random`. Defaults to one seeded by IKS_SEED
        env var, or a fresh Random if unset.
      tuning_overrides: per-stage `AgentTuning` overrides. Stages not in
        the dict use `DEMO_TUNING`. Useful for demos and smoke tests where
        you want a specific stage to force-Complete or force-Escalate.

    Returns:
      (compiled_graph, checkpointer). The checkpointer is returned so the
      caller can inspect / list threads.
    """
    rng = _resolve_seed(rng)
    overrides = tuning_overrides or {}

    g: StateGraph = StateGraph(AppointmentState)

    # ── Nodes: 2 per stage + 1 exception ─────────────────────────────
    for stage, agent_fn in AGENTS_BY_STAGE.items():
        g.add_node(_prep_node_name(stage), _make_prep_node(stage))
        g.add_node(
            _agent_node_name(stage),
            _make_agent_node(
                stage=stage,
                agent_fn=agent_fn,
                rng=rng,
                tuning=overrides.get(stage, DEMO_TUNING),
            ),
        )
    g.add_node(EXCEPTION_NODE, _exception_node)

    # ── START -> conditional -> prep_<current_stage> | EXCEPTION_NODE | END ─
    start_destinations = (
        [_prep_node_name(s) for s in STAGE_ORDER] + [EXCEPTION_NODE, END]
    )
    g.add_conditional_edges(START, _start_router, start_destinations)

    # ── For each stage: prep -> agent (unconditional), agent -> conditional ─
    for stage in STAGE_ORDER:
        g.add_edge(_prep_node_name(stage), _agent_node_name(stage))
        next_stg = _next_stage(stage)
        post_destinations = [EXCEPTION_NODE]
        if next_stg is None:
            post_destinations.append(END)
        else:
            post_destinations.append(_prep_node_name(next_stg))
        g.add_conditional_edges(
            _agent_node_name(stage),
            _make_post_agent_router(stage),
            post_destinations,
        )

    # ── exception -> conditional -> prep_<advanced_current_stage> | END ─
    exc_destinations = [_prep_node_name(s) for s in STAGE_ORDER] + [END]
    g.add_conditional_edges(EXCEPTION_NODE, _post_exception_router, exc_destinations)

    checkpointer = InMemorySaver()
    return g.compile(checkpointer=checkpointer), checkpointer


# ──────────────────────────────────────────────────────────────────────────
# Convenience helpers for the smoke test and (future) FastAPI surface
# ──────────────────────────────────────────────────────────────────────────


def thread_config(appointment_id: str) -> dict[str, Any]:
    """The standard config dict for invoking the graph on a specific
    appointment. thread_id = appointment_id is the canonical mapping."""
    return {"configurable": {"thread_id": appointment_id}}


def extract_interrupt_value(invoke_result: Any) -> Optional[dict]:
    """If the graph paused on an interrupt, return the interrupt value.
    Returns None if the graph completed normally."""
    if not isinstance(invoke_result, dict):
        return None
    interrupts = invoke_result.get("__interrupt__")
    if not interrupts:
        return None
    # __interrupt__ is a tuple of Interrupt objects.
    first = interrupts[0]
    return getattr(first, "value", None)
