# Domain Analysis (Step 1)

This file seeds the architecture. It is consumed by `decisions.md`, `state.py`, and the README.

## 1. Entities (the nouns)

### Core
| Entity | Description | Identity | Notes |
|---|---|---|---|
| **Appointment** | Unit of work flowing through the pipeline. The aggregate root. | `appointment_id` (uuid) | Owns its full state. Denormalized: patient, specialty, client are fields, not separate tables. |
| **Stage** | One of 6 fixed processing steps. Locked, ordered. | `StageName` enum | Stage is a *position in the pipeline*, not a runtime object. The agent is the runtime object. |
| **Agent** | Async function that processes one appointment for one stage. | One per stage, named identically. | Agent ↔ Stage is 1:1. Agents are pure-ish: input state, output state. |
| **Orchestrator** | Selects next appointment to run, drives it through the graph, handles escalations. | Singleton | Owns the LangGraph `StateGraph` and the priority scoring function. |

### Sub-entities (live inside an Appointment)
| Entity | Description | Cardinality on Appointment |
|---|---|---|
| **StageState** | Current state of one stage for one appointment. One of: NotStarted, Processing, Complete, Escalate, Cleared. | 6 per appointment (one per stage) |
| **EscalationReason** | Structured payload created when an agent returns Escalate. `{code, message, suggested_action, agent_context}`. | 0..1 active per appointment; can recur per stage over time |
| **ConciergeResolution** | Human's response to an escalation. `{note, resolved_at, resolver_id}`. | 0..N per appointment (each escalation gets one) |
| **PriorityScore** | Derived numeric score, recomputed every tick. Not persisted as canonical state. | 1 (current) per appointment |

### Identity / categorical entities (dimensions, not entities)
- **Client**: `client_id` (3 of them: e.g. `C-NORTHWELL`, `C-MERCY`, `C-VALLEY`). Affects priority via `client_weight`.
- **Specialty**: 4 categories (e.g. Cardiology, Orthopedics, Dermatology, Primary Care). Affects priority and plausible escalation reasons.
- **Patient**: just a name string in the facade. Not modeled as an entity.

## 2. Relationships

```
Appointment 1 ── 1 Client (by id)
Appointment 1 ── 1 Specialty (by enum)
Appointment 1 ── 6 StageState  (dict: stage_name -> StageState)
Appointment 1 ── 0..1 EscalationReason (active)
Appointment 1 ── 0..N ConciergeResolution (history, append-only)
Stage       1 ── 1 Agent (function reference)
Orchestrator * ── * Appointment (selects, processes, escalates)
Orchestrator 1 ── 1 PriorityScoringFn (pluggable)
Orchestrator 1 ── 1 StateGraph (LangGraph)
```

The interesting relationship is **Appointment ↔ EscalationReason**: it is 0..1 *active* (because the orchestrator interrupts on escalation; there is no second escalation possible until the first is cleared), but conceptually 0..N over the appointment's lifetime. We keep only the active one in `escalation_reason`; resolution history lives in `concierge_resolutions`.

## 3. State transitions

### Per stage (the canonical state machine)

```
                    ┌──────────────┐
                    │  NotStarted  │
                    └──────┬───────┘
                           │ orchestrator picks this appt + stage
                           ▼
                    ┌──────────────┐
                    │  Processing  │
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              │                         │
          (success)                 (issue found)
              │                         │
              ▼                         ▼
        ┌──────────┐             ┌──────────┐
        │ Complete │             │ Escalate │ ──── pauses workflow,
        └──────────┘             └─────┬────┘      raises EscalationReason,
              │                        │           appointment goes to queue
              │                        │
              │                  (concierge resolves)
              │                        │
              │                        ▼
              │                  ┌──────────┐
              │                  │ Cleared  │
              │                  └─────┬────┘
              │                        │
              └────────────┬───────────┘
                           │ both Complete and Cleared advance
                           ▼
                  next stage NotStarted → Processing → ...
```

### Per appointment (derived, not stored)

