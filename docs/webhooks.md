# Eventos por webhook

Artemis recibe avisos de Seerr y otras aplicaciones y los guarda en PostgreSQL.
En **Tools → Webhooks** puedes ver los últimos 50 eventos, filtrar por el nombre
de la app y actualizar la lista. No requiere tener un skill activo.

## Activación

Genera un secreto, por ejemplo con `openssl rand -hex 32`, y guárdalo en `.env`:

```dotenv
ARTEMIS_WEBHOOK_TOKEN=tu-secreto-generado
```

Aplica la configuración y el código:

```bash
docker compose up -d --build artemis-api artemis-web
```

El token de webhooks es independiente de `ARTEMIS_ADMIN_TOKEN`: permite entregar
eventos, mientras que consultar la lista utiliza la autenticación administrativa
habitual. Si el token está vacío, la recepción devuelve HTTP 503. También se
requiere `DATABASE_URL`; la tabla `webhook_events` se crea al arrancar.

## Seerr

En **Settings → Notifications → Webhook**:

- Habilita la integración y selecciona los eventos que quieres enviar.
- Webhook URL: `http://artemis-api:8000/api/v1/webhooks/seerr`.
- Authorization Header: `Bearer TU_TOKEN_DE_WEBHOOK`. También se acepta el token sin prefijo.
- JSON Payload:

```json
{
  "notification_type": "{{notification_type}}",
  "subject": "{{subject}}",
  "message": "{{message}}"
}
```

Guarda y usa la prueba de notificación de Seerr. El evento aparecerá en **Tools → Webhooks**.
Artemis admite también el JSON predeterminado de Seerr; solo conserva el tipo,
el título y el mensaje, sin guardar objetos adicionales de usuarios o multimedia.

La API de Artemis ya comparte `seerr_default` con Seerr en este despliegue.
Otras aplicaciones deben compartir al menos una red Docker con `artemis-api`.
Usa el DNS del servicio y su puerto interno 8000, no `localhost` dentro de Seerr.

Referencia: https://docs.seerr.dev/using-seerr/notifications/webhook/

## Otras aplicaciones

Envía un POST JSON a `http://artemis-api:8000/api/v1/webhooks/NOMBRE_APP`, con
`Authorization: Bearer TU_TOKEN_DE_WEBHOOK` y `Content-Type: application/json`:

```json
{
  "event": "backup.finished",
  "title": "Backup completo",
  "message": "La copia de seguridad terminó correctamente.",
  "event_id": "backup-2026-11-04-001"
}
```

`NOMBRE_APP` admite letras minúsculas, números, guiones y guiones bajos, hasta
64 caracteres. Es una etiqueta para organizar los eventos; las apps comparten
el token del receptor. Debes incluir al menos un título o un mensaje. Si omites
`event`, se guarda como `notification`.

`event_id` es opcional. Para reintentar una entrega, conserva el mismo identificador:
Artemis devuelve el mismo ID y `duplicate: true`, sin crear otro registro. Cada app
tiene su propio espacio de identificadores. Sin `event_id`, cada POST es un evento
nuevo; no uses un ID de solicitud como identificador único de todos sus cambios.

La respuesta HTTP 202 confirma que el evento ya quedó guardado:

```json
{"id": "UUID_DEL_EVENTO", "status": "received", "duplicate": false}
```

Límites: cuerpo de 64 KiB, tipo de evento de 128 caracteres, título de 512 y
mensaje de 4096. Un token incorrecto devuelve 401; JSON o campos inválidos, 422;
un cuerpo demasiado grande, 413; otro tipo de contenido, 415.

## Consulta

La UI usa `GET /api/v1/webhooks/events?source=seerr&limit=50`. `source` es opcional;
`limit` admite de 1 a 100. La lista se ordena del más reciente al más antiguo.
`GET /api/v1/webhooks/configuration` muestra la disponibilidad y URL, nunca el secreto.
Los registros se conservan en PostgreSQL entre reinicios.

## Avisos por WhatsApp

Con el agente de WhatsApp configurado, los eventos nuevos se guardan con una
notificación pendiente y un proceso de fondo los envía a la conversación del creador.
Si hay una sola conversación registrada, Artemis la selecciona automáticamente.
Si todavía no hay ninguna, escribe al agente: la cola esperará un destino conocido.
Si hay varias, define `ARTEMIS_WEBHOOK_WHATSAPP_RECIPIENT` con el identificador
`user:...` de una conversación registrada; no se envía a todos los participantes.
El webhook no acepta destinatarios enviados por la aplicación externa.

**Tools → Webhooks** indica si el aviso está en cola, enviándose, enviado o pendiente
de reintento. `sent` indica aceptación por la API de WhatsApp, no confirmación de lectura.
Las notificaciones no cambian el skill activo ni ejecutan comandos.
Los eventos anteriores a esta conexión conservan el estado `not_requested`.

La cola sobrevive a los reinicios. Los fallos se reintentan con espera creciente,
y un `event_id` repetido no crea otra notificación. Si WhatsApp acepta un mensaje
pero se pierde la respuesta o el proceso termina antes de registrar el envío,
un reintento puede duplicarlo; la API no ofrece aquí una confirmación transaccional
compartida con PostgreSQL.

La configuración y el envío directo están en **Tools → Notificaciones**.
Consulta [el tool compartido](notifications.md).

## Tools compartidos

**Webhooks** recibe y valida los eventos. El envío se realiza mediante el mismo
servicio del tool **Notificaciones**, donde se configura el canal y el destinatario.
Ambos están en **Tools**; puedes abrir Notificaciones desde la pantalla de Webhooks.
Las URLs de recepción existentes siguen siendo las mismas.
