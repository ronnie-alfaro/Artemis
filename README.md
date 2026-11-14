# ARTEMIS

Artemis is a self-hosted, channel-agnostic agentic orchestration platform for private environments. It starts as a secure modular monolith: channels submit typed messages, the orchestration core builds a capability-based execution DAG, independently-defined agents run behind permission boundaries, and a response plus trace returns to the channel.

This repository delivers a self-hosted WhatsApp agent control plane: Web UI -> versioned API -> orchestrator -> system status agent and configured skills -> WhatsApp Agent API. The UI composes and operates agents, skills, channels, and configuration without demo agents or fake runtime tools.

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

## Usenet

Configure **Habilidades → Usenet** with an NZBPlanet URL/API key and an NZBGet XML-RPC
URL/username/password. Test both connections, then assign `usenet.downloads` to the
WhatsApp agent. Search up to 10 results by category, choose a result to download,
and inspect queue, progress and history. Download, pause and resume require explicit
confirmation. See [Usenet skill](docs/usenet.md).

## Webhooks de aplicaciones

Artemis puede recibir eventos de Seerr y otras apps de la red Docker.
Configura `ARTEMIS_WEBHOOK_TOKEN` y consulta [la guía](docs/webhooks.md).
Los eventos se conservan en PostgreSQL y aparecen en **Herramientas → Webhooks**.

## Tools compartidos

**Herramientas → Notificaciones** permite configurar WhatsApp, enviar avisos directamente
y consultar el historial. Los skills y los webhooks utilizan el mismo servicio.
Consulta [el contrato del tool](docs/notifications.md).

**Herramientas → Recordatorios** permite programar mensajes por fecha/hora o por una condición
sobre el resultado de un tool, con frecuencia de revisión configurable.
Consulta [la guía de recordatorios](docs/reminders.md).

## Panel personal

La interfaz y los mensajes de Artemis están en español. El inicio muestra actividad,
recordatorios y conexiones reales. La navegación incluye Inicio, Agentes, Habilidades,
Herramientas, Canales y Ajustes; las pantallas Runs y Approvals se han retirado.

Usa **Ctrl+K** (o **⌘+K**) para encontrar una sección o herramienta. En Ajustes puedes
elegir tema claro u oscuro, reducir las animaciones y cambiar la densidad. Estas
preferencias se guardan en el navegador. Las animaciones también respetan la
preferencia de movimiento reducido del sistema. El diseño se adapta a móvil.

El panel usa fondo blanco de forma predeterminada y la fuente Atkinson Hyperlegible,
servida localmente. Su licencia OFL se incluye en `frontend/public/fonts/atkinson-hyperlegible/OFL.txt`.

## Codex por WhatsApp

La habilidad **Codex** permite hacer preguntas y pedir herramientas nuevas desde WhatsApp.
Las respuestas llegan al chat de origen y aparecen en **Habilidades → Codex**.
Puede buscar, ejecutar comandos y modificar archivos del proyecto real con permisos de root,
sin confirmación adicional, igual que Antigravity. Consulta [la instalación y los comandos](docs/codex.md).

Google Antigravity: [uso, permisos e instalación](docs/antigravity.md).

### Canal Telegram

Puedes conectar un bot de Telegram con las habilidades existentes. Consulta la [configuración de Telegram](docs/telegram.md).

### Configuración cifrada con AWS KMS

Consulta [AWS KMS y recarga de canales](docs/aws-kms.md) para proteger los secretos guardados en PostgreSQL y administrar WhatsApp y Telegram sin reiniciar Docker.
