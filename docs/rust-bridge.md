# Bridge conversacional en Rust

WhatsApp y Telegram normalizan los mensajes y aplican los comandos explícitos en la API.
La conversación natural pasa por una cola en PostgreSQL. La API conserva las autorizaciones,
la ejecución de habilidades y los adaptadores de canal. El servicio Rust ejecuta los
proveedores CLI, valida sus decisiones y hace la conmutación en el orden de cada bot.

En **Agentes → Proveedores de conversación**, el primer proveedor es el preferido.
Los siguientes se prueban ante errores, respuestas inválidas o vencimientos del plazo.
Codex es el inicial para conservar la selección anterior de Artemis. Se puede elegir AGY
como preferido o guardar una lista vacía para usar solo comandos. El panel muestra el
estado observado de cada adaptador y el proveedor del último turno. Un CLI instalado
queda sin verificar hasta su primera respuesta válida.

Al agotarse los proveedores, el bot muestra el aviso de modo básico y la ayuda sigue
disponible. Escribe `ayuda`, `estado`, `utiliza HABILIDAD` y los comandos de la habilidad
activa. Con `salir` se vuelve a la conversación general. Las tareas avanzadas de Codex y
Antigravity conservan sus workers y sus puntos de entrada explícitos.

## Habilitar en Compose

1. Crea los directorios de adaptadores y estado. Los adaptadores y binarios deben
   estar instalados por el operador y ser legibles y ejecutables para el UID 10001.
   El directorio de estado dedicado debe ser escribible para ese UID y contener
   subdirectorios privados `codex` y `agy`. De forma predeterminada se usan
   `/var/lib/artemis-bridge/adapters`, `/var/lib/artemis-bridge/state` y, para el
   binario AGY, `/var/lib/artemis-bridge/agy-bin`. Se pueden configurar con
   `ARTEMIS_BRIDGE_ADAPTERS_DIR`, `ARTEMIS_BRIDGE_STATE_DIR` y
   `ARTEMIS_BRIDGE_AGY_BIN_DIR`. Codex usa el binario de
   `/usr/local/lib/artemis-codex/bin` o el de `ARTEMIS_BRIDGE_CODEX_BIN_DIR`.
2. Autentica las cuentas conversacionales en sus directorios dedicados. Para una
   instalación de Codex que admita autenticación por dispositivo, usa
   `docker compose run --rm --no-deps -e CODEX_HOME=/state/codex --entrypoint /cli/codex/codex artemis-bridge login --device-auth`.
   Para AGY, la imagen ejecuta el binario `/cli/agy/agy` con `HOME=/state/agy`.
   Usa el flujo de autenticación de la versión instalada. Los workers de desarrollo
   mantienen sus propias credenciales, estado y permisos.
3. Inicia y verifica el servicio con
   `docker compose up -d --build --wait artemis-bridge`. Configura
   `ARTEMIS_BRIDGE_URL=http://artemis-bridge:8091` en el entorno activo y recrea
   API y web. Verifica el primer turno de cada bot y su proveedor en la UI antes
   de considerar activada la migración.

Con la URL vacía, los bots siguen usando el worker de conversación anterior. Los trabajos
anteriores en archivos mantienen sus mecanismos de ejecución y entrega mientras se vacía
la cola. El servicio Rust carece de acceso a la red de PostgreSQL y a los directorios del
proyecto. Su puerto HTTP se comparte con la API por la red interna de Compose.

## Adaptador CLI adicional

Instala un ejecutable sin extensión en el directorio de adaptadores y regístralo desde
la UI. El nombre admite letras minúsculas ASCII, números y guiones, comienza con una
letra y tiene un máximo de 32 caracteres. El proceso recibe una línea JSON por entrada
estándar con la clave `prompt` y devuelve por salida estándar un objeto JSON con
`reply`, `capability` y `command`, los tres de tipo texto. Usa el código de salida
distinto de cero para un fallo y envía diagnósticos por stderr. El bridge aplica un
plazo de 50 segundos por proveedor y un límite de 64 KiB a la salida.

Los adaptadores son código de confianza instalado por el operador. Comparten el
contenedor, la red de salida y el volumen de credenciales del bridge. El panel
registra únicamente ejecutables que el servicio ya puede descubrir.

## Recuperación

Cada turno conversacional tiene un ID estable. PostgreSQL reclama el turno por
un plazo y serializa los pendientes por bot y conversación. Antes de ejecutar una
habilidad registra su inicio. El resultado guardado se reutiliza cuando otro LLM
retoma el turno. Si el proceso cae durante la habilidad y el resultado no llegó a
guardarse, el bot solicita verificar la operación y evita repetirla automáticamente.

La respuesta y el envío pendiente se guardan de forma atómica. La entrega confirma
cada fragmento por separado. Si el canal acepta el envío y se pierde la confirmación
antes de guardarla en PostgreSQL, el fragmento puede aparecer dos veces. WhatsApp
y Telegram no se invocan de nuevo al cambiar de proveedor.

## Prueba de integración

Ejecuta la imagen del bridge con `bridge/tests/adapters` montado en
`/providers:ro` y un puerto de prueba local. Ejecuta
`backend/tests/test_rust_bridge.py` con `ARTEMIS_BRIDGE_TEST_URL` apuntando a esa
instancia y `ARTEMIS_BRIDGE_TEST_DSN` a un PostgreSQL desechable. Los adaptadores
simulan un proveedor que falla tras ejecutar una habilidad, un respaldo que
utiliza el resultado guardado y la caída de todos los proveedores.
