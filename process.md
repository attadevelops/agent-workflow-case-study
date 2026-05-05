# Build process and GenAI collaboration

This case study was built collaboratively with Claude Code (Anthropic's agentic CLI). The architectural decisions were mine; Claude Code executed and surfaced edge cases for review. Per the brief's note about GenAI usage, this document covers the release plan and the prompts that drove the most consequential decisions.

## Release plan

The 14-step build sequence followed in this order. Each step landed as a coherent vertical slice and was either greenlit or revised before the next began.

- Step 1: Domain analysis. Resolved three deliberate ambiguities in the brief; produced open questions for human review before locking decisions.
- Step 2: State models. Pydantic v2 domain (StrEnum, AppointmentState, EscalationReason, ConciergeResolution, StageRuntime) with a hand-mirrored TypeScript file as the wire contract.
- Step 3: Mock data. 25 hand-tuned appointments across three clients and four specialties with varied SLA bands, two pre-escalations and one prior resolution to seed demo state.
- Step 4: One agent end-to-end (Eligibility Verification). Established the agent contract: stage owns Complete/Escalate verdict, orchestrator owns the cursor.
- Step 5: All six agents. Five mechanical near-clones plus the Pre-Visit Questionnaire LLM seam (mock-default, real-Anthropic-when-MOCK_LLM=0).
- Step 6: LangGraph orchestrator. Two-nodes-per-stage pattern (prep + agent) for Processing checkpoint visibility; exception node with `interrupt()` and `Command(resume=...)`.
- Step 6.5: REVISION. Dual-mode resolution introduced (decisional + informational), retrofit across the orchestrator's exception node, the resolution payload, and the AppointmentState's last_resolution slot.
- Step 7: FastAPI surface + priority strategies + tick loop. Pluggable WeightedSum and LLMRule strategies with hot-swap; hybrid tick (auto every 4s + manual override).
- Step 8: Folded into step 7 during execution.
- Step 9: Frontend scaffold. Vite + React + Tailwind, single-hook polling at 2s, top-nav shell with placeholder views.
- Step 10: Dashboard pipeline visualization. Six-pill row per appointment with color semantics; client-side filter and sort; per-stage workload chips.
- Step 11: Exception Queue. The named UI/UX evaluation criterion. Structured payload rendering, mode toggle pre-selected from catalog hint, JSON payload textarea, dual-mode submit.
- Step 12: Resume-after-resolution validation. Playwright-driven UI lifecycle test surfaced a checkpoint-priming bug for seed-time pre-escalations; fixed via `_start_router` enhancement and async `store.seed()`.
- Step 13: README compile. Single-page entry document pulling from decisions.md and embedding the three demo screenshots.
- Step 14: Demo dry-run. Final visual sanity, no breaks found.

## Significant prompts

Below are six prompts from the build that drove the most consequential architectural outcomes. Each is annotated with what it was steering toward and what came of it. The full prompt history is much longer; this is a curated set showing the decision points that shaped the architecture.

### PROMPT 1 — Build framework and teaching cadence (project kickoff)

Substantive part (paraphrased; opening kickoff exchange):

> We're starting a new project together. I want to build this collaboratively as a learning exercise, not just code generation. Two parallel goals: (1) ship a working demo, (2) build deep understanding so I can defend every decision in a live interview. I want you to: explain before building each chunk; debrief after; push back on weak architectural decisions; maintain a decision log (decisions.md) with Context / Options / Chosen / Rationale / Interview defense format; pace yourself in vertical slices with stop-and-ask at choice points. If I'm asking for something speculative or premature, say so before answering. The 14-step build sequence is: domain → state → mock data → one agent → five agents → LangGraph orchestrator → strategies and tick → FastAPI → frontend scaffold → Dashboard → Exception Queue → resume wiring → README → polish.

What came of it: every architectural choice was interrogated when made, not retrofitted later. The decision log accumulated 16 entries over the build; education.md (internal-only, not in this repo) maintained per-step study notes for interview prep. The "explain before build, debrief after" cadence caught at least three premature commitments that would have rotted into rework.

### PROMPT 2 — The strategy pattern decision (after step 1 open questions)

Substantive part (verbatim, response to my five open questions):

> Answers to your five open questions, plus updates from further analysis. Log all of these in decisions.md. (1) Hybrid tick: auto every 4s plus manual override. (2) LLM stub for Pre-Visit Questionnaire only, with a real seam gated behind MOCK_LLM. (3) Row of six pills per appointment with compact color semantics. (4) Compact escalation badges in the queue. (5) Force-escalate via tuning override. Three additional points from analysis: priority is pluggable via a Strategy pattern, not a single weighted function — the brief's "or other unknown factors" phrase signals extensibility, not opacity. Dashboard supports filtering by status and stage. Acknowledge in README that long-running stages aren't modeled.

What came of it: WeightedSumStrategy + LLMRuleStrategy with hot-swap via `POST /admin/strategy`. Same wire shape, two interpretations of the priority lens. This became the strongest single architectural answer to the prioritization question — and the live demo's most dramatic moment (toggle the dropdown, watch the sort flip from numeric scoring to natural-language reasoning).

### PROMPT 3 — The dual-mode resolution pushback (step 6.5 revision)

Substantive part (verbatim, the revision that introduced dual-mode):

> Confirming all three of your points, with revisions on the classification. The field on AppointmentState should be named last_resolution (not active_resolution) — it's the most recent INFORMATIONAL resolution, consumed by the agent on re-run, then cleared. ConciergeResolution gets two new fields: resolution_type (decisional | informational, defaults to decisional to preserve the original semantic) and payload (dict, only populated for informational). Per-agent catalog gets a default_resolution_mode hint that the form pre-selects from. Revised classification: most member-data issues are informational (need corrected member ID), most clinical-judgment issues are decisional (human assesses and clears).

What came of it: This was the single most important architectural revision in the project. It happened mid-build after the original "Cleared = stage N+1" decision was already committed in decisions.md. The system was extended with `default_resolution_mode` on each `EscalationCandidate`, `resolution_type` and `payload` on `ConciergeResolution`, `last_resolution` on `AppointmentState`, and branching exception-node logic. The architecture now supports both judgment supersession and data supply as resolution patterns; the catalog declares the default; the human can override. The decision log has bidirectional cross-references between the original single-mode entry and the dual-mode revision.

### PROMPT 4 — Refusing to fabricate alignment (step 6.5 confirmation cycle)

Substantive part (the user's reaction after I surfaced the contradiction):

> Your "five extra minutes of confirmation beats reverse-engineering a feature" instinct here was exactly right. Don't lose that habit.

Context: I was asked to apply the dual-mode resolution work and "verify or report." Rather than fabricate alignment with the existing single-mode decision, I went back to the transcript, confirmed the dual-mode change had not actually been specified in prior turns, and refused to silently reverse a prior commitment without explicit confirmation. The user then explicitly approved the new direction, and the revision was made deliberate rather than implicit.

What came of it: the decision log preserves the evolution from single-mode to dual-mode with bidirectional cross-references between the entries. The architecture revision was a first-class decision, not a quiet drift. This pattern — "refuse to silently reverse prior commitments; surface the contradiction; ask" — became a load-bearing collaboration norm for the rest of the build.

### PROMPT 5 — The LLM seam at Pre-Visit Questionnaire (step 5 greenlight)

Substantive part (verbatim, greenlight for step 5 with constraints):

> Greenlight to proceed. Per-agent catalog is the right call. For Pre-Visit Questionnaire specifically: the LLM does extraction (free-text patient symptom input → structured intake fields), the agent does the policy decision (does this need clinical review?). Mock branch returns the same QuestionnaireExtraction shape the real Anthropic call would, gated behind MOCK_LLM defaulting to true. Real branch uses AsyncAnthropic with prompt caching on the system prompt. The seam is the architecture; the mock is canned for demo determinism.

What came of it: stage 5 became the architecture's "LLM where it earns its cost" demonstration. Free-text input → structured output is the canonical case for an LLM in a production pipeline. The MOCK_LLM seam pattern was reused at step 7 for the LLMRuleStrategy, which gave the project a second "real LLM call possible, mock by default" example without doubling the demo's risk surface.

### PROMPT 6 — Final scope tightening (step 11 essentials-only directive)

Substantive part (verbatim, the pre-step-11 directive):

> STEP 11 — Exception Queue. This is the named UI/UX evaluation criterion. Build the essentials, ship it. MUST HAVE: per-card structured payload rendering; resolution form with mode toggle pre-selected from default_resolution_mode; submit calls POST /exceptions/{id}/resolve with resolution_type, note, payload; after submit the card disappears (optimistic removal is fine, or just wait for next poll); stage history strip per card. SKIP for now: sort/filter (the demo can scroll), attempt counter badge, animation on card removal, keyboard navigation, narrow-viewport polish. Step 11 is where the bulk of UI craft goes; plan for step 10 to be tighter (mostly mechanical) and step 11 to be where you spend extra cycles.

What came of it: the named UI/UX evaluation criterion shipped with the architectural through-line intact and on time. The form's mode toggle, JSON payload textarea, and adaptive submit-button-color (emerald for decisional, sky for informational) made the dual-mode architecture visible in the first second of the screen. The pre-escalation checkpoint-priming bug (discovered during step 12 visual lifecycle testing, fixed before ship) was the kind of issue that would have been catastrophic at demo time; finding it via a real UI lifecycle test rather than wire-level smoke was a function of building the form to actually work, not just compile.

## A note on the collaboration model

Working with Claude Code on this project surfaced two patterns worth naming. First, the system pushed back when prior decisions and new instructions contradicted, preventing a silent architectural reversal that would have left the codebase incoherent with the decision log. Second, every architectural commitment was tested by being articulated; if I couldn't explain why I was making a choice, that was the signal to think more carefully before locking it in. The 16 entries in decisions.md, including bidirectional cross-references on the dual-mode revision, are the audit trail of that process.
