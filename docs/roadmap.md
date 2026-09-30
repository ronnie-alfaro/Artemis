# Delivery roadmap

## M0 — foundation (implemented)

Architecture/security/roadmap documentation, ADRs, Docker Compose topology, CI scaffolding, quality commands, and the first typed vertical slice.

## M1 — durable core

PostgreSQL models and Alembic, conversation/activity persistence, execution-trace UX, and production migrations.

## M2 — registry and plugins

Signed/trusted manifest discovery, health reporting, agent pages, capability discovery, configuration validation.

## M3 — orchestration

Provider-backed typed planning, DAG dependencies, concurrent scheduling, retries, partial results, synthesis, deterministic tests/evals.

## M4 — tools and approvals

Tool registry, policy evaluator, persisted approval lifecycle, approval UI, audit events.

The Seerr slice demonstrates an optional typed business tool and explicit `WRITE` confirmation. Persistence, tenant identity, season/quality UI, egress allowlisting and a live integration smoke test remain prerequisites for production enablement.

## M5–M7 — useful capabilities

Qdrant-bound Library Agent, provider-agnostic Research Agent, read-only allowlisted Homelab Agent, tracing/metrics/activity UI.

## M8–M10 — extensibility and hardening

MCP client boundary, eval datasets and CI reports, authentication, retention, backups, release/deploy automation, operational runbooks.

## M11 — WhatsApp (initial adapter implemented)

The documented Agent API supports secret-backed authentication, a durable single-poller receive loop, text replies, read/typing status, opaque participant mapping, and deduplication. Next work: media transfer/verification, multi-agent configuration, migrations, rate-limit metrics, and a safely configured live smoke test.
