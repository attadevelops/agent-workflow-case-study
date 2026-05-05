# Decision Log

Append-only. Newest at the bottom. Each entry is a real choice point. The brief's ambiguities and our resolutions are the most defensible material in the README.

---

## 2026-05-05 10:00 — Cleared is a stage-level state, not appointment-level
Context: Brief lists 4 stage states (NotStarted, Processing, Complete, Escalate) and adds "the system should immediately update the appointment status to Cleared" after concierge resolution. Ambiguous: appointment-level field or stage-level state?
Options considered:
- A: Appointment-level Cleared flag, stage_states stays at 4 values.
- B: Cleared as a fifth stage state.
Chosen: B.
Rationale: A stage was the thing that escalated, so the resolution is a stage-level fact. B preserves "which stage was resolved" and "from where do we resume." A loses both.
Interview defense: "Brief uses 'appointment status' as user-facing language. Internally, appointment status is derived from stage states. Stage-level Cleared makes the LangGraph resume logic trivial: treat Cleared identically to Complete for advancement."

---

## 2026-05-05 10:00 — Workflow resumes at stage N+1, not stage N
**[REVISED on 2026-05-05 12:30 — see the "dual-mode resolution" entry below. This decision stands as the *decisional* path; the revision generalizes it by adding an *informational* path as a second mode. When `resolution_type` is omitted from the resume payload, behavior defaults to decisional and matches this entry exactly.]**
Context: Brief says "resume workflow if necessary." Silent on whether the cleared stage re-runs.
Options considered:
- A: Re-run the escalated stage after resolution.
- B: Skip ahead to N+1; Cleared = terminal-success for advancement.
Chosen: B.
Rationale: Re-running stage N would just escalate again — the agent's view of state hasn't changed. Cleared is the human's stamp that stage N is effectively done. The whole point of human resolution is to assert that the blocker is handled.
Interview defense: "If a human says 'I fixed it,' the orchestrator must trust that. Re-running the agent would create a re-escalation loop. We trade some safety (no automatic re-validation) for liveness."

---

## 2026-05-05 10:00 — Orchestrator concurrency: serial, one appointment per tick
Context: Brief silent. Out-of-scope explicitly excludes multi-user concurrency.
Options considered:
- A: Parallel processing via worker pool.
- B: Serial — one appointment advances by one stage per tick.
Chosen: B.
Rationale: Demo readability. Architectural value is the orchestration pattern, not throughput. Parallel is a one-line change once the contract is right (top-N instead of top-1) because the agent contract is already pure-function over state.
Interview defense: "The agent signature is async and pure over state, so parallel-safe. We chose serial for the facade because demo legibility beats throughput at this scope."

---

## 2026-05-05 10:00 — SLA modeled even though brief is silent
Context: Brief mentions no SLA. Frontend brief mentions "SLA countdown."
Options considered:
- A: No SLA on the model. Priority is by client/specialty weight only.
- B: `sla_due_at` field on every appointment, used for priority scoring + Exception Queue sort.
Chosen: B.
Rationale: Healthcare ops are SLA-driven (insurance verification within X hrs). Modeling SLA gives the priority function meaningful inputs and the concierge UX a sort dimension that means something.
Interview defense: "The brief said 'dynamic priorities (may vary by ... other unknown factors).' SLA urgency is the highest-value example of an 'unknown factor' the brief invites us to invent. The frontend brief explicitly named SLA countdown, so it's in scope."

---

## 2026-05-05 10:00 — Tick mode is hybrid: auto every 4s plus manual override
Context: Open question. Auto, manual, or both?
Options considered:
- A: Auto-only, fixed interval.
- B: Manual-only via `/admin/tick`.
- C: Hybrid: background task ticks every 4s, manual endpoint also exposed.
Chosen: C.
Rationale: Auto makes the dashboard feel alive (priorities visibly recompute). Manual gives the demoer a panic button if a tick comes mid-explanation.
Interview defense: "Dynamic priorities only matter if you can see them changing. The 4s tick proves the rescore is running. Manual override is ops realism — every production scheduler has a `run_now` admin hook."

---

## 2026-05-05 10:00 — One agent uses an LLM, gated behind MOCK_LLM flag
Context: Brief allows one optional agent to demonstrate LLM capability.
Options considered:
- A: Skip it. All deterministic.
- B: Stub it (canned response, no real call).
- C: Real call, gated by `MOCK_LLM` flag. Demo runs with flag on.
Chosen: C, at Stage 5 (Pre-Visit Questionnaire).
Rationale: B reads as smoke when an evaluator scrolls the file. C is provably real code; the seam is genuine. Demo runs the mock path for reproducibility; running the real path is one env var away.
Interview defense: "The whole role is agentic AI development. We picked the stage where free-text patient input makes the LLM's job clear (summarize, extract risk flags, decide Complete vs Escalate). Mocked for demo determinism, but the prompt template, message construction, and response parser are production-shape."

---

