#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test -x /root/.local/bin/agy
getent group artemis-codex >/dev/null || groupadd --gid 10002 artemis-codex
if [ "$(getent group artemis-codex | cut -d: -f3)" != 10002 ]; then
  echo 'El grupo artemis-codex debe tener GID 10002 para compartir la cola con Compose.' >&2
  exit 1
fi
install -d -m 0770 -o root -g artemis-codex /var/lib/artemis-antigravity /var/lib/artemis-antigravity/queue
install -d -m 0755 /usr/local/lib/artemis-antigravity
install -m 0644 "$project_dir/scripts/antigravity_worker.py" "$project_dir/scripts/codex_worker.py" /usr/local/lib/artemis-antigravity/
install -m 0644 "$project_dir/scripts/artemis-antigravity.service" /etc/systemd/system/artemis-antigravity.service
systemctl daemon-reload
systemctl enable --now artemis-antigravity
