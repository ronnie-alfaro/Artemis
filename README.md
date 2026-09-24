# ARTEMIS

Artemis is a self-hosted, channel-agnostic agentic orchestration platform for private environments. It starts as a secure modular monolith: channels submit typed messages, the orchestration core builds a capability-based execution DAG, independently-defined agents run behind permission boundaries, and a response plus trace returns to the channel.

This repository currently delivers the first vertical slice: Web control plane -> versioned REST API -> orchestrator -> deterministic FakeAgent -> registered FakeTool -> response. The UI is a SaaS-style control plane for composing and operating agents, skills, flows, channels, runs, approvals, and configuration. It is intentionally provider-free and safe to run locally.

## Quick start

Requires Docker Compose. The default deployment exposes only the web UI on `127.0.0.1:8080`; PostgreSQL remains on the internal Docker network.

```bash
cp .env.example .env
make up
```

Open http://127.0.0.1:8080. Run verification with `make test lint typecheck`.

## Runtime topology

```text
Browser -> artemis-web (edge + internal network) -> artemis-api -> PostgreSQL
                                                  |
                                                  +-> Agent Registry -> registered tools
```

No Docker socket, host filesystem, external LLM, Qdrant, or MCP server is required by this milestone. See [architecture](docs/architecture.md), [security](docs/security.md), and [roadmap](docs/roadmap.md).

## Development commands

`make dev`, `make test`, `make lint`, `make typecheck`, `make eval`, `make build`, `make up`, and `make down` are the supported entry points.

## WhatsApp

WhatsApp is a future channel adapter only. Artemis does not fabricate or probe an undocumented integration. The Web UI is where a future adapter would be configured and associated with a validated flow. See [WhatsApp tracking](docs/whatsapp.md).