## 2026-05-05 10:00 — Priority strategy is pluggable via a Strategy pattern
Context: Brief says "intelligently decide... based on dynamic priorities (may vary by client, specialty, or other unknown factors)." Open: deterministic scoring or LLM-driven ranking?
Options considered:
- A: Single weighted-sum scoring function. Simple, deterministic, auditable.
- B: LLM ranks the appointment list given natural-language rules. Flexible but opaque.
- C: Strategy pattern with both implementations behind one interface. Default to weighted-sum at runtime.
Chosen: C.
Rationale: C is the strongest demo answer to the obvious interviewer challenge "shouldn't priority be LLM-driven?" — we considered it and built the seam. Two implementations make pluggability provable rather than asserted.
Interview defense: "The 'dynamic priorities' clause is ambiguous on purpose; the brief invites design. We chose a strategy abstraction so the priority logic is swappable without touching the orchestrator. WeightedSum runs by default for auditability and reproducibility. LLMRule is a real call gated by MOCK_LLM, demonstrating the swap-cost is a constructor argument."

---

## 2026-05-05 10:00 — Strategy interface returns ordered list of AppointmentStates with score+reasoning fields populated
Context: Strategy interface shape. Choice between (a) returning a wrapper type, (b) mutating fields on AppointmentState directly.
Options considered:
- A: `rank() -> list[RankedAppointment]` wrapper carries score/reasoning separately.
- B: `priority_score` and `priority_reasoning` on AppointmentState. Strategy populates them as it returns.
- C: Strategy returns `(appointment_id, score, reasoning)` tuples.
Chosen: B.
Rationale: One type on the wire keeps frontend types.ts simple. WeightedSum populates score; LLMRule populates reasoning; dashboard renders whichever is present. Strategy is "less pure" but the cost is invisible in practice.
Interview defense: "We surfaced priority transparency as a first-class concern. Both fields are nullable and either is enough for the dashboard 'why was this prioritized?' view. Adding a wrapper type would have doubled the serialization surface for marginal purity gain."

---

## 2026-05-05 10:00 — Dashboard filters: state-based, but "Cleared" renamed to "Resolved"
Context: Dashboard filter set proposed: All / In Progress / Cleared / Escalated / Completed.
Options considered:
- A: Keep "Cleared" filter. Defines as "currently in Cleared state on at least one stage" (will almost always be empty due to transient nature).
- B: Drop "Cleared" filter; use a row badge "Has resolutions" instead.
- C: Rename to "Resolved" meaning "appointments that have had at least one escalation cleared in their history." (Lifetime fact.)
Chosen: C.
Rationale: A is broken (the state is too transient to filter on). B works but loses a primary filter dimension. C is what the user actually means by "show me appointments that hit a snag and recovered."
Interview defense: "The filter must align with the model. Cleared is stage-level and transient. Resolved is the lifetime fact a concierge actually wants to filter on: 'show me the workflow's recovered appointments.'"

---

## 2026-05-05 10:30 — Added `procedure` field to AppointmentState
Context: Step 3 mock data realism. Specialty alone is too coarse for clinical realism — every appointment is for a specific procedure (stress test, knee MRI, mole screening). Brief is silent on appointment fields.
Options considered:
- A: Pack procedure into patient_name string. Unparseable, ugly.
- B: Add `procedure: str` as a top-level field, display-only on the dashboard.
- C: Skip; specialty is enough for the orchestrator.
Chosen: B. Required string field, placed after `specialty`.
Rationale: Procedure is the field that makes demo data feel real instead of generic. Cardiology + stress test reads as a real appointment; bare "cardiology" reads as a test fixture. Cost is one field on each side of the wire.
Interview defense: "Specialty is the orchestrator's input (drives priority); procedure is the dashboard's output (drives display). Separating them keeps the agentic logic clean — agents care about specialty, the UI cares about procedure. Adding it now also cost a one-line edit on each side; deferring would have meant a model migration later."

---

## 2026-05-05 13:00 — Strategy interface symmetry: both populate priority_score + priority_reasoning
Context: WeightedSum produces numeric scores; LLMRule produces ranked list with text. Tempting to give them different output shapes.
Options considered:
- A: WeightedSum returns `(state, score)` tuples; LLMRule returns `(state, reasoning)`. Tick loop handles both shapes.
- B: Both mutate `priority_score: float` AND `priority_reasoning: str | None` on each appointment. Tick loop sees one shape regardless.
Chosen: B.
Rationale: Asymmetry leaks into the tick loop and forces case-handling that's purely strategy-bookkeeping. With B, the dashboard renders a single field for both ("why was this prioritized?") and shows whichever was populated. WeightedSum populates score (and a transparent breakdown in reasoning); LLMRule populates reasoning (with the score the LLM returned). Same wire shape.
Interview defense: "The interface is the architectural commitment, not the implementation. Forcing both strategies into the same output shape is what makes them swappable in one POST without touching the consumer."

---

