# Razorpay AI Black Box

An eventual flight recorder and forensic investigation layer for autonomous financial AI agents. The first use case will be a LangGraph-powered Subscription Recovery Agent operating against a local Razorpay-style simulated payment environment.

The product will capture real agent execution as immutable forensic evidence: model interactions, backend tool calls, decisions, results, failures, and reconstructable context snapshots. A separate AI investigator will analyze recorded evidence without being able to alter it.

## Current status

This repository currently contains the architecture contract only. No application, agent, frontend, database models, sample data, or dependencies have been added.

See [the architecture contract](docs/architecture.md) for the system design, boundaries, event model, entity contract, repository layout, constraints, and planned phases.

## Intended stack

- Python 3.12, FastAPI, Pydantic, SQLAlchemy, PostgreSQL
- LangGraph and the OpenAI API
- React, TypeScript, Vite, Tailwind CSS, React Flow
- scikit-learn, Pytest, Docker Compose

## Intended local topology

The eventual local setup will remain a single repository with a FastAPI backend, React dashboard, and PostgreSQL started through Docker Compose. It deliberately does not introduce microservices, Kafka, Redis, or Kubernetes.

## Next step

The next implementation phase is intentionally not started by this change. It will establish the foundation (project setup, Docker Compose, configuration, migrations, and tests) while preserving the architecture contract.

## Payment simulation (Phase 2)

The backend now includes a PostgreSQL-backed local payment simulation for merchants, customers, subscriptions, payments, refunds, payment links, and persisted recovery messages. It contains no external Razorpay integration and no AI-agent functionality.

Start the local stack and seed its deterministic demonstration data explicitly:

```sh
docker compose up --build -d
docker compose exec backend python -m app.simulation.seed
```

The seed command is idempotent. It is never run automatically at application startup.
