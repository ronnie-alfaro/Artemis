# Function Calling y minions: arquitectura base

## Contratos y límites

`NativeTools` adapta `ToolRegistry` sin comandos de texto. Cada herramienta registra
un modelo Pydantic estricto que genera JSON Schema, una capacidad y el runner
existente. `schemas(context)` produce el catálogo function/tool calling; `execute`
valida argumentos, permisos, activación actual, timeout y confirmación. La primera
migración incluye memory.search, memory.remember y memory.forget. Los agentes de
texto existentes continúan funcionando. No se añade un proveedor LLM ni se cambia
su bucle de conversación en esta entrega.

El contexto se construye en el servidor: identidad autenticada, conversación y
capacidades obtenidas de la configuración vigente del panel. Nunca aceptar estas
propiedades del modelo. El callback `enabled` permite volver a consultar la
configuración al ejecutar, incluso si se desactivó después de generar el catálogo.
La composición inicial exige capacidades explícitas; no interpreta una lista vacía
como permiso universal. El llamador debe renovar el contexto o instalar un resolver
de configuración para reflejar cambios del panel en tareas encoladas.

## Confirmación

Toda mutación nativa requiere ApprovalStore, aunque el runner legado no la exija.
Flujo: request_approval → panel existente approve/reject → execute con approval_id.
La aprobación queda vinculada a agente, conversación, herramienta y argumentos
normalizados, tiene caducidad y se reclama antes del primer await. Una operación
fallida o interrumpida consume la aprobación; no hay reintentos automáticos.
Las confirmaciones legadas no cambian. Los procesos distribuidos requieren una
reclamación transaccional compartida antes de habilitar múltiples ejecutores.

## Minions efímeros

`MinionDispatcher.submit` devuelve inmediatamente un trabajo con UUID, nombre
mitológico con sufijo aleatorio, mitología, estado, tarea y target. La tarea pública
es el nombre de herramienta: argumentos y resultados quedan fuera de telemetría.
Estados: pending → running → completed/failed/cancelled. Ejecución concurrente con
semáforo, capacidad limitada, plazo total que incluye espera en cola, cancelación
al cerrar y retención acotada. No son agentes autónomos con autoridad adicional.

`LocalExecutor` utiliza el mismo control nativo. `HTTPExecutor` exige destino HTTPS
configurado, autenticación y no sigue redirecciones. `SSHExecutor` usa argv sin
shell local, host configurado, host keys verificadas y comando remoto fijo
`artemis-minion-worker`; intercambia JSON por stdin/stdout. Cancelar SSH termina el
cliente local; no garantiza terminar una operación ya iniciada en el servidor.

Los destinos remotos se inyectan desde configuración confiable, nunca desde el
modelo. Sus adaptadores implementan el transporte, no despliegan workers. El worker
debe autenticar al coordinador, reconstruir permisos desde su configuración,
validar FunctionCall y deduplicar job_id. Las aprobaciones locales no se transfieren:
las mutaciones remotas deben obtener confirmación en el worker o implementar un
protocolo firmado y transaccional. No habilitar workers que omitan este control.

## Integración y telemetría

La aplicación compone native_tools y minions en app.state, con destino local y
contratos de memoria. La API administrativa existente protege estas rutas según
su configuración de autenticación habitual:

- GET /api/v1/tools/contracts: inventario de esquemas, no catálogo autorizado.
- GET /api/v1/minions: historial acotado de trabajos sin payloads.
- GET /api/v1/minions/events?after=N: eventos ordenados y cursores de retención.

La interfaz puede hacer polling y detectar huecos mediante oldest_sequence.
No se añade aún un componente visual ni endpoints públicos de ejecución: el bucle
LLM debe usar schemas/execute y el coordinador debe llamar submit con contexto
fiable. No hay persistencia de trabajos: un reinicio pierde cola e historial; no se
promete entrega exactamente una vez. Para producción distribuida quedan un broker,
leases, persistencia, límites de salida remota y deduplicación duradera. No se han
configurado destinos remotos ni ejecutado comandos en máquinas externas.

Los nombres enviados al proveedor sustituyen puntos por `__` (memory__search),
compatibles con APIs que restringen nombres de funciones. FunctionCall los
normaliza al nombre interno; los argumentos son objetos JSON, no texto shell.
