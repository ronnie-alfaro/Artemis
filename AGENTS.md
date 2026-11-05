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
No fuerces el push, no despliegues y no cambies de rama automáticamente.
Si falla una prueba, autenticación o push, explica el bloqueo sin afirmar éxito.
No imprimas tokens ni los guardes en URLs o configuración Git.
