# Context Builder

El turno se crea en `ConversationAgent.run`. PostgreSQL recibe la PERSONA del bot,
el catálogo asignado en ese instante y los identificadores de las aprobaciones
pendientes. Antes del cambio, `RustBridge._model` concatenaba instrucciones con
un JSON que contenía esa PERSONA completa, hasta ocho turnos y todas las habilidades
aún asignadas. El bridge pasaba el mismo prompt a cada CLI. La página
`conversation.md` describe el trabajador AGY heredado, no este flujo.

La API prepara un paquete de entrada versionado para el bridge mediante HTTPS o
la red privada de Compose. El bridge construye el paquete efectivo para cada
intento con la configuración de ese proveedor. Los adaptadores siguen recibiendo
`{"prompt": "..."}`. El simulador usa la misma función Rust sin invocar adaptadores.
Los datos persistentes se leen exclusivamente desde la API. El checkpoint de
operaciones y la revalidación de capacidades y aprobaciones siguen en Python.

## Activación y configuración

La optimización está desactivada por defecto. Para habilitar el panel configura
`ARTEMIS_ADMIN_TOKEN` en la API o localmente mediante el entorno de Compose.
Configura `ARTEMIS_CONTEXT_TOKEN` con un secreto aleatorio de al menos 32
caracteres en ambos servicios. Compose entrega ese valor a la API y al bridge.
El bridge debe ejecutarse en la red privada o recibir el tráfico por HTTPS.
Los servicios de almacenamiento y los adaptadores CLI no reciben este secreto.

En **Context Builder**, selecciona Global, el bot de WhatsApp o Telegram o el
proveedor. PostgreSQL aplica valores predeterminados, globales, del bot y del
proveedor en ese orden. Las reglas protegidas se validan después de combinar
los ámbitos. Cada guardado crea una revisión, y restaurar crea otra revisión.
Los cambios de configuración se leen al preparar el siguiente turno del bridge.
El optimizador solo actúa sobre el flujo conversacional Rust. El worker AGY
heredado y los workers explícitos de desarrollo mantienen sus contratos.

## Identidad y aislamiento

El texto de **Agentes → PERSONA** sigue siendo la fuente canónica de Extended en
PostgreSQL. Al guardar en el editor del Context Builder, Chroma aloja una copia
inalterada del original y las versiones Core y Extended en `agent_persona`. El
perfil usa el identificador `canal:bot`, con IDs de documento deterministas por
versión y tipo. El digest de la versión Extended activa debe coincidir con el
texto vigente de PostgreSQL para admitir el Core correspondiente. Modificar
PERSONA en Agentes invalida un Core que pertenecía al texto anterior. La API
propone un nuevo Core extractivo hasta que se revise y guarde. La propuesta
prioriza la primera frase de identidad y las frases completas que caben.
Cuando Chroma falla se parte únicamente de la PERSONA del bot de ese turno.

Los recuerdos nuevos incluyen canal y conversación. El filtro de Chroma exige
agente, canal y UUID de conversación antes de puntuar la similitud. Los recuerdos
antiguos que carecen de ámbito se siguen mostrando en Cerebro. El motor omite
esos recuerdos de las solicitudes a proveedores. Los recuerdos recuperados y los
resultados se etiquetan como datos. Un filtro elimina patrones frecuentes de
credenciales de la entrada optimizada. Las listas de aprobación y los resultados
del turno vienen del checkpoint de la API. El filtro del bridge no concede
permisos y la API vuelve a validar las decisiones.

## Simulación, presupuestos y métricas

El simulador prepara candidatos con la misma política de recuperación y usa
`POST /v1/context/preview`, protegido por el secreto del bridge. No crea turnos,
aprobaciones ni resúmenes persistentes. En runtime, `POST /v1/context/decide`
devuelve las métricas de cada intento. Durante el failover Rust usa la variante
del siguiente proveedor y la API mantiene el mismo turno y sus observaciones.
Una política puede recuperar el modo heredado cuando el endpoint no está
disponible o el contenido obligatorio no cabe.

Los resúmenes incrementales son extractivos y de tamaño acotado. Conservan
citas útiles de ambas partes y referencias verificables. Las operaciones
pendientes permanecen en el registro de aprobaciones y en el turno, fuera del
resumen. El selector de capacidades compara intención con los metadatos de
cada capacidad que el backend autoriza, incluidas las consultas registradas de
Curiosidad. Da prioridad a los contratos asociados con una aprobación real.
La caché local es acotada y compara ámbito, proveedor y entrada completa; por
ejemplo, un cambio en una habilitación o en el historial impide el acierto. El
orden del prompt favorece los prefijos estables. El acierto de caché local
mide trabajo de ensamblado evitado.

El estimador usa un factor de bytes por token configurable por proveedor. Las
reservas se restan del presupuesto de entrada antes de seleccionar contenido.
Los tokens reales solo aparecen si el adaptador los reporta. Codex usa eventos
JSONL de fin de turno; AGY y adaptadores personalizados pueden suministrar el
objeto opcional `usage` junto con `decision`. Los costes configurados se
estiman a partir de los conteos reportados. Los ahorros del simulador comparan
estimaciones para la misma entrada. Esas cifras cambian según la conversación
y el proveedor y requieren calibración antes de una activación global.

## Evaluación inicial

El programa `scripts/evaluate_context_builder.py` compara los mismos mensajes
sintéticos en los modos heredado y optimizado. Usa un puerto local del bridge o
HTTPS y toma el secreto del entorno. Por defecto solo genera estimaciones.
`--live` invoca ambos modos en el proveedor seleccionado sin asignar capacidades
ni crear turnos de WhatsApp o Telegram.

En el conjunto sintético inicial, el recuento estimado del prompt pasó de 872 a
225 en la consulta técnica, de 1.862 a 859 en continuidad y de 1.858 a 855 en
identidad. Los datos preparados incluían una PERSONA Extended deliberadamente
larga. Estas tres muestras estimadas no representan el consumo del modelo.

En una prueba real de continuidad, AGY reportó 9.093 tokens de entrada en el
modo heredado y 8.237 en el optimizado, una reducción del 9,4 %. Reportó 28
tokens de salida en cada caso y devolvió la misma referencia solicitada.
La latencia observada fue de 9,3 y 4,7 segundos, respectivamente. Es una sola
pareja, sin conclusión sobre latencias habituales. El CLI de Codex no llegó a invocar el modelo porque el bridge no tenía el
directorio de sesión `/state/codex`. El adaptador anterior tiene el mismo
requisito. Queda pendiente ampliar la evaluación de
calidad y consumo real de ambos proveedores antes de habilitar la optimización
para todos los agentes.
