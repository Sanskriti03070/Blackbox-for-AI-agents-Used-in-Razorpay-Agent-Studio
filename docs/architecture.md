# Razorpay AI Black Box — Architecture Contract

## Purpose

Razorpay AI Black Box is a flight recorder and forensic investigation layer for autonomous financial AI agents. It will provide a local, Razorpay-style simulated payment environment and a real LLM-powered Subscription Recovery Agent. The Black Box records what the agent saw, decided, called, and returned, so an incident can be investigated and later replayed from recorded evidence.

The product is not a log viewer with fabricated data. Instrumentation is part of the execution path: an agent run emits durable forensic events while it executes. A later investigator can read this immutable record, but cannot alter it.

## System shape

The system is a single repository and will run locally with Docker Compose. It begins as a modular FastAPI application backed by PostgreSQL, with a separate React/TypeScript frontend package. Modules have clear interfaces but are deployed together unless a later requirement justifies separation.

```text
React investigation dashboard
             |
             v
FastAPI API ----------------------------------------------------+
 |                 |                 |                         |
 v                 v                 v                         v
Investigation   Simulation API   Agent orchestration       Replay/anomaly
read APIs       (payments)       (LangGraph + tools)       services
                                      |
                                      v
                              Black Box SDK / recorder
                                      |
                                      v
                                PostgreSQL
                    runs, immutable events, snapshots,
                    financial simulation state, incidents
```

The Subscription Recovery Agent uses an LLM through the OpenAI API and invokes real backend tool functions against the simulated payment environment. Every model call, tool invocation, decision, and result flows through the Black Box SDK before control returns to the agent graph.

## Components and responsibilities

### FastAPI application

Owns HTTP APIs, validation, authentication/authorization when introduced, dependency wiring, and transaction boundaries. It exposes APIs for the payment simulation, starting and inspecting agent runs, incidents, replay, and dashboard read models. It must not contain unstructured agent or forensic business logic in route handlers.

### Simulated payment environment

Provides Razorpay-style domain operations for merchants, customers, subscriptions, payments, refunds, and payment links. It is a real local backend module and database state, not a mocked response layer. The agent's tools call this module through application services so the same behavior can be exercised through APIs and tests.

### Subscription Recovery Agent

The first instrumented agent is a LangGraph workflow that recovers failed subscription payments. It uses the OpenAI API for model reasoning and invokes application-backed tools such as `get_payment`, `get_customer`, `get_subscription`, `get_payment_history`, `retry_payment`, `create_payment_link`, `send_message`, and `issue_refund`.

The agent owns its graph state and recovery policy. It does not write forensic tables directly; it receives an instrumented execution context and uses Black Box-wrapped model and tool interfaces.

### Black Box SDK / instrumentation layer

Provides the stable, reusable instrumentation boundary for this agent and future agent types. It allocates a `run_id`, maintains execution context, creates event IDs, establishes parent-child relationships, records timestamps and safe serialized inputs/outputs, and captures context snapshots.

Instrumentation must wrap actual execution operations. The API should support scoped spans/contexts so a model call, tool call, decision, or nested agent operation can be recorded consistently. It should be independent of the Subscription Recovery Agent's particular graph.

### Forensic investigation service

Builds an evidence package from immutable run events and snapshots, then asks an OpenAI-powered investigator to explain observed behavior, cite event IDs, identify uncertainties, and propose follow-up checks. It has read-only access to recorded history. Its generated analysis is stored separately as an investigation artifact or incident note, never by editing prior run records.

### Replay and counterfactual services

Replay reconstructs an execution from recorded events and context snapshots. A deterministic replay initially replays recorded model/tool outputs to inspect the historical path. Counterfactual replay uses an explicitly declared changed input, policy, or model configuration and records its result as a new run linked to the source run; it never mutates the source.

### Anomaly detection service

Starts with interpretable features derived from completed runs—such as tool sequence, retry count, latency, amount bands, failure outcomes, and graph shape—and statistical detection/Isolation Forest. Scores and explanations are derived artifacts linked to runs rather than modifications to the immutable event history.

### React investigation dashboard

