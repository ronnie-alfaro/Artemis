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

## Consultar títulos pendientes

Escribe `ver títulos pendientes` (o `solicitudes pendientes`). La consulta es de
solo lectura y muestra hasta 10 solicitudes por página, con título, año, tipo,
estado e ID. Incluye solicitudes pendientes de aprobación y aprobadas cuyo
contenido aún no está disponible por completo; no incluye rechazadas ni fallidas.
Continúa con `ver títulos pendientes página 2`. No modifica selecciones ni
aprobaciones locales. La visibilidad depende de los permisos de la clave de Seerr.

Se usa `GET /api/v1/request?filter=unavailable`, según las
[rutas oficiales de Seerr](https://github.com/seerr-team/seerr/blob/develop/server/routes/request.ts),
y los detalles de cada película o serie para obtener su título.

## Estado de una solicitud

Escribe `estado solicitud 42` o `estado de la petición 42`. Muestra el estado de
aprobación (pendiente, aprobada o rechazada) y, si Seerr lo devuelve, la
disponibilidad del contenido (pendiente, en proceso, parcial, disponible, etc.).
Consultar no modifica selecciones ni aprobaciones locales.

## Acceso general a la API

La misma habilidad `seerr.media` admite `seerr api MÉTODO /api/v1/ruta [JSON]`.
Soporta GET, POST, PUT, PATCH y DELETE, parámetros en la URL y cuerpos JSON.
Ejemplos:

- `seerr api GET /api/v1/request?filter=pending&take=10&skip=0`
- `seerr api GET /api/v1/request/count`
- `seerr api GET /api/v1/request/42`
- `seerr api POST /api/v1/request/42/approve`
- `seerr api POST /api/v1/request/42/decline`
- `seerr api PUT /api/v1/request/42 {"mediaType":"tv","seasons":[1,2]}`
- `seerr api DELETE /api/v1/request/42`

GET consulta directamente. Los demás métodos preparan una aprobación con método,
ruta y cuerpo; requieren `confirmo` o aprobación desde el control plane. Usa
`cancelar` para rechazarla. Las aprobaciones expiran y no se pueden reutilizar.
Los fallos se registran sin reintentar automáticamente una mutación.

El acceso queda limitado al servidor configurado y a `/api/v1/`. Se rechazan URLs
externas y rutas con traversal. Las respuestas JSON ocultan campos de claves,
tokens y contraseñas, también dentro de listas y objetos. No introduzcas secretos
en comandos: sus parámetros se conservan en el registro de aprobación.
No se admiten subidas multipart ni descargas binarias desde el chat. Usa la
paginación del endpoint para respuestas grandes. Seerr decide los permisos de
cada endpoint según la clave configurada; esta ampliación no eleva sus permisos.

Referencia oficial: https://docs.seerr.dev/api/seerr-api/
Filtros: https://docs.seerr.dev/api/get-all-requests/
Aprobación/rechazo: https://docs.seerr.dev/api/update-a-requests-status/
