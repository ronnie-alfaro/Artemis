# Codex desde WhatsApp

La habilidad Codex utiliza la sesión autenticada del servidor y una cola persistente.
Asigna `codex.assistant` en Agentes y escribe `utiliza codex`, seguido de la tarea.
Puedes preguntar, buscar, revisar, pedir modificaciones o crear herramientas.
Usa `estado`, `resultado <ID>`, `ayuda` y `salir`.
Las respuestas regresan a la conversación de origen y aparecen en Habilidades → Codex.
Cada conversación conserva seis intercambios recientes de contexto independiente.

Codex ejecuta todas las peticiones sobre `/docker/artemis_platform` con
`-s danger-full-access` y `approval_policy="never"`. El trabajador corre como root,
con acceso al sistema de archivos, red y comandos del host, igual que Antigravity.
Los cambios se aplican directamente y no requieren confirmación adicional.
Las nuevas peticiones no generan parches; los parches históricos siguen descargables.
Asigna la habilidad a conversaciones autorizadas para operar el servidor.

## Instalación y actualización

```bash
sudo bash scripts/install-codex-worker.sh
sudo systemctl restart artemis-codex
docker compose up -d --build artemis-api artemis-web
```

El instalador copia el CLI local y conserva la autenticación existente del trabajador en
`/var/lib/artemis-codex/codex`. La API monta únicamente la cola, nunca los tokens.
El grupo 10002 permite compartir la cola con Compose. Ya no se requiere bubblewrap.
El servicio no aplica aislamiento de lectura ni protección del hogar del propietario.

Variables: `ARTEMIS_CODEX_STATE`, `ARTEMIS_CODEX_CLI`, `ARTEMIS_SOURCE` y
`ARTEMIS_CODEX_TIMEOUT` (900 segundos). El montaje de Compose se controla con
`ARTEMIS_CODEX_STATE_DIR`; cualquier cambio debe coincidir con el servicio.

Hasta diez trabajos pendientes, ejecutados secuencialmente. Un trabajo interrumpido
no se repite automáticamente y puede haber cambios parciales que revisar antes de
volver a enviarlo. Las entregas a WhatsApp conservan el progreso por fragmento.

Las herramientas compartidas `codex.ask` y `codex.create_tool` conservan sus contratos:
`prompt`, `message_id`, `conversation_id` y `channel`; devuelven ID y estado del trabajo.
Ambas permiten ejecutar tareas con escritura en el proyecto real.

## Comando global oculto de iteración

`iteracion`, `iteración` y `/iteracion` invocan una revisión acotada del propio
proyecto. También se admite esta invocación completa, sin distinguir mayúsculas o
acentos:

> Artemis, desciende a los sótanos de tu propia conciencia digital, disecciona tu
> código, redime uno de tus pecados de programación y procura no convertir una
> pequeña mejora en Crimen y castigo.

El comando funciona desde el modo general o cualquier habilidad activa y conserva
esa selección y sus operaciones pendientes. Requiere que `codex.assistant` esté
asignado a la conversación y que el trabajador esté conectado. No se anuncia en
el saludo, la ayuda, los menús de reacciones ni como una habilidad adicional.

Al aceptar la tarea, Artemis devuelve el monólogo de Sócrates definido en
`app/application/iteration.py`. Codex recibe una instrucción independiente para
examinar el repositorio, elegir un único problema pequeño, corregirlo directamente
y ejecutar las comprobaciones pertinentes, respetando los cambios existentes.
Debe comprobar, crear el commit propio, sincronizar y desplegar conforme a `AGENTS.md`,
sin encadenar nuevas iteraciones.
Si no hay una mejora pequeña segura, debe explicar el resultado sin forzar cambios.
El informe vuelve al chat original mediante la entrega normal de Codex; los
archivos corregidos se despliegan automáticamente tras superar las comprobaciones. Si Codex no está conectado
o la cola está llena, se informa del error sin afirmar que la tarea ha comenzado.
Los reintentos del mismo mensaje reutilizan el trabajo existente.

## Cierre automático de tareas

Cada tarea completada incluye reconstrucción y recreación de `artemis-api` y
`artemis-web`, incluso sin cambios, salvo prohibición explícita del usuario.
Se conserva el entorno Compose activo, PostgreSQL y los volúmenes. Antes de
publicar cambios deben pasar las comprobaciones y sincronizarse el commit propio.
El agente verifica salud, HTTP y logs y comunica cualquier bloqueo sin afirmar éxito.
La política está en `AGENTS.md` y en las instrucciones del trabajador. Al actualizar
el trabajador instalado, su reinicio debe esperar al cierre del trabajo activo.