- **Pending**: at least one stage is NotStarted; no stage is Escalate. Eligible for orchestrator pick-up.
- **In Progress**: at least one stage is Processing.
- **Escalated**: at least one stage is Escalate. Sits in Exception Queue until concierge resolves.
- **Done**: all 6 stages are Complete or Cleared.

The orchestrator never blocks on Done or fully-Escalated appointments. It picks from Pending.

### Workflow narrative (plain English)
1. Tick fires. Orchestrator scores all `Pending` appointments. Highest score wins.
2. Winner enters its current stage's agent. Stage state: NotStarted → Processing.
3. Agent runs (1-4s simulated). Returns Complete or Escalate.
4. **Complete**: stage state → Complete. Orchestrator advances pointer to next stage. If stage 6 Complete, appointment is Done.
5. **Escalate**: stage state → Escalate. EscalationReason persisted. LangGraph `interrupt()` pauses this thread. Appointment surfaces in the Exception Queue.
6. Concierge views the queue, reads the structured reason + agent context, writes a note, clicks "Mark Cleared".
7. Stage state → Cleared. ConciergeResolution appended. LangGraph resumes via `Command(resume=...)`. Workflow advances to next stage.
8. Loop until Done.

## 4. Ambiguities being resolved by decision

These are the moments where the brief is silent or hand-wavy. Each is a defendable choice, not a guess.

### A1. What does "intelligent orchestrator" mean?
- **Brief says**: "intelligently decide which appointments to process first based on dynamic priorities (which may vary by client, specialty, or other unknown factors)."
- **Interpretation**: A pluggable, weighted scoring function. Not an LLM. Inputs: `client_weight`, `specialty_weight`, `sla_urgency`, `age_in_queue`. Output: float. Recomputed every tick.
- **Defense**: An LLM-as-orchestrator is overkill for a deterministic ranking problem, expensive, non-reproducible, and the brief explicitly says "facade." The "intelligence" is in three properties:
  1. **Dynamic**: rescored every tick, so a long-waiting low-priority appointment eventually wins.
  2. **Pluggable**: swap the scoring function without touching the graph.
  3. **Auditable**: a reviewer can see exactly why an appointment was prioritized.
- **If pushed**: "Could we use an LLM here?" Yes, behind the same `score(appointment) -> float` interface. The interface is the architectural commitment; the implementation is swappable.

