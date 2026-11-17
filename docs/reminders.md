# Recordatorios

Abre **Tools → Recordatorios**. Cada recordatorio consta de un **mensaje** y un
**disparador**. El aviso se envía una sola vez por el tool compartido de Notificaciones.

## Fecha y hora

Selecciona una fecha futura. La web muestra la zona horaria del navegador y convierte
la fecha a UTC antes de enviarla. La API exige una fecha con zona horaria explícita.
Los recordatorios pendientes se conservan en PostgreSQL: si Artemis estaba detenido
cuando vencieron, el planificador los recupera al arrancar.

## Resultado de un tool

Selecciona un tool de consulta, sus parámetros, un campo del resultado y una condición.
Indica cada cuánto revisarlo, en segundos, minutos u horas. El intervalo admite desde
10 segundos hasta 7 días y se cuenta desde el final de la consulta anterior.

**Probar condición** ejecuta una consulta y muestra el resultado sin crear el recordatorio
ni enviar un aviso. Los tools de escritura no se pueden usar como disparadores.
El planificador vuelve a validar el permiso y el tipo de tool en cada consulta.

Ejemplos:

| Tool | Campo | Condición | Valor |
| --- | --- | --- | --- |
| `usenet.status` | `status.remaining_mb` | Es igual a | `0` |
| `usenet.history` | `items[id=42].status` | Contiene | `SUCCESS` |
| `usenet.queue` | `items` | Está vacío | — |
| `usenet.queue` | `items[id=42]` | Ya no existe | — |

Los resultados JSON que los tools devuelven como texto se convierten a valores antes
de compararlos. Puedes usar campos anidados, índices y comodines:

- `status.paused`: un campo de un objeto.
- `items.0.status`: un elemento por posición.
- `items[*].status` o `items.*.status`: todos los elementos.
- `items[id=42].status`: un elemento cuyo ID numérico sea 42.
- `items[id="42"].status`: un elemento cuyo ID sea el texto "42".
- `$`: el resultado completo.

La condición se cumple cuando coincide al menos un valor seleccionado. Si el campo no
existe, las comparaciones normales no disparan avisos; usa **Ya no existe** si eso es lo
que quieres vigilar. **Existe** incluye campos con valor null. **Está vacío** comprueba
listas, objetos o texto vacíos. Las comparaciones numéricas requieren números.

**Cambia respecto a la revisión anterior** usa la primera comprobación del planificador
como referencia y solo dispara en una comprobación posterior. La prueba previa de la
web no guarda esa referencia.

## Estado y recuperación

Puedes pausar, reanudar o cancelar recordatorios antes de que se disparen. Al reanudar,
una fecha ya vencida se procesa en la siguiente revisión. La lista se actualiza cada
5 segundos y muestra el último valor revisado y los errores de consulta.

Una consulta fallida conserva el recordatorio y se reintenta con su frecuencia configurada.
No se convierte un error del tool en una condición cumplida.

Cuando se cumple el disparador, el recordatorio pasa a **Pendiente de notificación** y
utiliza `notifications.send`. Si Notificaciones está desactivado o no disponible, se
reintenta cada minuto sin perder el disparador ya cumplido. **Aviso encolado** significa
que el aviso ya está guardado en la cola de Notificaciones; allí puedes consultar su envío.

El recordatorio usa un identificador estable para encolar el aviso: recuperar un proceso
interrumpido no crea otra notificación. Las comprobaciones usan una reserva temporal
para evitar que dos procesos ejecuten el mismo trabajo simultáneamente. Tras un cierre
abrupto, una reserva puede tardar hasta 3 minutos en caducar. Las garantías de entrega
final de WhatsApp son las mismas que las de [Notificaciones](notifications.md).

## API y uso desde skills

- `GET /api/v1/tools/reminders`: últimos 100 recordatorios no cancelados.
- `GET /api/v1/tools/reminders/catalog`: tools de consulta disponibles.
- `POST /api/v1/tools/reminders`: crear.
- `POST /api/v1/tools/reminders/preview`: probar un disparador de tool.
- `PATCH /api/v1/tools/reminders/{id}` con `{"status":"paused"}` o `{"status":"active"}`.
- `DELETE /api/v1/tools/reminders/{id}`: cancelar sin borrar el registro de auditoría.

Estas rutas utilizan la autenticación administrativa habitual de Artemis.

```json
{
  "message": "Revisar el backup",
  "trigger": {"kind": "time", "at": "2030-01-01T10:00:00Z"}
}
```

```json
{
  "message": "La descarga 42 terminó",
  "trigger": {
    "kind": "tool",
    "tool_name": "usenet.history",
    "input": {},
    "condition": {"path": "items[id=42].status", "operator": "contains", "value": "SUCCESS"},
    "interval_seconds": 60
  }
}
```

Puedes incluir `request_id` con un UUID y reutilizarlo al reintentar la creación.
Los skills registrados pueden usar el tool `reminders.create` con el mismo objeto como
entrada. Programar un recordatorio no permite ejecutar tools de escritura como consultas
ni elegir destinatarios ajenos a la configuración de Notificaciones.
