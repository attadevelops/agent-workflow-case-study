"""Stage 5 agent: Pre-Visit Questionnaire (the LLM seam).

Real-world responsibility: process the patient's free-text pre-visit
questionnaire, extract structured information (symptoms, medications,
allergies, family history), flag clinically concerning findings, and decide
whether the data is complete enough to proceed.

This is the only agent that uses an LLM. The architecture intentionally
separates extraction from decision:

  • The LLM does EXTRACTION. Free text in -> structured `QuestionnaireExtraction`
    out (extracted_fields, clinical_flags, completeness_score). LLMs are
    excellent sensors for this kind of mapping.
  • The agent does DECISION. The mapping from extraction -> Complete/Escalate
    is a deterministic, auditable policy in `_decide()`. The LLM does not
    decide whether to escalate; the policy does.

Why this matters: if a future version replaces Claude with a different
model, the policy doesn't change. If the policy needs to change (new
threshold, new flag list), the LLM doesn't need touching. The LLM is the
noisy sensor; the agent is the policy.

The seam is gated by `MOCK_LLM` (default true). The mock branch returns the
exact same `QuestionnaireExtraction` shape as the real branch, so callers
cannot distinguish them. The real branch uses the live anthropic SDK with a
proper system + user message and prompt caching on the system prompt.

Failure modes (catalog):
  • incomplete_questionnaire: completeness_score below threshold
  • clinical_flag_review_required: extraction surfaced concerning findings
  • patient_unresponsive: no questionnaire was returned at all
  • extraction_low_confidence: model output failed schema validation
"""

from __future__ import annotations

import json
import os
import random
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from app.agents._runtime import (
    DEMO_TUNING,
    AgentTuning,
    EscalationCandidate,
    build_escalation_reason,
    simulate_work,
    utc_now,
)
from app.state import (
    AppointmentState,
    Specialty,
    StageName,
    StageRuntime,
    StageState,
)

STAGE = StageName.PRE_VISIT_QUESTIONNAIRE

# Below this completeness, the policy escalates as `incomplete_questionnaire`.
COMPLETENESS_THRESHOLD = 0.70


# ──────────────────────────────────────────────────────────────────────────
# Extraction contract — both LLM branches return this shape.
# ──────────────────────────────────────────────────────────────────────────


class QuestionnaireExtraction(BaseModel):
    """Returned by both the mock and real LLM extract paths.

    The shape is the contract. Surrounding code cannot tell whether the
    extraction came from Claude or from the canned mock — that's what makes
    the seam provably correct.
    """

    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    clinical_flags: list[str] = Field(default_factory=list)
    completeness_score: float = 0.0


# ──────────────────────────────────────────────────────────────────────────
# LLM seam (mock + real). Defaults to mock.
# ──────────────────────────────────────────────────────────────────────────


def _mock_llm_active() -> bool:
    """Read MOCK_LLM env var. Defaults true so demos never accidentally
    spend tokens. Set MOCK_LLM=false to enable the real call."""
    return os.environ.get("MOCK_LLM", "true").lower() not in ("false", "0", "no")


SYSTEM_PROMPT = (
    "You are a clinical intake assistant. Given a patient's pre-visit "
    "questionnaire response (free text), extract the information into a "
    "structured object and identify any clinically concerning findings "
    "that warrant clinician review before the appointment.\n\n"
    "Return JSON only, matching this schema exactly:\n"
    "  extracted_fields: object with keys symptoms (list of strings), "
    "symptom_duration (string), current_medications (list), allergies "
    "(list), family_history (list)\n"
    "  clinical_flags: list of strings drawn from this allowed set: "
    "{new_cardiac_symptoms, suicidal_ideation, severe_pain_uncontrolled, "
    "family_cardiac_history, uncontrolled_diabetes_signs}\n"
    "  completeness_score: float between 0.0 and 1.0 reflecting how "
    "thoroughly the patient answered.\n\n"
    "Be conservative on clinical_flags — include only ones supported by "
    "the patient's text. Do not invent findings."
)


