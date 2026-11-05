# Karakeep skill

Karakeep is an optional self-hosted bookmarking skill. In the Artemis control plane, open **Skills → Karakeep bookmarks**, provide the Karakeep base URL and API key, then use **Test connection**. Artemis encrypts the key in PostgreSQL and never sends it back to the browser.

Generate the API key in Karakeep at **Settings → API Keys**. Karakeep requires `Authorization: Bearer <API_KEY>` for its API. Artemis checks the connection with `GET /api/v1/lists` and saves links through `POST /api/v1/bookmarks` with `type: link`.

After the connection test succeeds, open **Agents**, drag **Save links · Karakeep** to the WhatsApp agent, and save. A WhatsApp user can then write `guarda https://example.com`. Artemis creates an expiring approval that must be confirmed before sending the write to Karakeep.

The bookmark API call is deliberately limited to a supplied HTTP(S) link. Artemis does not scrape, fetch, or store message content as a bookmark.

## Buscar desde WhatsApp

Con `karakeep.bookmarks` asignado al agente puedes escribir:

- `busca docker en mis bookmarks`
- `busca en karakeep recetas`
- `busca python en mis enlaces guardados`

Artemis consulta `GET /api/v1/bookmarks/search` con `q`, `limit=5`,
`sortOrder=relevance` e `includeContent=false`. Devuelve hasta cinco resultados
con título, URL (si es un enlace) y un extracto del resumen o descripción.
Karakeep busca también en el contenido y las notas. No se pide confirmación
para buscar. Un guardado pendiente se conserva al consultar bookmarks.
`ayuda Karakeep` muestra los comandos completos.

API de referencia: https://docs.karakeep.com/api/search-bookmarks/
