# Architecture

## Proposal and scope

Artemis is a modular monolith for a homelab: one API process owns orchestration and platform state, while channel adapters, agents, model providers, storage, and tools are replaceable ports. This avoids distributed-systems operational cost before scale requires it. PostgreSQL is the source of truth for durable platform state; vector retrieval remains behind a separate library port.

```text
 Channel adapters                 Application / domain                  Infrastructure
 REST | Web | CLI | WhatsApp? -> Gateway -> Orchestrator -> Registry -> Agents -> Tools/Providers/MCP
                                      |            |             |              |
                                   Conversation   DAG        permissions       audit/events
                                      |            |             |              |
                                   PostgreSQL <---+-------------+--------------+
```

`WhatsApp?` is an empty adapter boundary pending official Third-Party Agent API documentation. No protocol is assumed.

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

An `Agent` is an independently declared capability: identity, purpose, instructions, capability list, permission set, model requirements, schemas, timeout/retry policy, health, metadata, optional memory, and MCP references. `AgentRegistry` validates manifests and registers healthy plugins; invalid plugins become unhealthy records rather than preventing startup. Initial packages are `library`, `research`, `homelab`, and this milestone's `fake` reference.

Manifests are validated at startup and instantiate agents through a trusted local entry-point mapping. Arbitrary plugin code is never loaded from user-controlled paths.

## Risks and trade-offs

| Decision | Benefit | Cost / mitigation |
| --- | --- | --- |
| Modular monolith | simple deploy/debug/audit | define ports and domain events so services can split later |
| Typed DAG, not workflow engine | predictable and testable | limited dynamic workflows initially |
| Deterministic fake planner first | no provider cost/flakiness | production planner arrives behind interface |
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

Primary navigation is `Overview`, `Agents`, `Skills`, `Flows`, `Channels`, `Runs`, `Approvals`, and `Settings`. WhatsApp belongs exclusively in `Channels` when official documentation permits a real adapter.

## First vertical slice

Web UI submits text to `POST /api/v1/chat`; REST creates `IncomingMessage`; the capability planner selects the registered `fake.echo` agent; the executor invokes the registered read-only `fake.echo_tool`; a typed response and expandable trace returns. It proves channel/core/agent/tool boundaries without provider credentials or privileged actions.
