# Tool de Notificaciones

En la web, abre **Tools** y selecciona **Notificaciones** o **Webhooks**. Desde allí puedes:

- Activar o desactivar los avisos.
- Elegir WhatsApp y una conversación registrada, o dejar selección automática si solo hay una.
- Guardar la configuración en PostgreSQL.
- Enviar un aviso directamente, sin activar un skill.
- Consultar el historial compartido de envíos directos, skills y webhooks.

La configuración compartida se aplica tanto al tool como a los webhooks.
Si desactivas Notificaciones, los nuevos webhooks se guardan sin envío y los avisos
en cola esperan a que vuelvas a activarlas. Un envío que ya está en curso puede terminar.
No se reenvían automáticamente eventos guardados sin envío.

## Uso directo por API

`POST /api/v1/tools/notifications/send` usa la autenticación administrativa habitual
de Artemis, independiente del token de recepción de webhooks.

```json
{
  "title": "Aviso directo",
  "message": "La tarea terminó correctamente.",
  "event_id": "mi-aviso-001"
}
```

La respuesta HTTP 202 significa que el aviso quedó guardado en la cola, no que
WhatsApp ya lo haya entregado. Reutiliza `event_id` si reintentas una misma operación.

- `GET /api/v1/tools/notifications/configuration`: configuración y destinos disponibles.
- `PUT /api/v1/tools/notifications/configuration`: guarda `enabled`, `channel: "whatsapp"`
  y `recipient_id` (null para selección automática).
- `GET /api/v1/tools/notifications/history?limit=50`: historial de avisos.

## Uso desde un skill

`notifications.send` está registrado en `ToolRegistry` y disponible para los skills
registrados en Artemis. Un skill puede invocarlo con:

```python
await tools.invoke(ToolInvocation(
    tool_name="notifications.send",
    agent_name=self.definition.name,
    input={
        "title": "Tarea terminada",
        "message": "El resultado ya está disponible.",
        "event_id": "identificador-unico-de-esta-notificacion",
    },
    risk_level=RiskLevel.WRITE,
))
```

El skill no elige destinatarios arbitrarios ni cambia la configuración del tool.
La identidad del skill determina el origen mostrado en el historial. El registro
controla qué agentes pueden invocarlo.

El envío se declara WRITE, con `requires_approval=False`: usa exclusivamente el
canal y destinatario habilitados por el operador. Los demás tools WRITE mantienen
la confirmación obligatoria por defecto.

## Relación con los webhooks

Los webhooks son adaptadores de entrada: normalizan el evento y llaman al mismo
servicio de Notificaciones que utiliza el tool. Se conservan las URLs existentes,
el token de recepción y la cola persistente con reintentos. La configuración de
Tools prevalece sobre el destinatario inicial indicado por la variable de entorno.

Los skills no generan avisos nuevos automáticamente por el hecho de tener el tool
disponible: lo invocan cuando una función o regla lo requiera.
