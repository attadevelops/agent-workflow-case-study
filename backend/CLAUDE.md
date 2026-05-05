# Backend: LangGraph + FastAPI

See root CLAUDE.md for project-wide rules. This file covers backend specifics.

## Why LangGraph
The brief describes a state machine over agents with conditional escalation and human-in-the-loop resume. That is the exact problem LangGraph's `StateGraph` solves. Use it for what it's built for, not as decoration.

Specifically:
- Each of the 6 stages is a node in the graph
- Edges go from stage N to stage N+1 on Complete
- A conditional edge from any stage routes to an `exception` node on Escalate
- LangGraph's `interrupt()` pauses execution at the exception node
- Concierge resolution resumes execution via `Command(resume=...)`
- LangGraph checkpointing (in-memory `MemorySaver`) holds workflow state

If you find yourself building state machine plumbing that LangGraph already provides, stop and use the LangGraph primitive instead.

## State schema
A single Pydantic model `AppointmentState` carries all data through the graph:
- appointment_id, patient_name, specialty, client_id
- priority_score (computed by orchestrator)
- current_stage (enum)
- stage_states: dict mapping stage -> StageState (NotStarted/Processing/Complete/Escalate)
- escalation_reason: optional structured object
- concierge_resolution: optional resolution payload
- created_at, updated_at, sla_due_at

Define enums as Python `StrEnum` so JSON serialization stays clean for the frontend.

## Agent contract
Every stage agent is an async function with this signature:
```python
async def stage_name(state: AppointmentState) -> AppointmentState
```
Each agent must:
1. Set its stage_state to Processing on entry
2. Simulate work (asyncio.sleep with jittered duration, ~1-4s)
3. Return one of: Complete (advance), Escalate (with reason payload)
4. NEVER silently fail. Any unexpected error becomes an Escalate with reason "internal_error" and the exception message.

## Escalation reason payload (structured, not free text)
```python
class EscalationReason(BaseModel):
    code: str           # e.g. "missing_insurance_id", "auth_denied"
    message: str        # human-readable
    suggested_action: str | None
    agent_context: dict # whatever the agent saw
```
The Exception Queue UI renders this directly. Make it useful.

## Orchestrator
`orchestrator.py` owns:
- The LangGraph `StateGraph` definition
- The priority scoring function (pluggable; weighted sum of client_weight, specialty_weight, sla_urgency, age_in_queue)
- The "tick" that pulls the highest-priority NotStarted/Cleared appointment and runs it through the graph

Re-score on every tick, not on enqueue. This is how dynamic priorities stay dynamic.

## FastAPI surface (minimal)
- `GET  /appointments`           list with current state
- `GET  /appointments/{id}`      detail
- `GET  /exceptions`             items currently escalated
- `POST /exceptions/{id}/resolve` concierge resolution; resumes workflow
- `POST /admin/seed`             reset and seed mock data
- `POST /admin/tick`             manually advance orchestrator (for demo control)

No auth. No validation beyond Pydantic. No error middleware beyond a global handler that logs and returns 500.

## Mock data
20-30 appointments across 3 clients and 4 specialties, with varied SLA due times. Bake in ~15-20% Escalate probability per stage so the Exception Queue populates naturally during demo.

## Determinism for demo
Use a seeded random so demos are reproducible. Expose seed as an env var.

## What NOT to do
- No database. In-memory dict is fine.
- No Celery/RQ/background workers. The orchestrator tick runs in a FastAPI background task.
- No real LLM calls unless explicitly asked.
- No WebSockets. Polling is the contract.
