#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
  echo 'Ejecuta este instalador como root.' >&2
  exit 1
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
codex_binary=$(command -v codex)
codex_auth=${CODEX_HOME:-/root/.codex}/auth.json
test -f "$codex_auth"
if ! getent group artemis-codex >/dev/null; then groupadd --gid 10002 artemis-codex; fi
if ! id artemis-codex >/dev/null 2>&1; then
  useradd --system --uid 10002 --gid artemis-codex --home-dir /var/lib/artemis-codex --shell /usr/sbin/nologin artemis-codex
fi
install -d -o artemis-codex -g artemis-codex -m 750 /var/lib/artemis-codex
install -d -o artemis-codex -g artemis-codex -m 700 /var/lib/artemis-codex/codex /var/lib/artemis-codex/workspaces
install -d -o 10001 -g artemis-codex -m 2770 /var/lib/artemis-codex/queue
install -d -m 755 /usr/local/lib/artemis-codex/bin
codex_bin_dir=$(dirname -- "$(readlink -f -- "$codex_binary")")
for executable in codex codex-code-mode-host codex-exec-server; do
  if [[ -f "$codex_bin_dir/$executable" ]]; then
    install -m 755 "$codex_bin_dir/$executable" "/usr/local/lib/artemis-codex/bin/$executable"
  fi
done
if command -v rg >/dev/null; then
  install -m 755 "$(command -v rg)" /usr/local/lib/artemis-codex/bin/rg
fi
if [[ ! -f /var/lib/artemis-codex/codex/auth.json ]]; then
  install -o artemis-codex -g artemis-codex -m 600 "$codex_auth" /var/lib/artemis-codex/codex/auth.json
fi
install -d -m 755 /usr/local/lib/artemis-codex
install -m 644 "$project_dir/scripts/codex_worker.py" /usr/local/lib/artemis-codex/worker.py
sed "s|/docker/artemis_platform|$project_dir|g" "$project_dir/scripts/artemis-codex.service" > /etc/systemd/system/artemis-codex.service
systemctl daemon-reload
systemctl enable --now artemis-codex.service
echo 'Servicio artemis-codex habilitado.'
