"""Priority scoring strategies.

Symmetric output contract (per orchestrator design): both strategies mutate
`priority_score` (float) and `priority_reasoning` (str | None) on every
appointment they rank. They differ only in the *mechanism* that produces
those values.

  • WeightedSumStrategy: deterministic, auditable, fast. Weighted sum of
    SLA urgency, client weight, specialty weight, queue age. Default.

  • LLMRuleStrategy: natural-language rules ranked by an LLM. Same output
    shape; gated by the same MOCK_LLM convention as Pre-Visit Questionnaire.

The tick loop in `store.py` is unaware of which strategy is in play — it
calls `await strategy.rank(...)` and consumes the same result shape either
way. This is what "pluggability" means concretely.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from app.state import AppointmentState, ClientId, Specialty


# ──────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ──────────────────────────────────────────────────────────────────────────
# Strategy protocol
# ──────────────────────────────────────────────────────────────────────────


@runtime_checkable
class PriorityStrategy(Protocol):
    """All strategies implement this contract.

    Returns: a list of AppointmentState (model_copies of the inputs) with
    `priority_score` and `priority_reasoning` populated, ordered by score
    descending. The first element is the next appointment to tick.
    """

    name: str

    async def rank(
        self,
        appointments: list[AppointmentState],
        now: datetime,
    ) -> list[AppointmentState]: ...


# ──────────────────────────────────────────────────────────────────────────
# WeightedSumStrategy (default)
# ──────────────────────────────────────────────────────────────────────────

# Weights are named module-level constants — code reviewer can see the
# entire configuration surface at a glance.
SLA_URGENCY_WEIGHT = 0.45
CLIENT_WEIGHT = 0.20
SPECIALTY_WEIGHT = 0.20
QUEUE_AGE_WEIGHT = 0.15
# Sanity check: weights should sum to 1.0 so scores are normalized to [0,1].
assert abs(
    SLA_URGENCY_WEIGHT + CLIENT_WEIGHT + SPECIALTY_WEIGHT + QUEUE_AGE_WEIGHT - 1.0
) < 1e-9

# SLA urgency normalizes to [0,1]: deadline within 0h = 1.0; deadline 72h+
# out = 0.0. Anything past deadline still pegs at 1.0.
SLA_MAX_HOURS = 72.0
# Queue age normalizes to [0,1]: created 96h+ ago = 1.0 (anti-starvation).
AGE_MAX_HOURS = 96.0

CLIENT_PRIORITY: dict[ClientId, float] = {
    ClientId.NORTHWELL: 1.00,  # premium
    ClientId.MERCY: 0.70,
    ClientId.VALLEY: 0.50,
}

SPECIALTY_PRIORITY: dict[Specialty, float] = {
    Specialty.CARDIOLOGY: 0.95,
    Specialty.ORTHOPEDICS: 0.75,
    Specialty.PRIMARY_CARE: 0.60,
    Specialty.DERMATOLOGY: 0.45,
}


class WeightedSumStrategy:
    """Deterministic weighted sum. Auditable per-appointment reasoning."""

    name: str = "weighted_sum"

    async def rank(
        self,
        appointments: list[AppointmentState],
        now: datetime,
    ) -> list[AppointmentState]:
        ranked: list[AppointmentState] = []
        for a in appointments:
            sla_hours_remaining = (a.sla_due_at - now).total_seconds() / 3600
            sla_urgency = _clamp01(1.0 - max(sla_hours_remaining, 0.0) / SLA_MAX_HOURS)

            client = CLIENT_PRIORITY.get(a.client_id, 0.5)
            specialty = SPECIALTY_PRIORITY.get(a.specialty, 0.5)

            age_hours = (now - a.created_at).total_seconds() / 3600
            age = _clamp01(age_hours / AGE_MAX_HOURS)

            score = (
                sla_urgency * SLA_URGENCY_WEIGHT
                + client * CLIENT_WEIGHT
                + specialty * SPECIALTY_WEIGHT
                + age * QUEUE_AGE_WEIGHT
            )

            reasoning = (
                f"SLA {sla_urgency:.2f}, client {client:.2f}, "
                f"specialty {specialty:.2f}, age {age:.2f} -> {score:.3f}"
            )
            ranked.append(
                a.model_copy(
                    update={
                        "priority_score": score,
                        "priority_reasoning": reasoning,
                    }
                )
            )
        ranked.sort(key=lambda x: -(x.priority_score or 0.0))
        return ranked


# ──────────────────────────────────────────────────────────────────────────
# LLMRuleStrategy (mock-default seam)
# ──────────────────────────────────────────────────────────────────────────

# Default rules are inline. Production: load from config (file or DB) so
# ops can adjust without redeploys.
DEFAULT_RULES = (
    "Premium clients (C-NORTHWELL) get priority over Standard "
    "(C-MERCY, C-VALLEY). Cardiology specialty takes precedence over "
    "Dermatology. Appointments within 24 hours of SLA get a max-urgency "
    "boost regardless of other factors. Older queue items (>48h) get a "
    "moderate boost to prevent starvation."
)


SYSTEM_PROMPT = (
    "You are a medical-appointment scheduling assistant. Given a list of "
    "pending appointments and a set of natural-language priority rules, "
    "score each appointment 0.0 to 1.0 (higher = higher priority for the "
    "next tick) and explain your reasoning in one short sentence per "
    "appointment.\n\n"
    "Return JSON only, matching this schema exactly:\n"
    "  rankings: list of objects with keys {appointment_id (string), "
    "score (float 0.0-1.0), reasoning (string)}\n"
    "Apply the rules consistently across all appointments. Score every "
    "appointment in the input — do not omit any."
)


class _LLMRankItem(BaseModel):
    appointment_id: str
    score: float
    reasoning: str


class _LLMRanking(BaseModel):
    rankings: list[_LLMRankItem]


def _mock_llm_active() -> bool:
    return os.environ.get("MOCK_LLM", "true").lower() not in ("false", "0", "no")


class LLMRuleStrategy:
    """Natural-language rules ranked by Claude. Real call gated by MOCK_LLM.

    Mock and real branches return identical `_LLMRanking` shape; surrounding
    code cannot tell them apart — same shape-parity discipline as the
    Pre-Visit Questionnaire agent.

    Production architecture note: a real LLM call against 25 appointments
    takes 1-3s; the tick runs every 4s. This strategy does the LLM call
    synchronously on every tick, which is fine because MOCK_LLM=true keeps
    latency at zero. In production you'd decouple scoring cadence from
    tick cadence: score every 30s, cache the results, the tick reads cached
    scores. The seam is a thin wrapper around `rank()` that memoizes its
    output for N seconds. Acknowledged here, not exercised in the facade.
    """

    name: str = "llm_rule"

    def __init__(self, rules: Optional[str] = None) -> None:
        self.rules = rules if rules is not None else DEFAULT_RULES

    async def rank(
        self,
        appointments: list[AppointmentState],
        now: datetime,
    ) -> list[AppointmentState]:
        ranking = await self._llm_rank(appointments, now)
        by_id = {r.appointment_id: r for r in ranking.rankings}
        mode_tag = "mock" if _mock_llm_active() else "real"

        ranked: list[AppointmentState] = []
        for a in appointments:
            entry = by_id.get(a.appointment_id)
            if entry is None:
                ranked.append(
                    a.model_copy(
                        update={
                            "priority_score": 0.0,
                            "priority_reasoning": (
                                f"[llm_rule:{mode_tag}] omitted by ranker; "
                                f"defaulted to 0.0"
                            ),
                        }
                    )
                )
            else:
                ranked.append(
                    a.model_copy(
                        update={
                            "priority_score": entry.score,
                            "priority_reasoning": (
                                f"[llm_rule:{mode_tag}] {entry.reasoning}"
                            ),
                        }
                    )
                )
        ranked.sort(key=lambda x: -(x.priority_score or 0.0))
        return ranked

    async def _llm_rank(
        self, appointments: list[AppointmentState], now: datetime
    ) -> _LLMRanking:
        if _mock_llm_active():
            return self._mock_rank(appointments, now)
        return await self._real_rank(appointments, now)

    def _mock_rank(
        self, appointments: list[AppointmentState], now: datetime
    ) -> _LLMRanking:
        """Canned scoring that loosely follows the default rules. Returns the
        identical shape the real call would parse — surrounding code cannot
        distinguish mock from real."""
        items: list[_LLMRankItem] = []
        for a in appointments:
            score = 0.50
            reasons: list[str] = []

            sla_hours_remaining = (a.sla_due_at - now).total_seconds() / 3600
            if sla_hours_remaining <= 24:
                score = 1.00
                reasons.append("max-urgency boost (SLA within 24h)")
            else:
                if a.client_id == ClientId.NORTHWELL:
                    score += 0.20
                    reasons.append("premium client")
                if a.specialty == Specialty.CARDIOLOGY:
                    score += 0.15
                    reasons.append("cardiology precedence")
                age_hours = (now - a.created_at).total_seconds() / 3600
                if age_hours > 48:
                    score += 0.10
                    reasons.append("starvation guard (>48h queued)")

            items.append(
                _LLMRankItem(
                    appointment_id=a.appointment_id,
                    score=_clamp01(score),
                    reasoning="; ".join(reasons) if reasons else "baseline",
                )
            )
        return _LLMRanking(rankings=items)

    async def _real_rank(
        self, appointments: list[AppointmentState], now: datetime
    ) -> _LLMRanking:
        """Real anthropic SDK call. Disabled by default; set MOCK_LLM=false
        and `pip install -e .[llm]` to enable.

        The system prompt is cached (ephemeral) since it doesn't change
        across calls. The user message changes per tick (different SLA
        windows, different queue ages) and isn't cached.
        """
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()

        appointment_summary = json.dumps(
            [
                {
                    "appointment_id": a.appointment_id,
                    "patient_name": a.patient_name,
                    "client_id": a.client_id.value,
                    "specialty": a.specialty.value,
                    "procedure": a.procedure,
                    "sla_hours_remaining": round(
                        (a.sla_due_at - now).total_seconds() / 3600, 1
                    ),
                    "age_hours": round(
                        (now - a.created_at).total_seconds() / 3600, 1
                    ),
                }
                for a in appointments
            ]
        )

        user_message = (
            f"Priority rules:\n{self.rules}\n\n"
            f"Appointments to rank:\n{appointment_summary}"
        )

        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text
        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            return _LLMRanking(**json.loads(cleaned))
        except (json.JSONDecodeError, ValidationError) as e:
            # Defensive: neutral 0.5 across the board so the tick still
            # has SOMETHING to rank with rather than crashing the loop.
            return _LLMRanking(
                rankings=[
                    _LLMRankItem(
                        appointment_id=a.appointment_id,
                        score=0.5,
                        reasoning=f"llm parse failed ({type(e).__name__}); neutral fallback",
                    )
                    for a in appointments
                ]
            )


# ──────────────────────────────────────────────────────────────────────────
# Registry — for /admin/strategy hot-swap
# ──────────────────────────────────────────────────────────────────────────


def make_strategy(name: str) -> PriorityStrategy:
    if name == "weighted_sum":
        return WeightedSumStrategy()
    if name == "llm_rule":
        return LLMRuleStrategy()
    raise ValueError(f"unknown strategy: {name!r}")
