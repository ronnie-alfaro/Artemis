# Optional Seerr integration

Seerr is an optional Artemis business tool, not a `WhatsApp -> Seerr` flow. Any channel adapter submits a conversation; capability policy decides whether the registered `seerr.media` agent can use it.

Set `SEERR_BASE_URL` to an independently deployed HTTPS Seerr instance and inject `SEERR_API_KEY` by a secret manager. Both are required or the plugin is not registered. No real values belong in git.

Current Compose deliberately puts API on `internal` only and does not deploy, expose or verify Seerr. An external Seerr URL is therefore not reachable from the default topology without an explicit reviewed egress path. For a separate container attach both to a dedicated private network; for an external instance use API-only egress with an exact-host firewall/proxy allowlist and TLS validation. Do not put Seerr on `edge`.

The client uses `X-Api-Key`: `/api/v1/search`, typed movie/TV detail paths, `/api/v1/request`, and `/api/v1/request/{id}`. Ambiguous results display title, year, type and TMDB ID. A selected title creates an expiring `WRITE` approval that includes requester and default profile; the initial agent requests TV as a full series and does not claim granular seasons. Replayed selection is deduplicated; a Seerr 409 is a safe duplicate error rather than a blind retry.

## Smoke test (not run)

Deploy a disposable Seerr outside this Compose file, use a least-privilege request API key, and establish the private network/egress path. Configure it in **Skills → Seerr media requests**, test the connection, bind the skill to the WhatsApp agent, request a known test title, inspect and approve its operation once, then compare returned ID/status in Seerr. Replay the confirmation and verify no second request. Revoke the key and verify the safe unauthorized response. Automated coverage uses controlled HTTP test doubles; it is not evidence of a live connection.