Presents recorded evidence, execution graphs, event details, context snapshots, incidents, replay comparisons, and anomaly findings. It consumes APIs only; it does not synthesize historical events or bypass the backend's evidence boundaries. React Flow will visualize parent-child execution graphs.

## Execution and data flow

1. A user/API request starts an agent execution.
2. The Black Box SDK creates an `AgentRun` with a unique `run_id` and persists `RUN_STARTED` and `USER_REQUEST` events.
3. The SDK records a versioned `ContextSnapshot` of the execution context needed for reconstruction, then emits `CONTEXT_SNAPSHOT`.
4. The LangGraph workflow invokes the model through the instrumented model wrapper. The wrapper records `MODEL_CALL` and `MODEL_RESPONSE` events.
5. When the model selects a tool, the instrumented tool wrapper records `TOOL_CALL`, invokes the real simulation service, and records `TOOL_RESULT` (or `ERROR`).
6. Material agent choices are recorded as `DECISION` events with the evidence and rationale available at the time.
7. The workflow records an `OUTCOME` and terminates with `RUN_COMPLETED`, or records an error and a completed failed run according to the run-status contract.
8. Investigation, replay, counterfactual, anomaly, and dashboard flows read the completed evidence. Counterfactual work creates a distinct linked run.

## Data architecture

PostgreSQL is the system of record. SQLAlchemy models and migrations will be added in a later implementation phase. The following is the conceptual contract, not a database schema.

| Entity | Responsibility |
| --- | --- |
| `Agent` | Registered agent definition, type, version, and supported capabilities. |
| `AgentRun` | One execution: its `run_id`, agent/version, status, timing, initiator, and optional source-run link. |
| `AgentEvent` | Immutable execution record with `event_id`, event type, parent event, sequence/order, timestamps, safe input/output payloads, and metadata. |
| `ContextSnapshot` | Versioned, serialized execution context referenced by a run/event; includes capture metadata and integrity information. |
| `Incident` | A forensic case associated with one or more runs; contains investigator artifacts separately from the evidence stream. |
| `Merchant` | Simulated business account. |
| `Customer` | Simulated payer associated with a merchant. |
| `Subscription` | Simulated recurring-payment agreement and lifecycle state. |
| `Payment` | Simulated payment attempt, amount, currency, status, and subscription relationship. |
| `Refund` | Simulated refund associated with a payment. |
| `PaymentLink` | Simulated payment-recovery link associated with a customer/payment/subscription. |

Forensic records (`AgentRun`, `AgentEvent`, and `ContextSnapshot`) are append-only after capture. Corrections or annotations must be represented as new linked records, not updates to historical evidence. Database roles and application-level safeguards will enforce that investigators have no write path to that evidence.

## Event model

Each `AgentEvent` has a globally unique `event_id`, belongs to one `run_id`, and can reference a `parent_event_id`. Parent links form an execution graph; a stable per-run sequence/order provides deterministic display and replay ordering even when events are concurrent.

Common event fields:

- identity and graph: `event_id`, `run_id`, `parent_event_id`, event type, sequence/order
- time: UTC creation timestamp plus optional started/completed timestamps and duration
- provenance: agent name/version, graph node/span name, actor/component, correlation identifiers
- evidence: safely serialized input, output/result, metadata, error details, and references to context snapshots
- integrity: schema version, redaction classification, and optional payload/content hashes

The initial event vocabulary is:

| Event | Meaning |
| --- | --- |
| `RUN_STARTED` | A run was allocated and execution began. |
| `USER_REQUEST` | The triggering request and validated parameters. |
| `CONTEXT_SNAPSHOT` | A reconstructable execution-state capture was stored. |
| `MODEL_CALL` | A request was sent to a model, including safe model/configuration metadata. |
| `MODEL_RESPONSE` | The model returned a response, tool choice, or structured output. |
| `TOOL_CALL` | The agent requested a backend/domain tool operation. |
| `TOOL_RESULT` | The tool returned its result. |
| `DECISION` | A material agent choice and the evidence available for it. |
| `OUTCOME` | The business or workflow result. |
| `ERROR` | A captured execution, tool, model, or persistence error. |
| `RUN_COMPLETED` | The terminal run status and summary. |

