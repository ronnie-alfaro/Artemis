# Optional Seerr integration

Seerr is an optional Artemis business tool, not a `WhatsApp -> Seerr` flow. Any channel adapter submits a conversation; capability policy decides whether the registered `seerr.media` agent can use it.

For the Seerr deployment in `/docker/seerr`, Artemis API joins the existing
`seerr_default` Docker network. Start Seerr before Artemis so that this external
network exists. The web and PostgreSQL containers do not join this network.

In **Skills → Seerr media requests**, set the base URL to `http://seerr:5055`
and enter the API key from Seerr settings, then test the connection. Alternatively,
set `SEERR_BASE_URL=http://seerr:5055` and `SEERR_API_KEY` in the deployment
environment. Both environment values are required for environment configuration.
Do not commit credentials.

Traffic goes directly from Artemis API to Seerr using Docker DNS and the container
port. It does not use the host's published port or `localhost`. If the Seerr
Compose project name changes, update the external network name in Artemis Compose.

The client uses `X-Api-Key`: `/api/v1/search`, typed movie/TV detail paths, `/api/v1/request`, and `/api/v1/request/{id}`. Ambiguous results display title, year, type and TMDB ID. A selected title creates an expiring `WRITE` approval that includes requester and default profile; the initial agent requests TV as a full series and does not claim granular seasons. Replayed selection is deduplicated; a Seerr 409 is a safe duplicate error rather than a blind retry.

## Smoke test (not run)

Deploy a disposable Seerr outside this Compose file, use a least-privilege request API key, and establish the private network/egress path. Configure it in **Skills → Seerr media requests**, test the connection, bind the skill to the WhatsApp agent, request a known test title, inspect and approve its operation once, then compare returned ID/status in Seerr. Replay the confirmation and verify no second request. Revoke the key and verify the safe unauthorized response. Automated coverage uses controlled HTTP test doubles; it is not evidence of a live connection.

## Eventos de Seerr hacia Artemis

Para recibir solicitudes disponibles y otros cambios en **Tools → Webhooks**,
consulta [Eventos por webhook](webhooks.md).
