# Architecture

## Proposal and scope

Artemis is a modular monolith for a homelab: one API process owns orchestration and platform state, while channel adapters, agents, model providers, storage, and tools are replaceable ports. This avoids distributed-systems operational cost before scale requires it. PostgreSQL is the source of truth for durable platform state; vector retrieval remains behind a separate library port.

```text
 Channel adapters                 Application / domain                  Infrastructure
 REST | Web | CLI | WhatsApp -> Gateway -> Orchestrator -> Registry -> Agents -> Tools/Providers/MCP
                                      |            |             |              |
                                   Conversation   DAG        permissions       audit/events
                                      |            |             |              |
                                   PostgreSQL <---+-------------+--------------+
```

`WhatsApp` is a documented long-poll adapter. It owns provider tokens, cursor/deduplication state,
opaque participant mapping and outbound serialization; the orchestrator receives ordinary typed messages.

## Core contracts

The domain uses explicit Pydantic contracts: `IncomingMessage`, `OutgoingMessage`, `Conversation`, `Agent`, `AgentCapability`, `AgentRequest`, `AgentResponse`, `AgentExecution`, `AgentResult`, `Tool`, `ToolInvocation`, `ToolResult`, `Channel`, `ModelProvider`, `Permission`, `ApprovalRequest`, and `ExecutionPlan`.

```text
ChannelAdapter.receive() -> IncomingMessage -> Orchestrator.handle()
  -> CapabilityPlanner.plan() -> ExecutionPlan(nodes, dependencies)
  -> DAGExecutor.execute() -> Agent.run(AgentRequest) -> ToolRegistry.invoke()
  -> AgentResult[] -> synthesizer -> OutgoingMessage -> ChannelAdapter.send()
```

The planner consumes requested capabilities, not agent names or keywords. A future model-backed planner produces the same typed `ExecutionPlan`; it cannot select a tool directly. The executor runs currently-unblocked nodes concurrently, applies retry policy, and retains results/errors in the trace.

## Agent and plugin model

An `Agent` is an independently declared capability: identity, purpose, instructions, capability list, permission set, model requirements, schemas, timeout/retry policy, health, metadata, optional memory, and MCP references. `AgentRegistry` validates manifests and registers healthy plugins; invalid plugins become unhealthy records rather than preventing startup. The initial runtime packages are the system status agent and optional `seerr`. Seerr is a business tool, not a channel or orchestration dependency.

Manifests are validated at startup and instantiate agents through a trusted local entry-point mapping. Arbitrary plugin code is never loaded from user-controlled paths.

## Risks and trade-offs

| Decision | Benefit | Cost / mitigation |
| --- | --- | --- |
| Modular monolith | simple deploy/debug/audit | define ports and domain events so services can split later |
| Typed DAG, not workflow engine | predictable and testable | limited dynamic workflows initially |
| Status-first fallback | a safe response when no optional skill matches | providers remain behind typed interfaces |
| PostgreSQL platform state | familiar, durable | Alembic migrations and retention policy required |
| Tools behind permissions | prevents direct model authority | approvals add interaction latency |

## Dependencies

- FastAPI/Pydantic v2: typed async API and OpenAPI.
- SQLAlchemy 2 + Alembic + asyncpg: durable PostgreSQL state and migrations (introduced with persistence milestone).
- `prometheus-client` and OpenTelemetry APIs: vendor-neutral metrics/tracing.
- React/Vite: strict, fast Web UI; no heavyweight component framework.
- pytest/httpx, Vitest/RTL, Playwright: deterministic layered testing.

Each optional provider SDK is confined to its adapter package. Qdrant, Ollama, and MCP dependencies are optional extras, not core requirements.

## Repository tree

```text
backend/app/{api,application,domain,infrastructure,agents,tools,evals}
backend/tests/{unit,integration,api}
frontend/src/{features,components,styles}
docs/adr
.github/workflows
deploy/
```

## Product control plane

Artemis is not a chat product. Its Web UI is the control plane where operators compose versioned, permissioned flows from agents and skills, bind a flow to a channel, inspect runs, and approve sensitive actions. The REST channel and a future Web sandbox are test surfaces, not the product's primary interaction model. A visual builder produces a declarative execution DAG; it may not introduce arbitrary code, unknown tools, unchecked dependencies, or privilege escalation.

Primary navigation is `Overview`, `Agents`, `Skills`, `Flows`, `Channels`, `Runs`, `Approvals`, and `Settings`. WhatsApp belongs exclusively in `Channels`; its agent is created in WhatsApp and connected with secret-backed configuration.

## First vertical slice

WhatsApp submits typed inbound traffic through its adapter; the capability planner selects a configured optional skill only when bound to that agent, otherwise it selects the system status agent. The executor returns a typed response through the channel adapter. No demo agent or fake tool exists in the runtime.

## Optional Seerr tool slice

`SeerrClient` is a domain port with explicit media/request DTOs. `HttpSeerrClient` is its infrastructure implementation using `X-Api-Key`, `GET /api/v1/search`, typed details/status reads, and `POST /api/v1/request`. The sequence is `intent -> search -> selected candidate -> ApprovalRequest -> create_request`. Results contain title, year, type and TMDB id. A TV series is currently requested as a full series; granular season and quality-profile selection are reserved in DTOs but not claimed by this first conversational UI.

Approval and candidate state are in-memory in this vertical slice, including conversation, sanitized parameters, operation correlation, expiry and idempotency. They must move to PostgreSQL before multi-process production. The WhatsApp adapter has its own PostgreSQL cursor/deduplication state; neither the Seerr port nor the orchestrator imports it.
