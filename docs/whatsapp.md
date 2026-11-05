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

Only the WhatsApp agent's creator is a permitted outbound recipient. Chat replies use the recipient from the current inbound message. Webhook notifications use the only known participant, or an explicitly configured participant that must already exist in the conversation mapping. Sends to an individual recipient are serialized. The adapter marks a message read and shows typing only when it is going to generate a reply. Reactions outside an active choice menu are consumed without producing a reply.

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

## Skill activo por conversación

- `utiliza usenet`, `utiliza karakeep` o `utiliza seerr` activa el skill asignado.
  También se acepta su nombre personalizado, sin distinguir mayúsculas.
- Con el skill activo, todos los comandos de chat se envían a ese skill:
  `busca Rocky` busca en Usenet; tras `utiliza karakeep`, `busca docker` busca bookmarks.
- `ayuda` muestra los comandos del skill activo. `ayuda SKILL` consulta otro sin cambiarlo.
- `salir` vuelve al modo general. Allí `ayuda` lista los skills brevemente y una búsqueda
  ambigua pide elegir uno cuando hay varios disponibles.
- Cambiar de skill o salir rechaza las aprobaciones pendientes y descarta las selecciones
  de búsquedas anteriores. Activar de nuevo el mismo skill conserva sus operaciones pendientes.
- La selección se guarda en PostgreSQL por canal y conversación, y sobrevive al reinicio.
  Si se retira la asignación del skill, la siguiente interacción vuelve al modo general.
- Los planes explícitos de la API (`required_capabilities`) conservan su enrutamiento explícito.

La tabla `conversation_skill_sessions` se crea automáticamente al arrancar con `DATABASE_URL`.
Sin base de datos, las sesiones permanecen solo en memoria durante el proceso.

## Presentación de mensajes

Las respuestas y notificaciones comparten formato de WhatsApp: títulos en `*negrita*`,
comandos entre acentos graves, listas con guiones o números y secciones separadas por
líneas en blanco. Las respuestas de Codex y Antigravity se adaptan automáticamente:
encabezados Markdown pasan a negrita y los enlaces muestran su dirección completa.
El contenido de código y las URLs se conservan.

Los textos largos se dividen por párrafos, líneas o espacios dentro del límite de
WhatsApp, en lugar de truncarse. Los bloques de código se cierran y reabren al dividirlos.
No se envían mensajes de prueba a conversaciones reales durante la validación.

## Elegir opciones mediante reacciones

Los menús de habilidades, la elección de habilidad ante búsquedas ambiguas y los
resultados de Seerr y Usenet ofrecen emojis numéricos (`1️⃣`…`🔟`). Reacciona al
mensaje con el emoji de la opción (usa `＋` para buscarlo) o escribe el comando
habitual. La selección sigue el mismo recorrido que el texto: elegir un resultado
prepara la operación y conserva su confirmación explícita.

Cada menú se vincula al identificador del mensaje enviado y a su destinatario.
Solo acepta una elección durante 15 minutos. Un mensaje nuevo del usuario o un
menú posterior desactiva el anterior. Al reiniciar Artemis se invalidan los menús,
porque los candidatos de búsqueda de los agentes viven en memoria. Las reacciones
no ofrecidas, eliminadas, repetidas, ajenas o caducadas se ignoran sin responder.
Las notificaciones no reemplazan los menús de elección.

Las opciones se declaran en `AgentResult.reaction_options` y se propagan a
`OutgoingMessage`; el canal no intenta deducir acciones de texto generado libremente.
El emoji y el mensaje de origen de las reacciones se conservan en la bandeja de
entrada persistente. La tabla `whatsapp_reaction_menus` se crea automáticamente y
reclama cada selección de forma atómica; los reintentos del mismo evento mantienen
su selección.
