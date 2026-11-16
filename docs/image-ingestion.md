# Ingesta visual en WhatsApp y Telegram

## Frontera de seguridad

El runtime compartido clasifica la entrada antes del orquestador:

- Texto: conserva el flujo existente.
- Imagen con texto/caption: el texto es la instrucción. La descripción visual se
  transporta en `IncomingMessage.image_context`, separada del contenido que
  selecciona habilidades y sesiones. Los agentes de conversación y desarrollo
  reciben ese contexto como datos no fiables.
- Imagen sola: descarga y valida, llama a visión **sin herramientas**, guarda
  descripción y metadatos en Cerebro y responde con `img-<24 caracteres hex>`.
  Esta rama nunca invoca el orquestador, sesiones, aprobaciones ni habilidades.
  El texto visible dentro de la imagen nunca se convierte en caption/instrucción.
- Si falla descarga, integridad o visión, responde con la limitación y no ejecuta
  la instrucción parcialmente sin el contexto esperado.

Telegram admite fotos de chats privados autorizados y elige la variante mayor.
WhatsApp resuelve `/media/<id>` y descarga desde HTTPS de dominios multimedia
permitidos, sin seguir redirecciones. Se limita la descarga a 10 MiB y se aceptan
firmas JPEG, PNG y WebP; se verifica SHA-256 cuando lo aporta el proveedor.
Otros formatos y los documentos adjuntos no se interpretan como imágenes.

## Motor multimodal

Configurar en el entorno activo (sin guardar secretos en Git):

```dotenv
ARTEMIS_VISION_URL=http://servidor-vision:11434
ARTEMIS_VISION_MODEL=modelo-multimodal-instalado
```

Contrato: API Ollama `POST /api/chat`, imágenes base64, `stream=false`, sin tools.
Referencia: https://docs.ollama.com/api/chat
El servidor debe ser accesible desde el contenedor API y tener un modelo con
visión previamente instalado. La aplicación no descarga modelos automáticamente.
Se serializan las inferencias, se limita el contexto/salida y se descarga el modelo
de RAM al terminar (`keep_alive=0`). Sin configuración no se inventan descripciones:
Artemis informa de que la visión no está disponible y no ejecuta acciones.
La identificación de especie/modelo es una hipótesis cuando la imagen no permite
confirmarla; no se garantiza exactitud taxonómica ni identificación por foto.

## Persistencia y caducidad

`/data/memory/images` comparte el volumen persistente de Cerebro. Contiene bytes
originales y un manifiesto JSON privado con ID, canal, ámbito de conversación,
fecha, vencimiento, SHA-256, ID de adjunto, MIME y descripción. El ID deriva del
ámbito y evento, por lo que reintentos no duplican imágenes ni recuerdos.
`agent_memory` recibe un evento con embedding y metadatos `kind=image`, `scope`,
`image_id` y `expires_at`.

Vencen a los **7 días del timestamp de entrada**, no de cada consulta. Las
referencias rechazan registros vencidos inmediatamente. Un trabajador independiente
purga bytes, manifiestos y recuerdos cada 60 segundos y al arrancar. Las consultas
generales de memoria también eliminan recuerdos visuales vencidos. Se limpian los
adjuntos de la bandeja PostgreSQL a los 7 días de recepción local y los archivos
huérfanos a los 7 días de su creación.

Las interacciones y resultados con contexto visual no se vuelven a copiar en la
memoria permanente. Se propaga la marca temporal a las habilidades de desarrollo;
los trabajos derivados y sus archivos auxiliares caducan con la primera imagen
que referencian. Los trabajadores de host limpian logs/respuestas cada 5 segundos
usando marcadores persistentes y excluyen esos trabajos del historial de turnos
posteriores. Las ejecuciones visuales de Codex usan sesiones efímeras.

La purga cubre el almacenamiento activo de Artemis, no las copias del proveedor,
mensajes ya enviados al usuario, copias de seguridad externas ni archivos que el
usuario solicite crear expresamente mediante una nueva instrucción.

## Referencias posteriores

Una consulta que mencione imagen/foto o un ID busca únicamente dentro del mismo
canal, agente y conversación. Los IDs se resuelven exactamente; las descripciones
se buscan con embeddings de Cerebro y umbral de similitud. «La última imagen»
selecciona la más reciente; varios resultados piden concretar el ID. El contexto
se adjunta a la nueva instrucción, sin renovar la caducidad. Un ID inexistente,
ajeno o caducado solicita reenviar la imagen.

## Operación

Después de configurar el motor, reconstruir/recrear API y web con el comando de
AGENTS.md. Actualizar las copias instaladas de los trabajadores cuando cambien sus
scripts; esperar a que terminen los trabajos activos antes de recargarlos.
Validación local: pruebas de canales, seguridad de ingesta, referencias y TTL,
memoria Chroma, trabajadores, lint y tipos. Para validar visión real hace falta
un motor configurado y una imagen real; las pruebas unitarias usan dobles sin
llamadas externas ni mensajes a usuarios.
