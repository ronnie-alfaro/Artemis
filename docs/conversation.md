# Conversación natural y PERSONA

Para el enrutamiento configurable, la conmutación y el modo básico, consulta el
[bridge conversacional en Rust](rust-bridge.md). Esta página describe la cola heredada.

Los bots de WhatsApp y Telegram usan AGY por defecto. El usuario puede preguntar, pedir ayuda con Artemis o solicitar una acción sin activar una habilidad. AGY recibe únicamente el catálogo asignado a ese bot y traduce la petición a un comando del agente correspondiente. El servidor vuelve a comprobar la asignación antes de ejecutarlo y entrega el resultado a AGY para que lo explique con naturalidad.

## Configurar el bot

En **Agentes → WhatsApp/Telegram → PERSONA** define personalidad, tono y comportamiento. Por ejemplo:

> Eres Artemis, cercana, ingeniosa y directa. Responde en español, brevemente, y amplía cuando te lo pidan. Ayuda a usar la aplicación y pregunta cuando la petición sea ambigua. Usa humor ocasional sin ocultar errores.

Guarda la PERSONA. Se aplica desde el siguiente mensaje, sin reiniciar el canal. Cada identidad de bot tiene su perfil independiente en PostgreSQL; Telegram y WhatsApp no comparten personalidad ni conversaciones. Los trabajos ya en cola mantienen la PERSONA con la que fueron recibidos.

Las habilidades asignadas determinan qué puede usar el asistente. No hace falta asignar `antigravity.assistant` para conversar: AGY es el motor por defecto. Esa habilidad opcional conserva la función avanzada de desarrollo del proyecto y sus permisos existentes. El saludo configurado se ofrece a AGY como sugerencia, sin repetirlo en cada turno.

Ejemplos de mensajes:

- «¿Qué puedes hacer y cómo agrego un recordatorio?»
- «¿Me buscas Matrix para descargar?»
- «Busca en mis enlaces lo que guardé sobre Docker».
- «Prefiero la segunda opción».
- «Sí, dale» para confirmar una operación que el bot acaba de proponer.

## Ejecución

1. El canal carga PERSONA y habilidades y crea un trabajo conversacional persistente.
2. El trabajador AGY produce una respuesta o una solicitud estructurada de habilidad.
3. El puente de la API comprueba bot, conversación, asignaciones actuales y confirmaciones.
4. Ejecuta el agente por el orquestador existente, sin activar sesiones manuales.
5. AGY recibe el resultado y puede responder o solicitar otra acción, hasta un máximo de cuatro por mensaje.
6. La respuesta final vuelve al chat de origen, sin encabezados de proveedor, IDs de trabajo ni recibos automáticos de cola.

Se mantiene el historial reciente de la propia conversación. Los trabajos posteriores de una conversación esperan a que termine el anterior para poder usar su contexto. No se utiliza `--continue` ni una sesión global compartida de AGY.

La conversación usa un directorio separado del repositorio, `--sandbox` y reglas de permisos que deniegan las herramientas locales. No utiliza `--dangerously-skip-permissions`. El acceso a las habilidades ocurre en el servidor; los tokens de servicios no se envían al modelo. Una PERSONA no amplía las habilidades ni autoriza operaciones. Las confirmaciones continúan siendo decisiones del usuario: el modelo solo puede traducir una afirmación explícita para una aprobación que ya existía cuando llegó ese mensaje.

La API exige el marcador de protocolo `conversation-v1` actualizado por el trabajador. Un trabajador antiguo no recibe trabajos conversacionales con sus permisos de desarrollo. Si AGY está desconectado o la cola está llena, el bot informa que no puede responder en ese momento.

## Actualizar el trabajador

Después de actualizar el código, instala el nuevo helper junto al trabajador y reinicia el servicio cuando no tenga tareas en marcha:

```sh
sudo bash scripts/install-antigravity-worker.sh
sudo systemctl restart artemis-antigravity
```

La API y la web también necesitan la nueva imagen una vez. Las modificaciones posteriores de PERSONA y asignaciones no requieren reinicios.

## Límites actuales

- El trabajador procesa una tarea AGY a la vez y admite diez pendientes compartidas con sus tareas avanzadas.
- Puede necesitar varias respuestas del modelo para completar una petición; no garantiza respuesta inmediata.
- Los estados de selección de ciertos agentes siguen siendo locales al proceso. Tras reiniciar la API puede hacer falta repetir una búsqueda.
- Un fallo después de ejecutar una habilidad y antes de guardar su resultado puede provocar un reintento. Se conservan los mecanismos existentes de aprobaciones e idempotencia; no se garantiza ejecución exactamente una vez para toda habilidad.
- Los comandos de sincronización e iteración mantienen su comportamiento previo y sus permisos de Codex.
- Los clientes REST y los agentes invocados con capacidades explícitas conservan el enrutamiento anterior. El modo natural se activa en los adaptadores de los bots.

## Memoria automática de Cerebro

La API registra las interacciones nuevas en `agent_memory`, con agente, canal,
conversación y fecha. Conserva el mensaje y la respuesta inmediata, o indica que
la respuesta está pendiente. Los resultados definitivos de Codex y Antigravity
se añaden como eventos separados, con su estado real, incluso si fallaron.
No se importan trabajos anteriores a la primera activación del mecanismo.

Una cola en el volumen `ARTEMIS_MEMORY_DIR/pending-interactions` conserva las
interacciones pendientes de embeddings. Un trabajador revisa la cola cada cinco
segundos, fuera del procesamiento del mensaje, y reintenta si Chroma falla.
Los identificadores estables evitan duplicados tras reinicios o reintentos.
Las invocaciones internas con capacidades explícitas no generan interacciones
artificiales. Los textos se limitan a 7500 caracteres por participante.
Los fallos de escritura de la propia cola se avisan en logs sin contenido privado;
si el volumen no permite escribir, esa interacción no queda garantizada.

El registro no añade recuperación automática al contexto del modelo ni cambia las
aprobaciones de `memory.remember`. No sustituye una política de retención: los
recuerdos se conservan hasta su eliminación explícita. Requiere actualizar la
imagen de API para activarse; reiniciar una imagen antigua no aplica el código.
