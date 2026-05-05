"""In-memory appointment store + orchestrator wrapper.

The dashboard's read path (the FastAPI surface) reads from this store.
The orchestrator's resume path uses the LangGraph checkpointer the store
holds. They share state via the appointment_id == thread_id mapping.

Threading model: single-process, single-threaded for the demo. tick() and
resolve() are awaited on the asyncio loop and serialized by an internal
lock so two concurrent invocations don't overlap on the same appointment.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.types import Command

from app.mock_data import seed_appointments
from app.orchestrator import (
    build_graph,
    extract_interrupt_value,
    thread_config,
)
from app.state import AppointmentState


def is_pickable(state: AppointmentState) -> bool:
    """An appointment is pickable for the next tick if it's not currently
    escalated (waiting on concierge) and not yet complete."""
    if state.escalation_reason is not None:
        return False
    if state.current_stage is None:
        return False
    return True


def is_escalated(state: AppointmentState) -> bool:
    return state.escalation_reason is not None


def is_complete(state: AppointmentState) -> bool:
    return state.current_stage is None


def _state_from_invoke(result: Any) -> AppointmentState:
    """LangGraph returns a dict for pydantic state. Reconstruct the model.
    Excludes synthetic __interrupt__ keys the framework adds on pause."""
    if isinstance(result, dict):
        cleaned = {k: v for k, v in result.items() if not k.startswith("__")}
        return AppointmentState.model_validate(cleaned)
    return result


class AppointmentStore:
    """Single source of truth for the read path. Wraps the LangGraph
    orchestrator for the write path (tick, resolve)."""

    def __init__(self, strategy: Any = None) -> None:
        # Strategy is filled in at step 7 piece B. None during piece A.
        self._strategy = strategy
        self._graph, self._checkpointer = build_graph()
        self._appointments: dict[str, AppointmentState] = {}
        self._lock = asyncio.Lock()

    # ── Lifecycle ────────────────────────────────────────────────────

    async def seed(self, now: Optional[datetime] = None) -> None:
        """Load the 25 hand-tuned mock appointments anchored to `now`.

        Pre-escalated appointments (seed-time `escalation_reason` set, e.g.
        APT-06, APT-14) are primed through the graph so a checkpoint exists
        at the exception node. Without this priming, the concierge resolve
        path has nothing to resume — `Command(resume=...)` against a
        non-existent thread silently produces an empty state and 400s on
        response validation. The graph's `_start_router` routes
        already-escalated appointments straight to the exception node, so
        priming is one `ainvoke` per pre-escalation.
        """
        anchor = now or datetime.now(timezone.utc)
        self._appointments = {
            apt.appointment_id: apt for apt in seed_appointments(now=anchor)
        }
        for apt in list(self._appointments.values()):
            if apt.escalation_reason is not None:
                config = thread_config(apt.appointment_id)
                await self._graph.ainvoke(apt, config=config)

    def set_strategy(self, strategy: Any) -> None:
        """Hot-swap the priority strategy. Called by the FastAPI admin
        layer when the demoer toggles WeightedSum vs LLMRule."""
        self._strategy = strategy

    @property
    def strategy(self) -> Any:
        return self._strategy

    # ── Read path ────────────────────────────────────────────────────

    def list(self) -> list[AppointmentState]:
        return list(self._appointments.values())

    def get(self, appointment_id: str) -> Optional[AppointmentState]:
        return self._appointments.get(appointment_id)

    def exceptions(self) -> list[AppointmentState]:
        """Appointments currently waiting on concierge resolution."""
        return [a for a in self._appointments.values() if is_escalated(a)]

    def pickable(self) -> list[AppointmentState]:
        """Appointments eligible for the next tick (not escalated, not done)."""
        return [a for a in self._appointments.values() if is_pickable(a)]

    # ── Write path (filled in for step 7 piece B) ────────────────────

    async def tick(self) -> Optional[str]:
        """Pick the highest-priority pickable appointment, advance it via
        the graph by one stage (or until it pauses on escalation).

        Returns the appointment_id ticked, or None if nothing was pickable
        (per guardrail: empty-pool tick is a no-op, not an error).

        Wired in step 7 piece B once the strategy module exists.
        """
        async with self._lock:
            pool = self.pickable()
            if not pool:
                return None
            if self._strategy is None:
                # No strategy yet (piece A state). Pick by appointment_id
                # for stable behavior — replaced by strategy ranking in piece B.
                pool.sort(key=lambda a: a.appointment_id)
                ranked = pool
            else:
                ranked = await self._strategy.rank(pool, now=datetime.now(timezone.utc))
                # Strategy returns a new list with priority_score/reasoning
                # populated. Persist all updated scores so the dashboard
                # sees the rescore, not just the winner.
                for a in ranked:
                    self._appointments[a.appointment_id] = a

            winner = ranked[0]
            config = thread_config(winner.appointment_id)
            result = await self._graph.ainvoke(winner, config=config)
            self._appointments[winner.appointment_id] = _state_from_invoke(result)
            return winner.appointment_id

    async def resolve(
        self, appointment_id: str, payload: dict
    ) -> AppointmentState:
        """Apply a concierge resolution to a paused appointment thread.
        Resumes the graph via Command(resume=payload). Returns the new
        appointment state."""
        async with self._lock:
            current = self._appointments.get(appointment_id)
            if current is None:
                raise KeyError(f"unknown appointment_id: {appointment_id}")
            if not is_escalated(current):
                raise ValueError(
                    f"appointment {appointment_id} is not currently escalated"
                )
            config = thread_config(appointment_id)
            result = await self._graph.ainvoke(
                Command(resume=payload), config=config
            )
            new_state = _state_from_invoke(result)
            self._appointments[appointment_id] = new_state
            return new_state

    # ── Diagnostics for /health ──────────────────────────────────────

    def stats(self) -> dict[str, int]:
        appts = list(self._appointments.values())
        return {
            "total": len(appts),
            "pickable": sum(1 for a in appts if is_pickable(a)),
            "escalated": sum(1 for a in appts if is_escalated(a)),
            "complete": sum(1 for a in appts if is_complete(a)),
        }