## 2026-05-05 13:00 — Tick loop hybrid: 4s auto + manual /admin/tick, sharing one lock
Context: The brief's "intelligent orchestrator" needs to demonstrably re-rank and pick on a cadence. Static state doesn't make the demo feel alive.
Options considered:
- A: Auto-tick only. Demoer can't pause to explain.
- B: Manual-tick only. Static UI makes "dynamic priorities" hard to show.
- C: Hybrid: background `asyncio.create_task` ticks every TICK_INTERVAL_S (default 4); manual `POST /admin/tick` available for ops control. Both share the store's `_lock` so they never overlap on the same appointment.
Chosen: C. Tick interval is env-configurable (`IKS_TICK_INTERVAL_S`); demoer can crank it to 60+ if they want to manually drive.
Rationale: Auto proves dynamic priorities (rescore visible per tick); manual is the panic button. The lock guarantees no double-pick. Empty-pool tick is a no-op, not an error — the loop just sleeps until something becomes pickable.
Interview defense: "Auto-tick is the proof; manual-tick is the safety net. Both share the same `tick()` entry point. The lock means concurrent calls serialize cleanly — production would replace this with a Postgres advisory lock or a Redis-based queue, but the contract stays."

---

## 2026-05-05 13:00 — LLMRuleStrategy: MOCK_LLM seam, same shape parity as Pre-Visit Questionnaire
Context: The brief says "intelligent orchestrator." The strongest answer to "shouldn't priority be LLM-driven?" is to *show the seam, working*.
Options considered:
- A: Skip. WeightedSum is enough.
- B: Stub a function that returns hardcoded scores.
- C: Real `AsyncAnthropic` call with prompt caching, full system+user message, JSON-parsed `_LLMRanking` schema, defensive parse fallback. Gated by `MOCK_LLM` env var defaulting true. Mock branch returns the same `_LLMRanking` shape.
Chosen: C. Default rules string is inline with a comment that production would load from config; rules are natural-language ("Premium clients get priority over Standard...") so an interviewer can see the LLM-as-policy concept concretely.
Rationale: B reads as smoke. C is provably real code that the demo doesn't run for cost/latency reasons but that *would* run with one env-var flip. The mock and real branches return identical shape — surrounding code (the rank() method) cannot tell them apart.
Production architecture note acknowledged in code: a real LLM call against 25 appointments takes 1-3s; the tick runs every 4s. The demo runs synchronously (mock = zero latency). Production would decouple scoring cadence from tick cadence — score every 30s, cache the results, the tick reads cached scores. The seam is documented; not exercised.
Interview defense: "We considered LLM-as-orchestrator as the strongest possible interpretation of 'intelligent.' We built the seam, made it provably correct (same shape, same interface, gated env var), and chose deterministic-by-default for demo reproducibility. Same architectural commitment as the Pre-Visit Questionnaire."

---

## 2026-05-05 13:00 — Mock data escalation codes aligned with the renamed catalogs
Context: After the dual-mode revision renamed several codes (`missing_insurance_id` → `member_id_mismatch`, `expired_coverage` → `coverage_inactive`, `auth_denied_pending_review` → `auth_pending_clinical_info`), the pre-seeded escalations in mock_data still used the old names.
Options considered:
- A: Leave the old codes in mock_data. The codes are free-form strings; the model accepts anything.
- B: Rename to align with the catalog. Demo coherence — an evaluator scrolling /exceptions then opening the agent catalog should see consistent code namespacing.
Chosen: B.
Rationale: An evaluator who finds APT-06's `missing_insurance_id` in the API and then can't find that code in the agent catalog has the wrong impression about the system's coherence. Renaming is a 3-line edit. Ignoring it is a quiet bug.
Interview defense: "The pre-seeded escalations in mock_data are demo fixtures, not catalog products. We aligned the codes anyway because demo coherence matters: an evaluator should never see a code at runtime that doesn't appear in the source-of-truth catalog."

---

