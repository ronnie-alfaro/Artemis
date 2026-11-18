# Curiosidad

## Integrar desde WhatsApp o Telegram

1. Añade a `ARTEMIS_CURIOSITY_ALLOWED_URLS` las URL HTTPS exactas del documento OpenAPI JSON y de las operaciones de lectura autorizadas, separadas por comas. La API carga esta configuración al desplegar.
2. Asigna **Integrar APIs · Curiosidad** al bot en **Agentes**. El montaje y las consultas se hacen en el chat.
3. Envía `Curiosidad integrar inventario https://docs.example.com/openapi.json`. Si el documento está en el propio mensaje, indica el origen de la API en lugar de la URL del documento y pega el JSON en la línea siguiente.
4. Artemis responde con los comandos de consulta generados. Por ejemplo, `Curiosidad consultar inventario obtenerInventario`. El primer uso verifica la respuesta del servicio contra el contrato guardado.
5. `Curiosidad retirar inventario` elimina la integración de ese chat. Volver a integrar con el mismo nombre reemplaza el adaptador si el nuevo documento tiene operaciones válidas.

El adaptador es declarativo, se guarda en PostgreSQL y solo está disponible en su conversación y canal. Admite OpenAPI 3.0/3.1 en JSON con un servidor fijo y hasta 16 operaciones GET con `operationId`, sin autenticación ni parámetros. La respuesta HTTP 200 debe declarar `application/json` con un esquema de objeto o arreglo. Se admiten propiedades, campos requeridos, elementos de arreglos, restricciones simples y referencias locales acotadas a `components/schemas`. Las referencias externas y circulares quedan fuera del montaje.

Las solicitudes tienen un plazo de ocho segundos, limitan el cuerpo a 128 KiB y validan la URL exacta antes de cada llamada. El ejecutor no sigue redirecciones ni incorpora credenciales del entorno. Esta versión usa comandos explícitos y deja pendientes la selección conversacional libre, el montaje de APIs autenticadas, las operaciones de escritura y la generación de código.

## Inventario administrativo

Desde **Curiosidad** en la consola, introduce el objetivo de la exploración y pega una especificación JSON de Swagger 2.0 u OpenAPI 3.0/3.1. El analizador enumera operaciones HTTP declaradas directamente y conserva el método, la ruta, el identificador de operación, los parámetros declarados, los códigos de respuesta y las indicaciones de autenticación y referencias.

Los resultados representan declaraciones del documento. Se guardan como conocimiento técnico en PostgreSQL y quedan disponibles después de reiniciar la API. Enviar el mismo objetivo y JSON equivalente devuelve el informe existente. La consola muestra las 50 exploraciones más recientes.

## API administrativa

- `POST /api/v1/curiosity/explorations` recibe `objective` y `specification`, ambos strings. El segundo contiene el documento JSON.
- `GET /api/v1/curiosity/explorations` enumera los informes recientes.
- `GET /api/v1/curiosity/explorations/{id}` devuelve un informe y su historial.

La API utiliza la autenticación administrativa configurada para Artemis y requiere `DATABASE_URL`. El análisis se completa en la solicitud y se guarda en una transacción. Su historial empieza en `DISCOVERED` y termina en `ANALYZED`, `FAILED` para documentos inválidos o fuera de límite, o `BLOCKED` para formatos no admitidos.

## Límites actuales

- Se admiten 131 072 caracteres de entrada y hasta 128 operaciones por informe. Introduce objetivos y contratos sin credenciales.
- El analizador trabaja sin conexiones externas. Omite las descripciones, conserva un resumen del documento y señala referencias sin resolver en las operaciones inventariadas.
- El inventario administrativo y los adaptadores de chat tienen registros separados. El inventario admite también Swagger 2.0 y enumera declaraciones sin ejecutar operaciones.

Para probar persistencia y deduplicación con PostgreSQL, configura `ARTEMIS_TEST_CURIOSITY_DATABASE_URL` con una base de datos de pruebas y ejecuta `python -m pytest tests/test_curiosity.py` desde `backend`.
