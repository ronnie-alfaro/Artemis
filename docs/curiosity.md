# Curiosidad

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
- La ejecución, generación y activación de herramientas, exploraciones por URL, verificación de interfaces, dependencias recursivas, Chroma e integración conversacional quedan pendientes.

Para probar persistencia y deduplicación con PostgreSQL, configura `ARTEMIS_TEST_CURIOSITY_DATABASE_URL` con una base de datos de pruebas y ejecuta `python -m pytest tests/test_curiosity.py` desde `backend`.
