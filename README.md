# ARTEMIS

Artemis is a self-hosted, channel-agnostic agentic orchestration platform for private environments. It starts as a secure modular monolith: channels submit typed messages, the orchestration core builds a capability-based execution DAG, independently-defined agents run behind permission boundaries, and a response plus trace returns to the channel.

This repository delivers a self-hosted WhatsApp agent control plane: Web UI -> versioned API -> orchestrator -> system status agent and configured skills -> WhatsApp Agent API. The UI composes and operates agents, skills, channels, approvals, and configuration without demo agents or fake runtime tools.

## Quick start

Requires Docker Compose. The default deployment exposes only the web UI on `127.0.0.1:8080`; PostgreSQL remains on the internal Docker network.

```bash
cp .env.example .env
make up
```

Open http://127.0.0.1:8080. Run verification with `make test lint typecheck`.

For a persistent host deployment, use the separate [production deployment guide](docs/deployment.md). It requires an operator token, durable secrets, backups, and an authenticated access path.

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

WhatsApp is a documented, optional long-poll channel adapter. Create the agent in WhatsApp, inject its API token through `WHATSAPP_AGENT_TOKEN`, and Artemis connects it to the same typed orchestration and skills layers as the control plane. See [WhatsApp channel](docs/whatsapp.md).

## Karakeep

Karakeep is an optional bookmarks skill. Configure its URL and API key in the control plane, test the connection, then drag `karakeep.bookmarks` onto the WhatsApp agent. Saving a link always requires a concrete approval. See [Karakeep skill](docs/karakeep.md).
