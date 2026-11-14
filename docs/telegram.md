# Telegram

El canal reutiliza el orquestador, las habilidades, las aprobaciones y las herramientas de Artemis.
WhatsApp y Telegram mantienen conversaciones, cursores y asignaciones independientes en PostgreSQL.

1. Crea un bot con [BotFather](https://t.me/BotFather).
2. Puedes usar **Canales → Conexión de Telegram** si ya está habilitado el almacenamiento cifrado ([guía KMS](aws-kms.md)); guarda y aplica sin reiniciar Docker. Como alternativa inicial, configura `TELEGRAM_BOT_TOKEN` con su token y `TELEGRAM_ALLOWED_USER_IDS` con los identificadores numéricos de los usuarios autorizados, separados por comas. No uses nombres de usuario. La lista es obligatoria; solo se aceptan chats privados de esos usuarios.
3. Configura `DATABASE_URL` (Docker Compose ya lo proporciona).
4. Tras reiniciar el servicio con esta configuración, abre **Agentes → Telegram**, asigna las habilidades y guarda. Puedes personalizar el saludo.
5. Escribe `/start` al bot. Usa «utiliza HABILIDAD», «ayuda» y «salir» como en WhatsApp. `/help` equivale a «ayuda».

Se utiliza `getUpdates` mediante long polling: no se necesita una URL pública. El bot debe estar libre de webhooks y debe tener un único consumidor activo. Si ya tiene un webhook, retíralo mediante `deleteWebhook` antes de iniciar este canal. Véase la [Bot API oficial](https://core.telegram.org/bots/api#getupdates).

Los mensajes se guardan antes de confirmar el cursor y se reintentan cuando falla el procesamiento. Una interrupción después de enviar una respuesta y antes de marcarla completada puede duplicar la respuesta. Los resultados de Codex y Antigravity vuelven al chat de origen. Las selecciones se escriben por texto; no se ofrecen menús de reacciones. Esta primera integración admite texto en chats privados; los archivos, audios y grupos se omiten. Los avisos proactivos y recordatorios conservan su configuración actual de WhatsApp.

API de administración (con la autenticación habitual):

- `GET /api/v1/channels/telegram`: estado sin credenciales.
- `GET/PUT /api/v1/agents/telegram/{bot_id}/skills`: habilidades asignadas.
- `GET/PUT /api/v1/agents/telegram/{bot_id}/profile`: saludo.

El estado devuelve `agent_name` con el identificador numérico del bot. No introduzcas el token en URLs de administración ni en el repositorio.
