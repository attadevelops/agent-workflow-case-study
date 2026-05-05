"""Shared agent runtime: simulated work, tuning, escalation candidate type.

All six stage agents import from here. Centralizes the levers the demoer
might want to dial:
  - Jitter range for simulated work (`work_seconds_min/max`)
  - Base escalation probability per agent invocation

`AgentTuning` is a frozen dataclass exposed as `DEMO_TUNING`. To dial demo
intensity (e.g., force escalations for a stress test), construct an
alternative `AgentTuning` and pass it as the agent's `tuning` kwarg. The
default is preserved for normal demo flow.

This module is named with a leading underscore to signal "internal to the
agents subpackage" — agents import freely from here; outside callers should
not depend on these helpers.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.state import EscalationReason, StageName

ResolutionMode = Literal["decisional", "informational"]


@dataclass(frozen=True)
class AgentTuning:
    """Single source of truth for agent runtime knobs."""

    work_seconds_min: float = 1.0
    work_seconds_max: float = 4.0
    # ~15-20% per backend/CLAUDE.md, tuned mid-band for demo readability.
    escalation_probability: float = 0.18


DEMO_TUNING = AgentTuning()


@dataclass
class EscalationCandidate:
    """One plausible failure mode for one agent. Picked via weighted random
    when the agent rolls Escalate.

    `weight` is relative within the catalog — no normalization required.
    `extra_context` is the static portion of the agent_context dict; the
    agent layers in dynamic appointment fields (id, patient name) at build time.

    `default_resolution_mode` is the catalog's *suggestion* for how this code
    is normally resolved:
      • "decisional"  — human judgment supersedes the agent's escalation;
                         workflow advances to stage N+1 on resolve.
      • "informational" — human supplies missing data; stage N re-runs
                         with the resolution payload available to the agent.
    The concierge UI surfaces both options at resolution time and may override
    the default. The chosen mode lands on ConciergeResolution.resolution_type.
    """

    code: str
    message: str
    suggested_action: str
    weight: float
    extra_context: dict[str, Any] = field(default_factory=dict)
    default_resolution_mode: ResolutionMode = "decisional"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def simulate_work(
    rng: random.Random, tuning: AgentTuning = DEMO_TUNING
) -> float:
    """Sleep for a jittered duration. Returns the actual seconds slept."""
    seconds = rng.uniform(tuning.work_seconds_min, tuning.work_seconds_max)
    await asyncio.sleep(seconds)
    return seconds


def maybe_pick_escalation(
    rng: random.Random,
    catalog: list[EscalationCandidate],
    tuning: AgentTuning = DEMO_TUNING,
) -> EscalationCandidate | None:
    """Roll for escalation. Returns a chosen candidate, or None for Complete.

    Empty catalog also returns None (Complete) — guards against an agent
    that hasn't yet defined its escalation set.
    """
    if rng.random() >= tuning.escalation_probability:
        return None
    if not catalog:
        return None
    weights = [c.weight for c in catalog]
    return rng.choices(catalog, weights=weights, k=1)[0]


def build_escalation_reason(
    candidate: EscalationCandidate,
    appointment_id: str,
    patient_name: str,
    raised_at: datetime,
    raised_at_stage: StageName,
) -> EscalationReason:
    """Compose a fully-formed EscalationReason payload from a chosen candidate.

    Layers appointment-specific fields onto the candidate's static context
    so the Exception Queue UI has both the failure code AND the identity of
    what failed.
    """
    return EscalationReason(
        code=candidate.code,
        message=candidate.message,
        suggested_action=candidate.suggested_action,
        agent_context={
            "appointment_id": appointment_id,
            "patient_name": patient_name,
            **candidate.extra_context,
        },
        raised_at=raised_at,
        raised_at_stage=raised_at_stage,
        default_resolution_mode=candidate.default_resolution_mode,
    )