## 2026-05-05 12:30 — REVISION: dual-mode resolution (decisional + informational)
Context: The earlier decision (2026-05-05 10:00, "Workflow resumes at stage N+1, not stage N") committed to single-mode resume on the principle of trusting the human's resolution. Closer domain analysis surfaced that real concierge resolutions split into two patterns:
  • DECISIONAL: human judgment supersedes the agent's escalation. The stage is treated as resolved by virtue of the human's call. Workflow advances to stage N+1.
    Examples: ineligible_procedure_for_plan (rebooking decision), clinical_flag_detected (clinician sign-off), missing_pcp_signature (rebook with valid referral).
  • INFORMATIONAL: human supplies missing data the agent didn't have. Stage N re-evaluates with the new input. Workflow stays at stage N until the agent makes its own call.
    Examples: member_id_mismatch (corrected ID supplied), incomplete_responses (patient's missing answers supplied), referral_not_on_file (located document supplied).

The original single-mode framing isn't wrong — it's a special case (decisional always). The dual-mode framing is a strict generalization: if `resolution_type` is omitted from the resume payload, we default to `decisional` and behavior is identical to the prior decision.

Implementation:
- `EscalationCandidate.default_resolution_mode: Literal["decisional", "informational"]` — the catalog declares the suggested default; the concierge UI offers both at resolution time.
- `ConciergeResolution.resolution_type: ResolutionMode = "decisional"` and `payload: dict | None = None` — captures what was chosen and any data supplied.
- `AppointmentState.last_resolution: ConciergeResolution | None = None` — working slot for the most-recent informational resolution. Set by the exception node on informational resume; consumed by the agent on re-run; cleared by the agent-node wrapper after consumption.
- The exception node branches on `resolution_type`: decisional sets stage=Cleared and advances cursor; informational sets stage=NotStarted, leaves cursor at N, and populates last_resolution.
- The agent-node wrapper bumps `stage_runtimes[stage].attempt` (informational re-runs visibly attempt=2) and clears `last_resolution` after the agent runs.

Verified: `smoke_step6_informational.py` exercises the informational path end-to-end. `smoke_step6.py` continues to exercise decisional. `smoke_step5.py` continues to pass with the renamed catalog codes.

Interview defense: "We initially committed to single-mode resume on the principle of trusting the human. Closer domain analysis showed real workflows have two distinct patterns — judgment supersession and information supply. Each demands different orchestrator behavior. We surfaced the tension explicitly rather than silently reversing the prior decision; the README narrative is 'we evolved from single-mode to dual-mode based on closer domain analysis,' which is honest and stronger than pretending the architecture was always dual-mode."

Domain insight surfaced: failure-mode classification is a property of the most-likely resolution path, not of the failure code itself. Some codes have a clear canonical mode; others have multiple plausible paths and need a default + concierge override. Early-pipeline stages skew informational (missing-data failures); late-pipeline stages skew decisional (judgment-call failures). The Pre-Visit Questionnaire is mixed because it has both kinds.

---

## 2026-05-05 12:00 — Two LangGraph nodes per stage (prep + agent) for Processing visibility
Context: Brief requires Processing to be visible to consumers polling between agent invocations. The agent's single-return contract makes it impossible to flip Processing mid-execution from inside the agent.
Options considered:
- A: Single node per stage; Processing is invisible (consumers only see Old → Complete/Escalate).
- B: Single node + LangGraph state-write hook to emit intermediate state mid-execution.
- C: Two nodes per stage: `prep_<stage>` flips Processing and writes a checkpoint; `agent_<stage>` does the work. Polling between them sees Processing.
Chosen: C.
Rationale: A breaks the demo (the brief explicitly lists Processing as a state). B is more LangGraph-idiomatic but couples orchestration to streaming primitives that are harder to extend later (telemetry, retries, audit logging all live more naturally in a wrapper node). C is the legible, extensible choice — and a wrapper node is exactly where production systems end up regardless.
Interview defense: "LangGraph nodes are checkpoint boundaries. Visibility = node count. Two-nodes-per-stage costs a few extra lines of wiring and gives consumers a clean Processing checkpoint they can poll. The wrapper is also the natural extension point for retries, telemetry, or audit logging — exactly where you'd add them in production."

---

## 2026-05-05 12:00 — Cursor advancement lives in the orchestrator wrapper, not the agent
Context: After an agent returns Complete, `current_stage` should advance to the next stage (or None if at end). Where does this happen?
Options considered:
- A: Each agent's wrapping logic advances current_stage. Couples agent logic with orchestrator semantics.
- B: A separate "finalize" node after each stage's agent. Adds 6 more nodes to the graph.
- C: The agent-node closure post-processes the agent's return: on Complete, advance current_stage; on Escalate, leave it (the exception node uses it).
Chosen: C.
Rationale: Agent owns the *decision*. Orchestrator owns the *cursor*. Putting cursor advancement in the agent-node closure (a 4-line addition) keeps that separation clean without inflating the graph topology.
Interview defense: "The agent answers 'what happened?' (Complete or Escalate, with reasons). The orchestrator answers 'what's next?' (advance the cursor, route to the next node, persist). Mixing them is the classic mistake that makes orchestrators hard to test."

---

## 2026-05-05 12:00 — Active escalation cleared on resolve; resolutions list is the audit trail
Context: After concierge resolution, `escalation_reason` is the now-resolved escalation. Keep it, archive it, or clear it?
Options considered:
- A: Keep `escalation_reason` set as "last active." Validator forbids this (escalation_reason set requires a stage in Escalate; after resolution the stage is Cleared).
- B: Add an `archived_escalations: list[EscalationReason]` field; append on resolve, then clear active.
- C: Clear `escalation_reason` to None on resolve. The `resolutions` list (with `resolved_stage` + `resolved_code`) is the audit trail.
Chosen: C.
Rationale: A breaks coherence. B is more thorough but adds a field used by exactly one read path (Exception Queue history view). C captures the resolution event with enough detail (stage, code, note, resolved_at, resolver_id) for the demo. The full agent_context dict is lost on clear; we accept this for facade simplicity.
Interview defense: "If asked 'where's the agent_context after resolution?' — in v2 we'd archive the full EscalationReason. For the facade, the ConciergeResolution captures the stage and the code, which is enough for the audit trail story. The model validator enforces coherence at the boundary."

---

## 2026-05-05 12:00 — thread_id = appointment_id; one graph thread per appointment
Context: LangGraph thread_id is the unit of independent pause/resume. What's the right granularity?
Options considered:
- A: One global thread for the whole orchestrator. Doesn't survive interrupts cleanly because Command(resume=...) targets one thread.
- B: thread_id = appointment_id. Each appointment is independently pause-able.
Chosen: B.
Rationale: B is the only option that handles concurrent escalations (different appointments paused at different stages) cleanly. Aligns with the natural domain partition. A doesn't work in any non-trivial scenario.
Interview defense: "Each appointment has its own state machine, its own pause point, and its own resume target. Threads are the LangGraph primitive that maps to that domain partition. Appointment ID is the canonical identifier; reusing it as thread_id keeps the mapping invisible — which is what good API surfaces feel like."

---

## 2026-05-05 12:00 — LangGraph msgpack deprecation warning is cosmetic; address before step 8
Context: Compiling the graph emits warnings about unregistered enum types being deserialized from checkpoints. LangGraph plans to block this in a future version.
Options considered:
- A: Register types via `LANGGRAPH_ALLOWED_MSGPACK_MODULES` or a programmatic call. Suppresses warnings.
- B: Ignore for now. Output is functional; warnings are stderr noise.
Chosen: B for step 6; revisit before step 8 (FastAPI surface, where stderr from the dev server is more visible).
Rationale: The warnings don't affect correctness. Solving them now is a yak-shave; solving them at step 8 when we configure the FastAPI app and could add the registration in `main.py` startup is more efficient.
Interview defense: "We noted the deprecation, kept moving, and queued the fix at the natural integration point. Yak-shaving in the middle of an architectural step is exactly how facades get derailed."

---

## 2026-05-05 11:30 — Pre-Visit Questionnaire: LLM does extraction; agent does decision
Context: Stage 5 is the one agent that uses an LLM. Where exactly does the LLM sit in the decision pipeline?
Options considered:
- A: LLM decides Complete/Escalate directly. Pass the questionnaire text, ask the model "should this proceed?"
- B: LLM extracts structured data (`extracted_fields`, `clinical_flags`, `completeness_score`); a deterministic policy `_decide()` maps the extraction to Complete/Escalate. The agent owns the policy.
Chosen: B.
Rationale: LLMs are excellent sensors for free-text-to-structure extraction; they are unreliable as ultimate decision-makers when the decision affects ops state. Separation of concerns: the LLM is the noisy sensor, the agent is the deterministic policy. Either side can be swapped without touching the other.
Interview defense: "If we replace Claude with a different model, the policy doesn't change. If the policy changes (new threshold, new flag list), the LLM doesn't need touching. That decoupling is the whole point — and it's exactly the architectural property I'd expect to be probed on for an agentic AI role."

---

## 2026-05-05 11:30 — MOCK_LLM env var defaults true; real branch uses AsyncAnthropic with prompt caching
Context: We need a real LLM call for credibility but cannot run it during demo (cost, latency, unreliability).
Options considered:
- A: Stub function that returns canned text. Reads as smoke when scrolled.
- B: Real `AsyncAnthropic` call structurally complete (system + user message, prompt caching, schema validation), gated behind `MOCK_LLM` env var which defaults true. Mock path returns the same `QuestionnaireExtraction` shape so callers cannot distinguish.
Chosen: B. `MOCK_LLM=false` flips to the real call (requires `pip install -e .[llm]` and `ANTHROPIC_API_KEY`).
Rationale: The seam is provably correct only if the surrounding code cannot tell the difference between mock and real. Cache control on the system prompt is a one-line addition that demonstrates production-awareness — repeated questionnaire calls amortize the system-prompt tokens.
Interview defense: "The mock and real branches are interchangeable from any consumer's perspective. Prompt caching on the system prompt is the production-shape detail that says 'we considered cost at scale, not just correctness on one call.'"

---

## 2026-05-05 11:30 — Mechanical agents kept as near-clones; no abstraction
Context: Five of the six agents have nearly identical wrapping logic (started_at, simulate_work, finished_at, runtime, candidate roll, model_copy). Tempting to extract a `_run_simulated_agent` helper.
Options considered:
- A: Extract the wrapping into a shared helper; each agent file becomes ~10 lines (STAGE + CATALOG + thin wrapper).
- B: Keep each agent as a standalone function with the wrapping inlined. Repetition is the cost.
Chosen: B.
Rationale: LangGraph nodes are typed function references; keeping each agent as its own callable preserves that mental model. The repetition is also the kind of "boring-by-design" code an evaluator can scan one file and skim the rest of. Abstraction was tempting but premature — per CLAUDE.md "abstract only on second use" — and Victor explicitly flagged "resist the temptation to improve the pattern as you replicate."
Interview defense: "We chose readable repetition over premature abstraction. If a 7th agent ever appears, *that's* the moment to extract — when the abstraction has three real consumers, not five guesses."

---

## 2026-05-05 11:00 — Agent contract: agent owns the Complete/Escalate decision; orchestrator owns Processing visibility
Context: Brief says agents "set stage_state to Processing on entry." But agent signature is single-return (`AppointmentState in -> AppointmentState out`). Where does Processing get set?
Options considered:
- A: Each agent flips Processing internally (requires async generators or partial-state writes; fights the single-return contract).
- B: Orchestrator wraps the agent call: flips Processing before invocation, calls agent, records the agent's terminal Complete/Escalate after.
- C: Drop Processing visibility entirely; consumers see Old → Complete/Escalate only.
Chosen: B. Agent records its own `started_at`/`finished_at` on `stage_runtimes[STAGE]`; the orchestrator is the only thing that knows work is starting before it starts, so it owns the Processing flip.
Rationale: Six agents would mean six places to edit if visibility semantics change. Centralizing Processing in the orchestrator wrapper is one place.
Interview defense: "The agent's contract is the *decision*. The orchestrator's contract is the *coordination*. Processing is a coordination concern (someone needs to write it before the work starts), so it belongs to the wrapper, not the worker."

---

## 2026-05-05 11:00 — RNG is injected per-call, not module-global or env-var-driven
Context: Backend/CLAUDE.md mentions `IKS_SEED` env var for reproducibility. Where does the seed actually live?
Options considered:
- A: Module-global `random.Random()` seeded at import.
- B: Env-var-derived RNG inside each agent.
- C: Inject `rng: Random | None = None` as a kwarg on every agent. Default = fresh Random; tests pass a seeded one.
Chosen: C.
Rationale: A and B are global state, which makes per-call determinism impossible. C scopes randomness to one call, which is the only level at which deterministic tests work. The env-var seed becomes a one-line application concern (orchestrator reads `IKS_SEED` and constructs the Random it threads to agents), not a library concern.
Interview defense: "Tests can't be deterministic if randomness is global. Injection is the smallest discipline that keeps each agent independently testable. The env var is still respected, but only at the orchestration layer."

---

## 2026-05-05 11:00 — `AgentTuning` frozen dataclass: jitter range and escalation probability tunable from one place
Context: Demo intensity may need to change (e.g., force frequent escalations for stress test, or shorten jitter for demo-day pacing). Where do the knobs live?
Options considered:
- A: Magic numbers inline in each agent.
- B: Module-level constants in `_runtime.py`.
- C: Frozen `AgentTuning` dataclass with a `DEMO_TUNING` singleton; agents accept `tuning` kwarg defaulting to it.
Chosen: C. Smoke test demonstrates the seam: forced Complete via `AgentTuning(escalation_probability=0.0)`, forced Escalate via `escalation_probability=1.0`.
Rationale: Frozen dataclass means tuning is immutable per-call (you construct a new one to override). Single source of truth visible in one file. Agents stay free of env-var or config-file dependencies.
Interview defense: "Tuning lives behind a frozen interface so a swap is observable, not implicit. The smoke test exercises the seam directly: force Complete, force Escalate, observe both branches. Same mechanism a stress-test harness would use."

---

## 2026-05-05 11:00 — `stage_runtimes` is sparse on AppointmentState
Context: We need per-stage runtime metadata (started_at, finished_at, attempt). Eager full-dict default vs sparse?
Options considered:
- A: `dict[StageName, StageRuntime]` defaulted to all 6 entries with all fields None.
- B: Sparse dict; entries only appear for stages that have actually run. Default empty dict.
Chosen: B.
Rationale: Wire shape stays small (most appointments have 0-3 entries, not 6). Frontend treats absence as "stage hasn't run yet," which is more honest than a row of nulls. `stage_states` stays the canonical "what's the current state?" map; `stage_runtimes` stays the "when did this happen?" map.
Interview defense: "stage_states answers *what*; stage_runtimes answers *when*. Keeping them separate (and the latter sparse) means the wire shape grows only with actual progress, not with schema commitment."

---

## 2026-05-05 10:30 — Mock data: hand-tuned, not procedurally generated
Context: 25 appointments need to exist for the demo. Procedural (random.choices) is faster to write; designed is more realistic.
Options considered:
- A: Pure procedural with `random.Random(seed)`. Reproducible but generic.
- B: Pure hand-coded list. Maximum control, no nondeterminism.
- C: Hand-tuned distribution, each appointment chosen for a purpose.
Chosen: C. The 25 specs are static; a builder converts them to `AppointmentState` instances anchored to `now`.
Rationale: The dataset is a demo fixture, not a feature. Each appointment exists to exercise a specific corner of the system: priority scoring tension (on-fire vs stale), LLM rule discrimination (skewed client/specialty distributions), Exception Queue from tick zero (2 pre-escalated), recovery trail (1 with prior resolution), pipeline progress diversity (mix of NotStarted / mid-pipeline / deeper / Complete). The module docstring names the design intent for readers.
Interview defense: "We hand-tuned the dataset because random data dilutes the demo signal. Twenty-five appointments at six fields each is a hundred and fifty values; that's a thirty-minute hand-edit and the file's docstring becomes the demo cheat sheet."

---

## 2026-05-05 10:00 — `eligible_to_run_at` field on AppointmentState (modeled, not enforced)
Context: Real workflows have stages that should not run until close to the appointment time (questionnaire 24h before, etc.). Modeling without enforcing.
Options considered:
- A: Don't model. Acknowledge in README.
- B: Model the field on AppointmentState. Orchestrator skips appointments where `now() < eligible_to_run_at`. Demo data sets this to created_at.
- C: Model AND enforce.
Chosen: B.
Rationale: A loses defensibility (interviewer asks "what about scheduling constraints?" — we have nothing). C is overscope for facade. B threads the needle: the field exists, the constraint is documented, demo data ignores it.
Interview defense: "Production scheduling has temporal constraints. We surfaced the field on the model so the API contract is honest, but the demo doesn't exercise it. Adding enforcement is a one-line orchestrator change."

## 2026-05-05 14:00 — Pipeline pill color contract: `cleared` is visually distinct from `complete`
Context: A row of six pipeline pills tells the story of an appointment at a glance. `complete` and `cleared` are both terminal-success states, but they answer different questions ("did the agent finish cleanly?" vs. "did a human resolve an escalation?"). Making them visually identical would lose that distinction.
Options considered:
- A: Treat both as "green" — same color, same fill.
- B: `complete` = solid emerald; `cleared` = emerald outline (transparent fill, emerald border).
- C: Different hues entirely (e.g. blue for cleared).
Chosen: B.
Rationale: A loses information that the demo *should* surface (concierge intervention). C invents a new color for one state, breaking the consistent "stop-light" semantics. B uses fill-vs-outline as a within-color modulation — emerald means "good" in both cases, but the outline says "human in the loop." A reviewer scanning 25 rows can immediately spot which appointments needed human help.
Interview defense: "Pill color tells the agent's verdict; the cleared variant adds a second axis: was a human involved? Outline means yes. Reviewer can scan distribution at a glance."

## 2026-05-05 14:00 — Dashboard filter/sort is fully client-side
Context: The dashboard table has four filter facets (status, stages, clients, specialty) and four sort columns. Two implementations: server-side (URL params, refetch on change) or client-side (derive in `useMemo` from already-polled list).
Options considered:
- A: Server-side via query params on `/appointments`.
- B: Client-side, derive on each render via `useMemo`.
Chosen: B.
Rationale: 25 rows. Server-side adds backend code, URL state management, refetch latency on every chip toggle, and a stale-state risk (filtered list lags poll). Client-side is one `.filter().sort()` chain, runs in <1ms on 25 rows, and stays in sync with the polling stream automatically. The crossover where server-side becomes the right call is roughly 1k+ rows (when client memoization stops paying for itself or initial payload becomes a problem).
Interview defense: "At 25 rows, derive on the client. The pattern would migrate to server-side at ~1k rows; the API would gain `?status=&client=` params and the frontend would lose the useMemo. The migration is mechanical, not architectural."

## 2026-05-05 14:00 — StageBreakdown chips surface per-stage workload aggregate
Context: A reviewer looking at the dashboard wants to know "where is the work concentrated right now?" — not just "how many escalations total" but "how many are stuck at Prior Auth specifically?" The orchestrator's scheduler implicitly sees this distribution; the UI should make it visible.
Options considered:
- A: Don't show per-stage breakdown; rely on row-by-row pill scanning.
- B: Per-stage chips above the table: `S1 Eligibility 3↺ 1!`, `S2 Prior Auth 2↺ 4!`, ...
- C: A bar chart visualization.
Chosen: B.
Rationale: A is correct but slow to read for a reviewer with 30 seconds. C adds a chart library for marginal visual gain. B sits between text and chart — compact, scannable, no new deps. The `↺` glyph (in_progress) and `!` glyph (escalated) become a per-stage pulse summary.
Interview defense: "Aggregate counts per stage answer 'where is the bottleneck?' in one glance — useful for the human concierge deciding which exception to grab next, and useful for the reviewer understanding the system's load distribution."

## 2026-05-05 14:30 — `default_resolution_mode` lives on `EscalationReason` (catalog hint propagated to wire)
Context: The Exception Queue's resolution form has a mode toggle (decisional vs informational). The toggle should pre-select the mode the agent's catalog *suggests* for that escalation code (e.g., `member_id_mismatch` → informational; `clinical_flag_detected` → decisional). The hint already exists on `EscalationCandidate` in the catalog; it needs to travel onto the wire so the frontend can read it.
Options considered:
- A: Hardcode a code → mode lookup table on the frontend.
- B: Add `default_resolution_mode` field to `EscalationReason` (Pydantic model + serialized to JSON) and pass through in `build_escalation_reason`. Mirror the field on `types.ts`.
- C: Add a separate endpoint `/escalations/{code}/default-mode` and have the frontend look it up.
Chosen: B.
Rationale: A duplicates the source of truth and drifts. C adds an extra HTTP roundtrip for static metadata. B keeps the catalog as the single source of truth and rides one wire shape — the frontend already pays the cost of fetching the escalation; the hint is one extra string field. Pre-escalations from `mock_data.py` were updated to opt into `informational` for codes that obviously want it (member ID mismatch, missing clinical info); the default for unspecified pre-escalations remains `decisional`.
Interview defense: "The catalog already knows whether a code is decisional or informational — that's a property of the code, not the runtime. The wire carries the hint; the human can override before submitting. Hardcoding the lookup on the frontend would be a maintenance trap."

## 2026-05-05 14:30 — Resolution form is always-visible per card (not behind a Resolve button)
Context: Each Exception Card has a multi-field resolution form (mode toggle, note, optional payload JSON, submit). Decision: render it expanded by default vs. collapsed-with-toggle.
Options considered:
- A: Form behind a "Resolve" button that expands on click.
- B: Form always visible per card.
- C: Single-active card (only one form expanded at a time, others collapse).
Chosen: B.
Rationale: The Exception Queue is single-purpose. Every card here exists to be resolved. Hiding the form behind a click adds friction with zero gain — the concierge isn't browsing, they're working through the queue. Vertical density cost is real (~200px per card), but mitigated by the queue typically holding 5-10 items in a demo. C was tempting but the implementation cost (shared state, focus management) didn't pay back the visual calm.
Interview defense: "The Exception Queue isn't a list — it's a worklist. Every card is in front of you because something is waiting on you. Burying the resolution form behind a click would be UX theater for a concierge actually doing the job."

## 2026-05-05 14:30 — Informational payload is a JSON textarea, not a key-value editor
Context: For informational resolutions, the human supplies a payload that the agent reads on re-run (e.g., `{"member_id": "M-12345-CORRECTED"}`). UI options: free-form JSON textarea, or a structured key-value pair editor.
Options considered:
- A: Free-text JSON textarea with parse validation.
- B: Key-value pair editor (add row / remove row / type per field).
- C: Schema-driven form (different fields per escalation code).
Chosen: A.
Rationale: B requires UI state for a list of pairs and a type toggle (string vs number vs bool). C would be the right answer in a real product but requires a per-code schema registry and is well outside the facade scope. A is one `<textarea>` + `JSON.parse` + inline error display. Reads as "developer tool" rather than "concierge tool" — but for a demo audience that includes the technical evaluator, that's a feature: it makes the wire shape visible. The placeholder text shows a working example.
Interview defense: "In a real concierge tool, this is a schema-aware form per escalation code. For a facade, a JSON textarea is the most honest version of what's actually happening — the agent reads `last_resolution.payload` as a dict, and this textarea is that dict. A future iteration would map the EscalationReason.code to a per-code schema and render typed inputs."

## 2026-05-05 15:00 — Pre-escalation checkpoint priming (architectural bug fix found at step 12)
Context: Step 12 visual lifecycle test revealed `POST /exceptions/APT-06/resolve` returned 400. Root cause: APT-06 and APT-14 are seed-time pre-escalations — they have `escalation_reason` set on the AppointmentState but never went through the LangGraph orchestrator, so no checkpoint exists in the in-memory saver. The store's resolve path called `Command(resume=payload)` against a non-existent thread; LangGraph silently produced an empty state, which then failed `response_model=AppointmentState` validation with 9 missing-field errors.
Options considered:
- A: At resolve time, detect "no checkpoint" and apply the resolution logic (extracted from `_exception_node`) directly to the in-memory state. Skip the graph entirely for the no-checkpoint case.
- B: At seed time, "warm up" the graph for each pre-escalated appointment by calling `graph.ainvoke(state)`. Requires the start router to handle the already-escalated case (currently it routes to `prep_<stage>`, which would re-run the agent and overwrite the pre-escalation).
- C: Don't seed pre-escalations — generate all escalations through the agent path.
Chosen: B + a one-line fix to `_start_router`.
Rationale:
- A was tempting but creates a divergent code path (manual mutation vs. graph). Keeping a single resume mechanism is more maintainable.
- C kills the demo opening — APT-06 and APT-14 are the predictable initial-state escalations a demoer relies on. Removing them makes the queue empty until ticks roll escalations.
- B is a 6-line fix: `_start_router` checks for `escalation_reason is not None` and routes to `EXCEPTION_NODE`; `start_destinations` adds `EXCEPTION_NODE`; `store.seed()` becomes async and primes pre-escalated appointments via `graph.ainvoke(apt, config)`. The two FastAPI call sites (`/admin/seed`, lifespan) were updated to await.
Interview defense: "Pre-seeded escalations need a LangGraph checkpoint to be resolvable. The `_start_router` was the seam: it now treats 'arrived already-escalated' as a first-class state and routes straight to the exception node. Seed primes the graph by invoking once per pre-escalation; the router lands at the exception node, `interrupt()` pauses, checkpoint persists. Resume works as designed."
Discovery context: This was found by **playwright-driven UI lifecycle test** during step 12 verification. Wire-level smoke tests at step 6/7 only exercised agent-rolled escalations (which DO have checkpoints from their forward-graph run). The hole was specific to seed-time pre-escalations and would have surfaced live during the demo.
