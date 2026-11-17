Cerebro
=======

El panel `#/cerebro` ofrece tres vistas de consulta:

- Memoria: colecciones `agent_persona`, `agent_memory` y `agent_relations`, con filtro exacto por agente y páginas de 20 documentos. Cada ficha muestra texto, ID, metadatos y un gráfico de los componentes del embedding; sus valores completos se pueden desplegar. El gráfico representa dimensiones, no una proyección de similitud entre documentos.
- Herramientas nativas: inventario administrativo de contratos y parámetros JSON Schema. La activación sigue en Habilidades/Agentes; el inventario no garantiza disponibilidad para un agente concreto.
- Minions: ID, nombre, mitología, estado, tarea y destino. Consulta cada 10 segundos; el historial se pierde al reiniciar el servidor.

API de lectura: `GET /api/v1/memory/{collection}?agent=...&offset=0&limit=20` (máximo 50). Usa la autenticación administrativa existente: si `ARTEMIS_ADMIN_TOKEN` está configurado, requiere Bearer. El administrador puede consultar todos los agentes; las herramientas de memoria del LLM conservan su aislamiento por agente. No hay edición ni eliminación desde esta pantalla.

La lectura no carga el modelo de embeddings. Los fallos de almacenamiento responden 503 sin exponer rutas internas. El total filtrado requiere recuperar los IDs del agente; colecciones muy grandes pueden necesitar un índice de conteos adicional. Documentos y vectores se recuperan únicamente por página.

La pantalla no activa el bucle de tool calling, no lanza minions y no configura workers remotos. Tampoco guarda conversaciones automáticamente. Se debe reconstruir y desplegar API y web para aplicar los cambios; ese despliegue es una operación separada.