# Placeholder questionnaire text. In production this would be fetched from
# the patient's record or a prior pipeline stage; for the facade this is
# the literal text the real LLM call processes.
_PLACEHOLDER_QUESTIONNAIRE = (
    "Symptoms: chest discomfort on exertion the last 3 weeks, occasional "
    "shortness of breath when climbing stairs.\n"
    "Medications: lisinopril 10mg daily, atorvastatin 20mg.\n"
    "Allergies: penicillin (rash).\n"
    "Family history: father had heart attack at age 58."
)


def _build_user_message(state: AppointmentState) -> str:
    return (
        f"Patient: {state.patient_name}\n"
        f"Specialty: {state.specialty.value}\n"
        f"Procedure: {state.procedure}\n\n"
        f"Questionnaire response:\n{_PLACEHOLDER_QUESTIONNAIRE}"
    )


def _mock_extract(state: AppointmentState, rng: random.Random) -> QuestionnaireExtraction:
    """Canned extraction with specialty-aware variation so the demo feels
    alive across multiple appointments without burning tokens."""
    base = QuestionnaireExtraction(
        extracted_fields={
            "symptoms": ["chest discomfort on exertion", "shortness of breath"],
            "symptom_duration": "3 weeks",
            "current_medications": ["lisinopril 10mg", "atorvastatin 20mg"],
            "allergies": ["penicillin"],
            "family_history": ["father - MI age 58"],
        },
        clinical_flags=[],
        completeness_score=0.92,
    )
    # Specialty-aware noise so different appointments produce different paths.
    if state.specialty == Specialty.CARDIOLOGY:
        if rng.random() < 0.30:
            base.clinical_flags = ["new_cardiac_symptoms", "family_cardiac_history"]
    elif state.specialty == Specialty.PRIMARY_CARE:
        if rng.random() < 0.20:
            base.completeness_score = 0.55
    return base


