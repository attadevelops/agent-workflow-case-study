# Project: Agentic Workflow Management System (Interview Facade)

## What this is
A high-level facade for an interview case study. Deliverable is a working demo of an agentic workflow that processes medical appointments, plus a short README explaining architectural decisions.

This is NOT production code. When in doubt, mock it. Do not add features that are not in the brief.

## The Brief (verbatim)

The Context: As part of our interview process, we want to see how you tackle real-world product challenges. We aren't looking for a fully functional, production-ready application. Instead, we want to see a high-level facade or prototype that demonstrates your architectural thinking, product mindset, and UI approach.

The Goal: Design and build a facade for an Agentic Workflow Management System that processes medical appointments.

Core Product Requirements:
- Intelligent Orchestrator: A master agent that ingests a feed of appointments from a database. It must intelligently decide which appointments to process first based on dynamic priorities (which may vary by client, specialty, or other unknown factors).
- Agentic Processing: Appointments go through a configurable number of processing stages (e.g., 6 stages). Each stage should be conceptualized as an individual agent.
- Standardized Outputs: Each processing stage must return one of four states: Not Started, Processing, Complete, or Escalate.
- The Exception Queue: If an agent returns Escalate, the appointment must be routed to a human-in-the-loop Exception Queue.
- Human Concierge Resolution: A human user must be able to interact with the Exception Queue to unblock the issue. Once resolved, the system should immediately update the appointment status to Cleared and resume workflow if necessary.

Deliverables: high-level working facade (UI + mocked backend/logic) and a brief summary of architectural decisions (short ReadMe or diagram).

Evaluation criteria:
- Agent Architecture: thought process behind structuring the master orchestrator and the individual, separate agents.
- UI/UX Design: how user-centric the interface is, particularly how the human concierge interacts with the Exception Queue.
- Product Mindset: how effectively the core problem was understood and ambiguous, dynamic requirements were translated into a logical system design.

## Role context
Full-stack engineering role focused on agentic AI development. LangGraph is named in the JD. The evaluator will read code AND watch a live walkthrough.

## In Scope
- LangGraph-based orchestrator with 6 stage agents
- FastAPI backend exposing orchestrator state and concierge resolution
- React frontend with two views: orchestrator dashboard + Exception Queue
- Mocked appointment data, no real DB
- Deterministic agent logic with controlled randomness for Escalate paths
- README with architecture diagram and decision rationale

## Out of Scope (do not build)
- Real auth / authorization
- Real database (use in-memory state)
- Real LLM calls inside agents (mocked is fine; one optional agent may use an LLM to demonstrate capability)
- Multi-user concurrency
- Audit trails / HIPAA controls (mention in README, do not implement)
- Tests beyond smoke checks
- Deployment / Docker / CI

## Locked Decisions

### The 6 stages (do not rename, add, or remove)
1. Eligibility Verification
2. Prior Authorization
3. Patient Intake
4. Referral Validation
5. Pre-Visit Questionnaire
6. Appointment Confirmation

### The four states (verbatim from brief)
- Not Started
- Processing
- Complete
- Escalate

Plus one resolution state used by the concierge flow:
- Cleared (set when concierge resolves an Escalate)

### Architectural assertion
Every Escalate MUST carry a structured reason payload. No silent escalations. The Exception Queue UI consumes this payload directly. This is the contract between agents and the human concierge.

### Stack
- Backend: Python 3.11+, LangGraph, FastAPI, Pydantic
- Frontend: Vite + React 18 + TypeScript + Tailwind + shadcn/ui
- State: in-memory on the backend; frontend polls every 2 seconds

## Folder layout
```
/
├── CLAUDE.md                  (this file)
├── README.md                  (final deliverable, generated late)
├── decisions.md               (decision log, append-only)
├── prompts.md                 (Claude Code prompt log, append-only)
├── backend/
│   ├── CLAUDE.md
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            (FastAPI entrypoint)
│   │   ├── orchestrator.py    (LangGraph StateGraph)
│   │   ├── agents/            (one file per stage)
│   │   ├── state.py           (Pydantic models, enums)
│   │   ├── store.py           (in-memory state store)
│   │   └── mock_data.py       (seed appointments)
└── frontend/
    ├── CLAUDE.md
    ├── package.json
    └── src/
        ├── App.tsx
        ├── api.ts             (backend client)
        ├── types.ts           (mirrors backend Pydantic)
        ├── views/
        │   ├── Dashboard.tsx
        │   └── ExceptionQueue.tsx
        └── components/
```

## Coding posture
- Clarity over cleverness. An interviewer will read this.
- Comments explain *why*, not *what*. Especially around tradeoffs.
- No premature abstraction. One implementation first; abstract only on second use.
- Fail loudly. This is a demo; silent bugs are catastrophic.
- Match the locked stack. Do not introduce new dependencies without asking.

## When stuck or ambiguous
Ask the user before:
- Introducing a new dependency
- Creating files outside the folder layout above
- Changing locked decisions (stages, states, stack)
- Implementing anything in the Out of Scope list

For everything else, proceed.

## Walkthrough narrative (keep this in mind while building)
The user will demo this in 5 minutes. The story:
1. Three deliberate ambiguities in the brief and how each was handled
2. Why these 6 stages map to real medical appointment ops
3. The orchestrator: pluggable scoring because priorities are explicitly dynamic
4. An agent: shows Escalate with structured reason
5. The Exception Queue: where the most time was spent because human-in-the-loop is where these systems live or die
6. What was not built and why

Code that supports this story is in scope. Code that doesn't, isn't.
