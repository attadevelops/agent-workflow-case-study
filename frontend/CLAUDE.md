# Frontend: Vite + React + TypeScript + Tailwind + shadcn

See root CLAUDE.md for project-wide rules. This file covers frontend specifics.

## Priority of effort
The Exception Queue is the named UI/UX evaluation criterion. It gets the most design attention. The dashboard exists to give context; the Exception Queue is where craft shows.

## Two views
1. **Dashboard** — appointment list + pipeline visualization showing each appointment's progress through the 6 stages. Compact. Information-dense. Good for "watch the system run."
2. **Exception Queue** — escalated appointments with full context, resolution UI, history.

A simple top nav switches between them.

## Exception Queue UX requirements
The concierge needs to resolve fast. Every interaction should reduce time-to-resolution.

For each escalated item, show:
- Appointment summary (patient, specialty, client, SLA countdown)
- Which stage escalated and why (the structured EscalationReason payload, rendered with the code prominent and message in plain language)
- Suggested action from the agent, if present
- Agent context (collapsible JSON, for "show me what the agent saw")
- Stage history (which stages already completed)
- Resolution form: free-text note + "Mark Cleared" button

List-level features:
- Sort by SLA urgency (default), age, client, stage
- Filter by client and stage
- Empty state that doesn't look broken when nothing is escalated

Polish targets:
- SLA countdown that updates live
- Subtle animation when an item leaves the queue (resolved)
- Keyboard shortcut for "resolve and next" (j/k navigation, enter to resolve) — optional but high-signal for evaluator

## Polling
Simple `useEffect` + `setInterval` at 2s. No SWR, no React Query. Single fetch hook in `api.ts`. If polling becomes annoying during dev, add a manual refresh button rather than reaching for a library.

## Types
`types.ts` mirrors backend Pydantic models exactly. Keep them in sync by hand; do not generate.

## Components
- Use shadcn/ui primitives: Card, Badge, Button, Dialog, Tabs, Table
- Build feature components on top; do not abstract a "GenericList" or similar
- Tailwind utility classes inline. No CSS modules, no styled-components.

## State
- Local component state for UI concerns
- A single top-level state hook for the polled backend data, passed via props (or context if it gets ugly, but try props first)
- No Redux, no Zustand, no Jotai

## What NOT to do
- No settings/admin panel
- No user profile / login UI
- No charts or analytics views (unless trivially derived from existing data and adds <30min)
- No routing libraries; a single state variable for active view is enough
- No form libraries; native React state for the resolution form