### A2. Cleared = stage-level or appointment-level state?
- **Brief says**: "update the appointment status to Cleared and resume workflow if necessary."
- **Interpretation**: Cleared is a *stage-level* state. The appointment has no top-level status field; appointment-level status is derived from its stage states.
- **Defense**: A stage was escalated, so the resolution is a fact about that stage. Modeling Cleared at the appointment level loses information (which stage was cleared? from where do we resume?). Stage-level Cleared also makes the multi-escalation case (different stages escalating over the appointment's life) trivial to model.
- **If pushed**: "But the brief says 'appointment status'." We treat that as the user-facing label. Internally, status is derived. The Dashboard pill says "Cleared at Stage 2" rather than just "Cleared."

### A3. After resolution, do we re-run the escalated stage or skip it?
- **Brief says**: "resume workflow if necessary." Silent on direction.
- **Interpretation**: Workflow resumes at **stage N+1**, not stage N. Cleared is treated as terminal-success for advancement.
- **Defense**: Re-running stage N would just escalate again (the agent's view of state hasn't changed). The whole point of human resolution is that the human asserts "this stage's blocking issue is handled, proceed." Cleared is the human's stamp that stage N is effectively done.
- **If pushed**: "What if the resolution is 'this appointment cannot proceed at all'?" Out of scope for the facade; we'd add a `Cancelled` resolution type in v2. Note this in README under "future work."

### A4. Concurrency: serial or parallel processing?
- **Brief says**: silent. "decides which to process first" implies a queue, which implies serial. Out of scope explicitly excludes "multi-user concurrency."
- **Interpretation**: Serial. One appointment advances by one stage per tick. Multiple appointments exist in different stages over time, but the orchestrator processes one at a time.
- **Defense**:
  1. Serial keeps the demo readable; you can watch one thing at a time on screen.
  2. The architectural value is in the orchestration pattern, not in throughput.
  3. Parallelism is a 1-line change (fan out N tasks per tick) once the contract is right; we'd just be picking the top-N instead of top-1.
- **If pushed**: "Production would parallelize." Yes, with a worker pool. The agent contract (pure function over state) is already parallel-safe. No code changes inside agents needed.

### A5. SLA: introduce as a modeling primitive even though brief is silent?
- **Brief says**: nothing about SLA. But the frontend brief mentions "SLA countdown."
- **Interpretation**: Each appointment has `sla_due_at`. Used for: (a) priority scoring (urgency factor), (b) Exception Queue sort and visual urgency, (c) demo storytelling.
- **Defense**: Healthcare ops are SLA-driven (insurance verification within X hours of appointment, for example). Modeling SLA gives the priority function meaningful inputs and gives the concierge UX a sort dimension that *means* something to the role. Not modeling it forces priority into pure abstraction.
- **If pushed**: "You added a feature not in the brief." Two responses:
  1. The frontend brief explicitly named SLA countdown, so it is in scope.
  2. The brief named "dynamic priorities (may vary by ... other unknown factors)" - SLA urgency is exactly the kind of "other unknown factor" the brief invites.

### A6. Mock data shape: how realistic?
- **Brief says**: nothing specific. Backend brief says "20-30 appointments across 3 clients and 4 specialties, 15-20% Escalate probability per stage."
- **Interpretation**: 25 appointments, seeded random, distributed across {3 clients} × {4 specialties}. SLA times spread from "due in 2 hours" to "due in 3 days." Each agent has 2-3 plausible escalation reasons specific to its stage (e.g. Eligibility Verification escalates with `missing_insurance_id`, `expired_coverage`, `out_of_network`).
- **Defense**: Plausibility matters more than volume for a 5-min demo. The demo evaluator should look at an escalation reason and think "yes, that's a real thing that happens at this stage."

## 5. Open questions for Victor

These are real choice points. I'd rather you decide than I assume:

1. **Auto-tick interval, manual tick, or both?** Auto every ~3-5s makes the dashboard feel alive but the demo less predictable. Manual `/admin/tick` gives full control. Hybrid (auto + manual) is the safe answer. Preference?

2. **One agent on a real LLM?** The brief says "one optional agent may use an LLM to demonstrate capability." Strongest narrative beat is: "Pre-Visit Questionnaire summarizes free-text patient symptoms via Claude, then a deterministic check decides Complete vs Escalate." High signal for the JD ("agentic AI development"), modest extra time. Build it, skip it, or stub a hook for it?

3. **Pipeline visualization on the dashboard: row-of-six-pills per appointment, or compact "current stage" badge?** The row-of-pills is denser and more visually impressive but takes more screen real estate per row. The compact badge scales better but tells less of the story. Preference?

4. **Stage history in the Exception Queue: full audit trail (timestamps + transitions) or compact (row of stage badges, color-coded)?** Compact is faster to read at a glance; trail is more impressive for a code-reading evaluator. Lean compact + tooltip-on-hover, but flag if you want heavier.

5. **Demo control: build a "force escalate" button or trust the random seed?** Seeded randomness is reproducible but if you want to show an escalation on demand mid-demo, a button is safer. I lean: trust the seed + a manual `/admin/tick` button, no force-escalate. Agree?

## 6. What is intentionally NOT modeled

Worth being explicit about, because the interviewer may probe absence:

- **Patient as a first-class entity**: just a name. We're not building a CRM.
- **Appointment-level status field**: derived, not stored. Single source of truth = `stage_states`.
- **Audit trail**: brief excluded HIPAA/audit. Mention in README as "production gap."
- **User accounts for the concierge**: no auth. Resolver is a hardcoded mock identity.
- **Real LLM in deterministic agents**: agents 1-5 are simulated. Optional LLM in agent 6 only if you say yes to Q2.
- **Retry / backoff**: Escalate is the failure mode. There is no retry; humans handle it.
- **Cancellation**: appointments cannot be cancelled mid-flight. Future work.
