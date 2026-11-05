# Usenet skill

Configure **Skills → Usenet** with the NZBPlanet provider URL and API key, and the
NZBGet XML-RPC URL, username and password. The URL supplied for this deployment is
pre-filled. Use the provider's API endpoint (a bare host automatically uses `/api`).
Save both connections, then test them. The search test makes a small authenticated
`search` request; the download manager test reads `status` without changing the queue.
Each connection reports its own test result. No live authenticated verification is
claimed until credentials have been supplied and both tests succeed.

All configuration, including the two secrets, is encrypted in PostgreSQL with
`ARTEMIS_CONFIG_ENCRYPTION_KEY`. Configuration responses never return secrets. On
subsequent saves, empty secret fields preserve existing credentials.

Assign **Buscar y gestionar descargas · Usenet** in **Agents** and save the binding.
The channel help automatically includes all commands for this skill:

- `busca Rocky en movies`: up to 10 results from the provider. Categories: películas /
  movies (2000), series / TV (5000), música (3000), libros (7000), juegos (1000),
  software (4000), or a four-digit category ID. No category searches all categories.
- `detalles 2` / `detalles del 2`: title, size, category and date from the provider.
- `baja el 2`: prepare the selected result; `confirmo` starts it, `cancelar` rejects it.
- `qué bajo` / `qué está bajando`: queue and progress from the download manager.
- `estado de descarga`: pause state, speed, remaining size and free disk space.
- `historial de descargas`: latest 10 completed, failed or deleted downloads.
- `pausa las descargas` / `reanuda las descargas`: propose a global download pause
  or resume; these also require `confirmo`.

Search results are isolated per conversation and expire after 15 minutes. Selection
numbers always refer to that conversation's last successful search, not a new search
with potentially different ordering. Pending approvals persist across restarts and
contain the selected provider ID and title, without credentials. Approvals expire in
5 minutes. A new proposal replaces other pending proposals of this skill.
Changing the connection clears search choices and rejects pending proposals, so a
result from the previous provider cannot be sent using the new connection.

After approval, Artemis requests `t=get` using the selected ID, validates the NZB,
and transfers it to NZBGet's `append` as Base64 content. The temporary file lives only
in memory (bounded to 12 MiB). Provider download URLs and API keys are never sent to
NZBGet. Appends use a stable duplicate key and are not automatically retried; on a
timeout, check queue/history before trying again. A returned queue ID means accepted,
not completed. Normal NZBGet category processing remains at its configured default.

Provider API errors in XML (even HTTP 200), credential errors, quotas, malformed
responses and RPC faults produce safe messages without raw response bodies. Search
and download operations use the configured endpoints rather than links from RSS items.
RSS/XML parsing disables external entities.

NZBPlanet integration follows the API specification supplied for this deployment.
NZBGet RPC methods follow the [official API](https://nzbget.com/documentation/api/).
