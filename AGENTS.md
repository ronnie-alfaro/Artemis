# Sincronización de cambios propios

Después de modificar código de Artemis, ejecuta las comprobaciones pertinentes,
crea un commit con tus cambios y ejecuta `python3 scripts/github_sync.py` para
subir la rama actual a ronnie-alfaro/artemis_whatsapp_3p_platform.
El usuario ha autorizado este flujo y el comando oculto `sincronizate`.
Respeta una prohibición explícita en una petición posterior.

Revisa el estado inicial. Conserva los trabajos anteriores; incluye únicamente
cambios propios, usando selección de hunks o un índice temporal si hay cambios
ajenos en el mismo archivo. Nunca uses `git add .` indiscriminadamente.
No publiques `.env`, tokens, artefactos `._*`, cachés ni registros.
No fuerces el push ni cambies de rama automáticamente.
Si falla una prueba, autenticación o push, explica el bloqueo sin afirmar éxito.
No imprimas tokens ni los guardes en URLs o configuración Git.

# Despliegue automático autorizado

Al terminar cada tarea correctamente, incluso sin cambios de código, despliega y
reinicia API y web sin pedir confirmación. Tras modificar código, primero ejecuta
las comprobaciones pertinentes, crea el commit propio y sincroniza la rama.
Ejecuta desde la raíz, conservando los archivos Compose y el entorno del proyecto
activo (actualmente docker-compose.yml):
`docker compose up -d --build --force-recreate --no-deps --wait --wait-timeout 180 artemis-api artemis-web`.
Comprueba la salud de API, la respuesta HTTP de web y los logs recientes.
No reinicies PostgreSQL ni otros proyectos, no borres volúmenes y no ejecutes down.
Si falla una comprobación, sincronización o despliegue, detente e informa del bloqueo;
no afirmes éxito ni reintentes indefinidamente. Una petición posterior explícita de
no desplegar o no reiniciar tiene prioridad. Informa del despliegue y sus resultados.
Si modificas scripts/codex_worker.py, actualiza también la copia instalada del
trabajador; no reinicies artemis-codex mientras procese el trabajo actual: su
recarga debe esperar a que termine para no interrumpir la respuesta.
