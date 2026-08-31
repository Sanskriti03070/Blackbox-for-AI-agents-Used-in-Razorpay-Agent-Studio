# Blackbox for ai agents used in Razorpay Agent Studio 

AI agents can now take real actions on your behalf — retry a payment, issue a refund, message a customer. That's useful, but it creates a new problem: when an agent does something surprising, how do you actually find out why?

This project is a forensic recorder for AI agents that operate on a payment system. It doesn't just log "refund created at 2:31pm" — it reconstructs the full chain: what the agent saw, what it decided and why, whether a safety check approved that decision, what it actually executed, and what changed as a result.

## When you'd actually use this

You don't open Black Box while an agent is running. You open it **after** something happens — a refund you didn't expect, a payment that stayed stuck, a customer complaint about an action an agent took on their account. At that point the only useful question is: *why did the agent do this?*

Without something like Black Box, answering that means digging through application logs, LLM API logs, database rows, and tool call logs separately, and manually piecing together a timeline. Black Box exists so that instead you open one run, and it's already reconstructed for you: the trigger, what context the agent had, what it decided and why, whether the safety layer approved it, what it actually executed, and what changed. It's an incident-review tool, not a live dashboard.

## The trust problem this solves

Financial AI agents are a trust problem before they're a technology problem. An LLM can produce a *reasonable-sounding* decision that is still wrong, or hallucinated, or made with genuinely low confidence. If that decision is allowed to directly touch a database, you have no way to audit it afterward — you just have "the agent did X" with no explanation.

## The approach

The core engineering idea here is **separation between reasoning and action**. The LLM never executes anything. It produces a structured, schema-validated proposal — an action, a reason, and a confidence score. A separate, deterministic layer then decides whether that proposal is even allowed to run:

- Is the confidence above the required threshold? If not, escalate to a human instead of acting.
- Is the action on the allowed list? A hallucinated action like `"delete_payment"` is rejected by schema validation before it's ever considered.
- Does the action satisfy domain rules? (e.g. you cannot refund a payment that was never captured.)

Only after all of that passes does a deterministic tool actually touch the database. This means a wrong or overconfident model output can never move money on its own — the safety property holds even if the LLM is wrong.

The second engineering idea is **evidence as a first-class citizen, not a side effect**. Every stage of a run — trigger, context loaded, decision made, safety check, tool call, state change, outcome — is persisted as an ordered, immutable trace event, sanitized so it never leaks secrets (API keys, card numbers, tokens) into storage. This is what makes the system explainable after the fact instead of just observable while it's running.

## What's actually built

**Payment simulation** — a small but real payment platform: merchants, customers, subscriptions, payments, refunds, payment links, and customer messages, backed by PostgreSQL with real constraints (you cannot refund a payment that was never captured, for example).

**Subscription Recovery Agent** — a LangGraph workflow with two nodes: `reasoning` (calls the model, validates its output against a schema) and `execute_action` (runs the safety checks above, then dispatches to a deterministic tool). Five allowed actions: `retry_payment`, `create_payment_link`, `send_message`, `issue_refund`, `escalate`.

**Forensic trace pipeline** — every run persists an `AgentRun` row plus an ordered sequence of trace events:

agent_started → context_loaded → decision_generated → action_selected
→ policy_checked → tool_executed → state_changed
→ action_executed / action_rejected → agent_completed / agent_failed


Every payload going into these events is sanitized before it hits the database — UUIDs, `Decimal`s, enums, and timestamps are converted to JSON-safe values, and anything that looks like a secret (`api_key`, `card_number`, `cvv`, `authorization`, etc.) is redacted.

**Investigation API** — three endpoints:
- `GET /api/v1/black-box/runs` — list recent runs
- `GET /api/v1/black-box/runs/{run_id}` — the raw run and its full trace
- `GET /api/v1/black-box/investigations/{run_id}` — a reconstructed narrative: the decision, the safety check, the tool call, the resulting state change, a plain-English conclusion, and an evidence-integrity check that flags inconsistencies (e.g. if the tool acted on a different payment than the one loaded into context)

**Dashboard** — a React frontend that lists real runs and lets you drill into any of them across three views: Intelligence ("what happened and why"), Trace ("what did the agent do, step by step"), and Evidence ("how do we know — here's the proof for each claim"), with a collapsible raw-JSON view for anyone who wants the technical detail. This is the "open it after the incident" experience described above.

**Tests** — 44 backend tests covering: all five actions executing correctly from a structured decision, confidence-based escalation, domain safety (refund rules), unsupported/invalid actions being rejected without any financial effect, run and trace persistence for both successful and failed runs, and sensitive-field redaction.

## Architecture at a glance

Payment event (e.g. a failed payment)
↓
Subscription Recovery Agent
├─ loads context (payment, customer, subscription)
├─ asks the model for a decision (action + reason + confidence)
└─ hands that decision to a deterministic executor
↓
Executor (never the LLM)
├─ confidence check → escalate if too low
├─ domain check → reject if invalid (e.g. non-refundable payment)
└─ only then: call a real tool against the payment simulation
↓
PostgreSQL
├─ AgentRun (one row per execution)
└─ AgentTraceEvent (ordered, sanitized, one row per stage)
↓
Investigation API → React dashboard (opened after the fact, to investigate)


See [`docs/architecture.md`](docs/architecture.md) for the fuller design document, including the original architecture contract this was built against and how the current implementation maps onto it.

## Running it locally

Requires Docker and Docker Compose.

```sh
cp .env.example .env
docker compose up -d --build
```

This starts PostgreSQL, the FastAPI backend (`localhost:8000`), and the React dev server (`localhost:5173`).

Run the backend test suite:

```sh
docker compose exec -T backend pytest -q
```

Seed some demonstration payment data:

```sh
docker compose exec backend python -m app.simulation.seed
```

Trigger the agent against a failed payment (see `backend/tests/test_subscription_recovery_llm.py` for example usage), then open `localhost:5173` and select the run from the sidebar to see the full reconstruction.

## Tech stack

| Area | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, PostgreSQL |
| Agent orchestration | LangGraph |
| Frontend | React, TypeScript, Vite |
| Testing | Pytest |
| Local infra | Docker Compose |

No microservices, Kafka, Redis, or Kubernetes — this is intentionally a single, understandable local system. Complexity gets added only when a concrete requirement demands it, not by default.
