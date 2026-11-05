# Antigravity desde Artemis

La habilidad utiliza `/root/.local/bin/agy` y la sesión ya autenticada del servidor.
Tiene cola, contexto reciente por conversación, estado y respuestas al WhatsApp de origen.
Actívala en Agentes y escribe `utiliza antigravity`, seguido de la tarea. Usa `estado`,
`resultado <ID>`, `ayuda` y `salir`. El panel Habilidades → Antigravity muestra sus resultados.

El trabajador ejecuta `agy --print --mode auto --dangerously-skip-permissions` sobre
`/docker/artemis_platform`, con red, comandos y escritura en el sistema de archivos
según los permisos de root. Los cambios son directos y no se generan parches.
Las tareas solicitadas no requieren una segunda confirmación. Asigna esta habilidad
únicamente a conversaciones autorizadas para operar el servidor.

Instala y activa desde el host:

```bash
sudo bash scripts/install-antigravity-worker.sh
docker compose up -d --build artemis-api artemis-web
systemctl status artemis-antigravity
```

La API solo monta la cola, nunca la autenticación de agy. El trabajador se ejecuta como
root para utilizar la sesión existente. Su grupo 10002 permite compartir la cola con
Compose. El servicio tiene acceso real al host; no aplica el aislamiento de Codex.
Los trabajos se ejecutan secuencialmente, con hasta diez pendientes. Un trabajo
interrumpido no se repite automáticamente; puede haber cambios parciales que revisar.

Variables del trabajador: `ARTEMIS_ANTIGRAVITY_STATE`, `ARTEMIS_ANTIGRAVITY_CLI`,
`ARTEMIS_ANTIGRAVITY_TIMEOUT` (900 segundos) y `ARTEMIS_SOURCE`. Si cambias el estado,
ajusta también `ARTEMIS_ANTIGRAVITY_STATE_DIR` de Compose y la unidad systemd.
No uses `--continue`: cada petición recibe solo el contexto de su propia conversación.
