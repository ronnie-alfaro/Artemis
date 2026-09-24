# Delivery roadmap

## M0 — foundation (implemented)

Architecture/security/roadmap documentation, ADRs, Docker Compose topology, CI scaffolding, quality commands, and the first typed vertical slice.

## M1 — durable core

PostgreSQL models and Alembic, REST channel, conversation/activity persistence, fake provider, and a flow sandbox/execution-trace UX.

## M2 — registry and plugins

Signed/trusted manifest discovery, health reporting, agent pages, capability discovery, configuration validation.

## M3 — orchestration

Provider-backed typed planning, DAG dependencies, concurrent scheduling, retries, partial results, synthesis, deterministic tests/evals.

## M4 — tools and approvals

Tool registry, policy evaluator, persisted approval lifecycle, approval UI, audit events.

## M5–M7 — useful capabilities

Qdrant-bound Library Agent, provider-agnostic Research Agent, read-only allowlisted Homelab Agent, tracing/metrics/activity UI.

## M8–M10 — extensibility and hardening

MCP client boundary, eval datasets and CI reports, authentication, retention, backups, release/deploy automation, operational runbooks.

## M11 — WhatsApp (blocked by public specification)

Implement only after official documentation covers authentication, endpoint/connection lifecycle, send/receive, media, IDs, rate limits, reconnect/error behavior, and API-key rotation. Work stays in `channels/whatsapp` and channel configuration.
