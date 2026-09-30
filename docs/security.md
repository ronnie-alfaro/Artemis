# Security model

Artemis is a privileged internal service. Its default posture is deny-by-default, least privilege, private networking, and a human decision before mutation.

## Trust boundaries

System policy, agent instructions, user messages, retrieved documents/web pages, MCP results, and tool output are distinct typed fields. Retrieved and external material is untrusted data: it may be quoted or summarized, but cannot alter system policy, tool permissions, routing, or approvals. Agents must never interpret instructions inside retrieved content as executable instructions.

## Controls

- Every agent and tool declares permissions, risk, schemas, timeout, and retry policy.
- `READ` is automatic; `WRITE` needs approval by default; `DESTRUCTIVE` always needs explicit approval; `ADMIN` is disabled unless configured.
- Approval records include operation, agent, tool, validated parameters, risk, reason, expiry, result, and durable audit state in PostgreSQL. Approval is a platform primitive, not a channel feature.
- Inputs and outputs are validated at every boundary. Tool invocations have allowlisted implementations only.
- No arbitrary shell, SSH, Docker socket, arbitrary filesystem, or unrestricted network tool exists. Homelab starts read-only and HTTP-target allowlisted.
- Containers are non-root, use read-only filesystems/capability drops/no-new-privileges, and databases have no published port.
- Secrets are injected through environment/secret mechanisms, excluded from git/database/logs, and represented by references rather than values in configuration.
- Logs carry request/conversation/execution IDs, redact headers/secrets, and support private-prompt mode.
- Rate limiting/authentication boundaries sit at the gateway; production deployments place the UI/API behind an authenticated reverse proxy such as Authentik.

## Incident-oriented behavior

Every sensitive request, permission decision, tool invocation, and approval is auditable. Errors are classified without returning sensitive internals to channels. Timeouts, provider outages, malformed tool calls, bad manifests, and plugin crashes degrade an execution to a partial trace rather than granting broader access or crashing the process.

## Required production work before privileged tools

OIDC/session validation, CSRF policy for browser sessions, persistent audit store, secret manager integration, retention controls, tenant/user authorization, egress controls, threat-model review, and independent security scanning must be completed before write-capable agents are enabled.

## Seerr-specific controls

The optional adapter accepts only validated `SEERR_BASE_URL` and `SEERR_API_KEY`; the key is sent solely as `X-Api-Key` and never appears in DTOs, traces, approvals, API responses or errors. HTTP failures map to safe structured codes without logging headers or bodies.

`seerr.create_request` is `WRITE`: ToolRegistry limits it to the `seerr` agent and requires an unexpired approval for that exact tool. “sí”/“confirmo” works only when exactly one current approval belongs to that conversation; it cannot authorize an old, rejected, expired or unrelated operation. Replayed selections reuse a conversation/media/requester idempotency key.
