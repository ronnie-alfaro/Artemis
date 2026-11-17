# Security model

Artemis is a privileged internal service. Its default posture is deny-by-default, least privilege, private networking, and a human decision before mutation.

## Trust boundaries

System policy, agent instructions, user messages, retrieved documents/web pages, MCP results, and tool output are distinct typed fields. Retrieved and external material is untrusted data: it may be quoted or summarized, but cannot alter system policy, tool permissions, routing, or approvals. Agents must never interpret instructions inside retrieved content as executable instructions.

## Controls

- Every agent and tool declares permissions, risk, schemas, timeout, and retry policy.
- `READ` is automatic; `WRITE` needs approval by default; `DESTRUCTIVE` always needs explicit approval; `ADMIN` is disabled unless configured.
- Approval records include operation, agent, tool, validated parameters, risk, reason, expiry, result, and durable audit state in PostgreSQL. Approval is a platform primitive, not a channel feature.
- Inputs and outputs are validated at every boundary. Tool invocations have allowlisted implementations only.
- Codex and Antigravity are explicit privileged exceptions: their host workers execute requested tasks as root, with filesystem writes, shell commands and network access, without additional approval. Their API containers share only job queues. Restrict skill assignment to authorized conversations. Homelab HTTP adapters remain target allowlisted.
- Containers are non-root, use read-only filesystems/capability drops/no-new-privileges, and databases have no published port.
- Secrets are injected through environment/secret mechanisms, excluded from git/database/logs, and represented by references rather than values in configuration.
- Logs carry request/conversation/execution IDs, redact headers/secrets, and support private-prompt mode.
- Rate limiting/authentication boundaries sit at the gateway; production deployments place the UI/API behind an authenticated reverse proxy such as Authentik.

## Incident-oriented behavior

Every sensitive request, permission decision, tool invocation, and approval is auditable. Errors are classified without returning sensitive internals to channels. Timeouts, provider outages, malformed tool calls, bad manifests, and plugin crashes degrade an execution to a partial trace rather than granting broader access or crashing the process.

## Required production work before privileged tools

OIDC/session validation, CSRF policy for browser sessions, persistent audit store, secret manager integration, retention controls, tenant/user authorization, egress controls, threat-model review, and independent security scanning must be completed before write-capable agents are enabled.

## External-skill controls

The optional adapter accepts only validated `SEERR_BASE_URL` and `SEERR_API_KEY`; the key is sent solely as `X-Api-Key` and never appears in DTOs, traces, approvals, API responses or errors. HTTP failures map to safe structured codes without logging headers or bodies.

`seerr.create_request` is `WRITE`: ToolRegistry limits it to the `seerr` agent and requires an unexpired approval for that exact tool. “sí”/“confirmo” works only when exactly one current approval belongs to that conversation; it cannot authorize an old, rejected, expired or unrelated operation. Replayed selections reuse a conversation/media/requester idempotency key.

The optional Karakeep adapter accepts only a validated base URL and API key. The key is sent solely as `Authorization: Bearer` and never appears in DTOs, traces, approvals, API responses or safe error messages. The connection check uses `GET /api/v1/lists`; `karakeep.create_bookmark` is a `WRITE` allowlisted to the `karakeep` agent and requires an unexpired approval for that exact URL.

`notifications.send` is an explicit WRITE exception with `requires_approval=False`:
it can only enqueue text for the operator-configured channel and a known WhatsApp
participant. Registered skills and authenticated manual sends share that delivery
service. It cannot accept arbitrary recipients or change notification settings.
Other WRITE tools retain approval by default, and DESTRUCTIVE/ADMIN tools cannot
bypass approval using this flag.

`reminders.create` schedules time triggers or allowlisted READ tools only. The scheduler
revalidates the tool at execution, uses a bounded timeout and a declarative result path
without eval. READ invocations cannot execute tools that have been changed to WRITE.
Reminders enqueue alerts through `notifications.send` using the configured destination.

Codex uses `danger-full-access` and `approval_policy="never"`; Antigravity uses
`--dangerously-skip-permissions`. Both operate on the real source tree. New jobs
do not generate review-only patches. Interrupted jobs may leave partial changes and
are never automatically replayed. See [Codex](codex.md) and [Antigravity](antigravity.md).
