# Deployment and CI/CD

`docker compose up` creates an internal-only API and PostgreSQL network, with the Web UI published to loopback by default. Place an authenticated reverse proxy in front of the UI/API when remote access is needed; never publish PostgreSQL. Production should use externally managed secrets, backups, and image tags rather than `latest`.

Pull requests run Python lint/type/tests/Bandit, frontend lint/type/tests/build, Docker builds, CodeQL, Gitleaks, and Trivy. Dependabot proposes dependency updates. A `vX.Y.Z` tag builds and pushes component images to `ghcr.io/<owner>/artemis-backend:vX.Y.Z` and `artemis-frontend:vX.Y.Z`; a homelab deploy pulls explicit tags after its own approval gate.

Recommended `main` protection: required CI/security checks, one review, no unresolved conversations, linear history, and signed commits where organization policy supports it. Automated architecture review should start with these deterministic checks; any optional AI review is advisory and must not gate correctness.
