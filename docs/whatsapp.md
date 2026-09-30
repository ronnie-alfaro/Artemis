# WhatsApp Third-Party Agent channel

Artemis implements the documented WhatsApp Agent Platform API as a channel adapter. It does not create agents remotely: create the agent in WhatsApp (`Settings > Agents > Create an agent`), obtain its API key, then inject that key as `WHATSAPP_AGENT_TOKEN` through a secret manager. Do not commit the token or enter it through the Artemis API.

## Runtime topology

```text
WhatsApp Agent API long poll -> WhatsAppAgentRuntime -> Artemis Orchestrator
                                                        -> registered agents and skills
WhatsApp Agent API <- serialized adapter send      <- typed OutgoingMessage
                         PostgreSQL cursor, dedupe and conversation mapping
```

Each configured agent owns one poll loop. The loop uses `GET /agent/v1/updates`, persists the returned `next_offset` as a signed 64-bit value, maps opaque `user:<id>` identifiers to Artemis conversations, and records completed inbound `wamid`s before advancing its cursor. A failed message is replayed; a successfully completed one is skipped.

Only the WhatsApp agent's creator is a permitted outbound recipient. Artemis therefore copies the recipient from the current inbound message, never from a long-lived user record. Sends to an individual recipient are serialized. The adapter marks a message read and shows typing only when it is going to generate a reply. Reactions are consumed without automatically producing a reply.

## Configuration

```dotenv
WHATSAPP_AGENT_TOKEN=<secret-manager-reference>
WHATSAPP_AGENT_NAME=primary
```

When the token is absent, no provider client or background poller is started. `GET /api/v1/channels/whatsapp` returns its configured/running status without exposing configuration or secrets.

The enabled runtime requires PostgreSQL through `DATABASE_URL`; it creates a small, isolated state schema for the poll cursor, completed-message ledger, and participant-to-conversation mapping. This is intentionally separate from orchestration state so the core remains channel-neutral.

## Provider constraints implemented

- Bearer-token authentication over HTTPS only.
- Single long poll per agent; provider `409` is treated as a retryable polling failure.
- First poll omits `offset` and receives new traffic only. It does not silently replay the 30-day backlog.
- API output is capped at 4,096 characters. Media is represented as typed inbound attachment metadata; download/upload flows remain a separate capability addition.
- Failures use safe status-only messages and exponential retry backoff. A send with unknown outcome is never silently treated as delivered.

The current documented limits are 12 requests/minute for messages, statuses, and each media method, and 15 polls/minute per agent. Production deployment needs gateway monitoring and rate-limit metrics before enabling several busy agents.
