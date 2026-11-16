Memoria vectorial
=================

`app/infrastructure/memory_manager.py` usa ChromaDB persistente y embeddings
normalizados de `sentence-transformers/all-MiniLM-L6-v2` calculados en CPU.
Las colecciones son `agent_persona`, `agent_memory` y `agent_relations`.
Todas las consultas y borrados filtran por el agente que invoca la herramienta.

Las herramientas registradas son `memory.search`, `memory.remember` y
`memory.forget`. Reciben `collection` (por defecto `agent_memory`) y `text`;
para borrar se usa `id`. La búsqueda acepta `limit` entre 1 y 50 y devuelve
ID, texto y distancia coseno (menor es más similar). Las escrituras y borrados
requieren aprobación mediante el registro de herramientas existente.
No se guardan conversaciones automáticamente ni se añade enrutamiento de chat.

Docker monta `memory-data` en `/data/memory`, escribible por UID 10001 incluso
con el sistema raíz de solo lectura. No eliminar ese volumen para conservar
las memorias. Para copias consistentes, detener el escritor antes de copiarlo.
Usar un único proceso API por volumen; no compartirlo entre réplicas.

La imagen descarga el modelo durante la construcción y lo guarda en
`/opt/models/all-MiniLM-L6-v2`; la inferencia funciona sin red. La construcción
inicial requiere acceso a Hugging Face y espacio para PyTorch y el modelo.
Fuera de Docker: `ARTEMIS_MEMORY_DIR`, `ARTEMIS_EMBEDDING_MODEL_PATH` y
`ARTEMIS_EMBEDDINGS_OFFLINE=true` permiten configurar disco y modelo local.
Sin ruta local, la primera operación descarga el modelo; las importaciones e
inicialización son diferidas y no bloquean el arranque de la API.
Los datos se almacenan en claro: aplicar los permisos y copias del host.
