# Production deployment

Artemis is designed to run as one private Compose stack. The web interface is bound to `127.0.0.1` by default; do not publish the API or PostgreSQL ports. For remote operator access, put only the web service behind an authenticated TLS reverse proxy or a private VPN.

## Install on a new machine

Install Docker Engine with the Compose plugin, clone this repository, then create the production environment file:

```bash
cp .env.production.example .env.production
openssl rand -base64 36       # POSTGRES_PASSWORD
openssl rand -base64 32       # ARTEMIS_ADMIN_TOKEN
openssl rand -base64 32 | tr '+/' '-_'  # ARTEMIS_CONFIG_ENCRYPTION_KEY
```

Paste the generated values into `.env.production`, along with the WhatsApp agent token created inside WhatsApp. The encryption key is required to read the locally encrypted Seerr credential after a restart: retain it in the host secret manager or encrypted password vault. Losing or replacing it intentionally makes previously stored Seerr credentials unreadable; configure the skill again in that case.

Start the stack:

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

Open `http://127.0.0.1:8080`, enter `ARTEMIS_ADMIN_TOKEN`, then configure Seerr from **Skills → Seerr media requests**. The key is encrypted in PostgreSQL and is never returned to the browser after saving. Bind `seerr.media` to the WhatsApp agent only after **Test connection** succeeds.

## Verify before use

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/ready
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml logs --tail=100 artemis-api
```

Check the WhatsApp agent status in the authenticated UI. Send a normal greeting first; it must receive the configured status response. Then make one read-only Seerr search and verify that selecting a result produces an approval before any request is created.

## Backup and recovery

Back up PostgreSQL and `.env.production` together. The database contains durable WhatsApp inbox/idempotency state, approval/audit records, and encrypted Seerr credentials; `.env.production` contains the key required to decrypt those credentials.

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml exec -T postgres pg_dump -U artemis artemis > artemis-$(date +%F).sql
```

Test restoration on an isolated host before relying on a backup. Do not copy a production database or `.env.production` into source control.