Payload capture must be explicit and safe: secrets, credentials, raw authorization data, and unnecessary personally identifiable information must be redacted or represented by references/hashes. The exact redaction policy and retention rules will be defined before persistence is implemented.

## Repository structure

The current repository is a documented skeleton. The following structure is the intended single-repository layout when implementation begins:

```text
.
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routes and request/response schemas
│   │   ├── blackbox/         # SDK, event recording, snapshots, redaction
│   │   ├── agents/           # LangGraph agents and tool adapters
│   │   ├── simulation/       # Payment-domain services and APIs
│   │   ├── forensics/        # Evidence assembly and investigator service
│   │   ├── replay/           # Replay and counterfactual orchestration
│   │   ├── anomalies/        # Feature extraction and anomaly scoring
│   │   ├── db/               # SQLAlchemy, migrations, repositories
│   │   └── core/             # Settings, shared errors, dependencies
│   └── tests/
├── frontend/                 # Vite React/TypeScript dashboard
├── docs/                     # Architecture and operating documentation
├── scenarios/                # Versioned test/replay scenario definitions
├── docker-compose.yml         # Local application + PostgreSQL topology
├── .env.example              # Documented, non-secret local configuration
└── README.md
```

The proposed folders are a boundary map, not a requirement to create empty packages prematurely. Cross-module access should use service interfaces rather than reach into another module's persistence implementation.

## Technology stack

| Area | Chosen technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy |
| Agent orchestration | LangGraph and the OpenAI API |
| Database | PostgreSQL |
| Frontend | React, TypeScript, Vite, Tailwind CSS, React Flow |
| ML | scikit-learn; initially Isolation Forest and statistical techniques |
| Testing | Pytest |
| Local infrastructure | Docker Compose |

No microservices, Kafka, Redis, Kubernetes, or similar infrastructure is part of this contract. They require an explicit future need.

## Architectural constraints

- Instrument real agent execution; never fabricate forensic logs for product behavior.
- Assign a unique `run_id` to every execution and a unique `event_id` to every event.
- Preserve parent-child event relationships and a deterministic event order.
- Capture versioned context snapshots sufficient for reconstruction, subject to redaction policy.
- Keep recorded history immutable to the forensic investigator and all normal read flows.
- Make replay and counterfactual replay first-class future consumers of the evidence contract.
- Ensure counterfactual results are new, linked executions rather than changed history.
- Keep domain simulation, agent orchestration, instrumentation, and UI modular, but local and understandable in one repository.
- Use real LLM calls and real backend tool calls when the agent is implemented; test doubles belong only in tests.
- Version event payload schemas, agent definitions, prompts/configurations, and snapshots so historical evidence remains interpretable.
- Design APIs and SDK interfaces so additional agents can be instrumented without coupling them to the demo agent's graph.
- Prefer simple synchronous/local execution initially; introduce background workers or external infrastructure only when concrete requirements demand them.

## Development phases

1. **Foundation** — Create backend/frontend project setup, local Docker Compose, settings, database migrations, and test harness.
2. **Payment simulation** — Implement the payment domain and Razorpay-style local APIs with real PostgreSQL persistence.
3. **Black Box core** — Implement immutable run/event/snapshot persistence, the instrumentation SDK, redaction, and run-inspection APIs.
4. **Instrumented recovery agent** — Build the LangGraph Subscription Recovery Agent with real OpenAI model calls and real simulation tools routed through the SDK.
5. **Investigation experience** — Add evidence assembly, read-only AI investigation, incident artifacts, and the React investigation dashboard.
6. **Replay** — Add deterministic historical reconstruction and graph/event visual comparison.
7. **Counterfactual replay** — Add explicit-parameter variant execution linked to source runs.
8. **Anomaly detection** — Add interpretable features, baseline statistical/Isolation Forest scoring, and dashboard/API surfacing.
9. **Hardening** — Expand tests, observability, redaction/retention controls, failure handling, and local operational documentation.

Each phase must preserve the evidence contract above. Completing this document does not authorize or start implementation of any later phase.