async def _real_extract(state: AppointmentState) -> QuestionnaireExtraction:
    """Real anthropic SDK call. Disabled by default (MOCK_LLM defaults true).

    Enable with `pip install -e .[llm]` and `MOCK_LLM=false`. The SDK reads
    `ANTHROPIC_API_KEY` from the environment.

    Prompt caching is enabled on the system prompt because in steady-state
    the questionnaire stage runs repeatedly with identical instructions and
    only the user-message portion (per patient) changes.
    """
    from anthropic import AsyncAnthropic  # lazy import — keeps mock path dep-free

    client = AsyncAnthropic()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {"role": "user", "content": _build_user_message(state)},
        ],
    )

    raw_text = response.content[0].text
    cleaned = (
        raw_text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        parsed = json.loads(cleaned)
        return QuestionnaireExtraction(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        # Surface as a low-confidence extraction; the agent's _decide will
        # convert this to an `extraction_low_confidence` escalation.
        return QuestionnaireExtraction(
            extracted_fields={"_raw": raw_text, "_parse_error": str(e)},
            clinical_flags=[],
            completeness_score=0.0,
        )


async def _extract(
    state: AppointmentState, rng: random.Random
) -> QuestionnaireExtraction:
    if _mock_llm_active():
        return _mock_extract(state, rng)
    return await _real_extract(state)


# ──────────────────────────────────────────────────────────────────────────
# Catalog (the policy picks which one applies; the LLM never picks)
# ──────────────────────────────────────────────────────────────────────────


CATALOG: list[EscalationCandidate] = [
    EscalationCandidate(
        code="incomplete_responses",
        message=(
            f"Patient's questionnaire response is below the "
            f"{int(COMPLETENESS_THRESHOLD * 100)}% completeness threshold."
        ),
        suggested_action=(
            "Contact patient to complete missing sections; supply the "
            "additional answers via informational resolution."
        ),
        weight=2.0,
        extra_context={"completeness_threshold": COMPLETENESS_THRESHOLD},
        default_resolution_mode="informational",
    ),
    EscalationCandidate(
        code="clinical_flag_detected",
        message=(
            "Extraction surfaced clinical findings that warrant clinician "
            "review before the appointment."
        ),
        suggested_action=(
            "Route to clinical team for triage; clinician judgment "
            "supersedes (decisional)."
        ),
        weight=3.0,
        extra_context={"requires_clinician_review": True},
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="patient_unresponsive",
        message=(
            "No questionnaire response received within the required "
            "pre-visit window."
        ),
        suggested_action=(
            "Plan to administer at check-in with an extended slot "
            "(decisional). If patient finally responded, override to "
            "informational and supply their answers."
        ),
        weight=2.0,
        extra_context={"outreach_attempts": 2, "preferred_contact": "sms"},
        default_resolution_mode="decisional",
    ),
    EscalationCandidate(
        code="extraction_low_confidence",
        message=(
            "Extraction model returned output that failed schema validation. "
            "Human review required to avoid downstream bad data."
        ),
        suggested_action=(
            "Have a human transcribe the questionnaire response into the "
            "structured fields and supply via informational resolution."
        ),
        weight=1.0,
        extra_context={"validation_errors": ["schema_mismatch"]},
        default_resolution_mode="informational",
    ),
]

# Index for the policy. Stays alongside the catalog so renames stay in sync.
_CODE_TO_CANDIDATE = {c.code: c for c in CATALOG}


# ──────────────────────────────────────────────────────────────────────────
# Domain logic — deterministic, auditable, LLM-free.
# ──────────────────────────────────────────────────────────────────────────


def _decide(extraction: QuestionnaireExtraction) -> EscalationCandidate | None:
    """Map extraction -> Complete (None) or Escalate (a chosen candidate).

    Order matters: completeness gate first (cheapest signal of "we don't
    have enough data to evaluate"), then clinical flags (only meaningful
    once we have enough data to look at).
    """
    if extraction.completeness_score < COMPLETENESS_THRESHOLD:
        return _CODE_TO_CANDIDATE["incomplete_responses"]
    if extraction.clinical_flags:
        return _CODE_TO_CANDIDATE["clinical_flag_detected"]
    return None


# ──────────────────────────────────────────────────────────────────────────
# Agent function — same contract as the other 5.
# ──────────────────────────────────────────────────────────────────────────


async def pre_visit_questionnaire(
    state: AppointmentState,
    *,
    rng: Optional[random.Random] = None,
    tuning: AgentTuning = DEMO_TUNING,
) -> AppointmentState:
    """Decide Complete or Escalate for the Pre-Visit Questionnaire stage.

    The LLM extracts; this agent decides. See module docstring for the full
    rationale.

    Note on tuning: this agent is the only one whose escalation is decision-
    based, not RNG-based. `tuning.escalation_probability` is therefore not
    consulted; only `tuning.work_seconds_min/max` (which simulates the LLM
    round-trip latency) is used. Forcing escalation in tests is done by
    constructing a state whose mock extraction trips the policy (e.g., a
    cardiology specialty plus a seed that hits the 30% flag branch).
    """
    if rng is None:
        rng = random.Random()

    started_at = utc_now()
    await simulate_work(rng, tuning)  # Simulates the LLM round-trip latency.
    extraction = await _extract(state, rng)
    finished_at = utc_now()

    runtime = StageRuntime(started_at=started_at, finished_at=finished_at)
    new_stage_states = {**state.stage_states}
    new_stage_runtimes = {**state.stage_runtimes, STAGE: runtime}

    candidate = _decide(extraction)

    if candidate is None:
        new_stage_states[STAGE] = StageState.COMPLETE
        return state.model_copy(
            update={
                "stage_states": new_stage_states,
                "stage_runtimes": new_stage_runtimes,
                "updated_at": finished_at,
            }
        )

    # Layer the LLM extraction into the agent_context so the Exception Queue
    # surfaces what the model actually saw — useful for the concierge.
    enriched = EscalationCandidate(
        code=candidate.code,
        message=candidate.message,
        suggested_action=candidate.suggested_action,
        weight=candidate.weight,
        extra_context={
            **candidate.extra_context,
            "completeness_score": extraction.completeness_score,
            "clinical_flags": extraction.clinical_flags,
            "extracted_fields": extraction.extracted_fields,
            "llm_mode": "mock" if _mock_llm_active() else "real",
        },
    )
    new_stage_states[STAGE] = StageState.ESCALATE
    escalation = build_escalation_reason(
        candidate=enriched,
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
