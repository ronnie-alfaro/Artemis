"""Persistent, agent-scoped semantic memory with local CPU embeddings."""
from __future__ import annotations

import os
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

COLLECTIONS = ("agent_persona", "agent_memory", "agent_relations")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class MemoryManager:
    """Lazy initialization keeps unrelated requests independent of model loading.

    An injected encoder supports offline tests. Production always uses MiniLM.
    All IDs and queries are scoped to the authenticated calling agent.
    """

    def __init__(self, path: str | None = None, *, encoder: Any = None) -> None:
        self.path: str = path or os.environ.get("ARTEMIS_MEMORY_DIR", "/data/memory")
        self._encoder = encoder
        self._client: Any = None
        self._collections: dict[str, Any] = {}
        self._lock = RLock()

    def _collection(self, name: str) -> Any:
        if name not in COLLECTIONS:
            raise ValueError("Colección de memoria no válida.")
        if self._client is None:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self.path, settings=Settings(anonymized_telemetry=False),
            )
            for collection in COLLECTIONS:
                self._collections[collection] = self._client.get_or_create_collection(
                    collection, embedding_function=None, metadata={"hnsw:space": "cosine"},
                )
        return self._collections[name]

    def _embed(self, text: str) -> Any:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(
                os.getenv("ARTEMIS_EMBEDDING_MODEL_PATH", MODEL), device="cpu",
                local_files_only=os.getenv("ARTEMIS_EMBEDDINGS_OFFLINE", "false") == "true",
            )
        return self._encoder.encode([text], normalize_embeddings=True).tolist()

    @staticmethod
    def _validate(agent: str, value: str) -> None:
        if not agent.strip() or not value.strip() or len(value) > 16000:
            raise ValueError("Agente y texto/ID obligatorios; máximo 16000 caracteres.")

    def remember(self, collection: str, agent: str, text: str) -> str:
        self._validate(agent, text)
        with self._lock:
            target = self._collection(collection)
            embedding = self._embed(text)
            memory_id = str(uuid4())
            target.add(ids=[memory_id], documents=[text], embeddings=embedding,
                       metadatas=[{"agent": agent}])
            return memory_id

    def remember_event(self, agent: str, event_id: str, text: str,
                       metadata: dict[str, str]) -> str:
        """Idempotent automatic memories, isolated from manual memories."""
        self._validate(agent, text)
        key = str(uuid5(NAMESPACE_URL, f"artemis-event:{agent}:{event_id}"))
        with self._lock:
            target = self._collection("agent_memory")
            if not target.get(ids=[key], include=[])["ids"]:
                target.add(ids=[key], documents=[text], embeddings=self._embed(text),
                           metadatas=[{**metadata, "agent": agent, "source": "interaction"}])
        return key

    def search(self, collection: str, agent: str, text: str,
               limit: int = 5) -> list[dict[str, Any]]:
        self._validate(agent, text)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("El límite debe estar entre 1 y 50.")
        with self._lock:
            target = self._collection(collection)
            if target.count() == 0:
                return []
            result = target.query(
                query_embeddings=self._embed(text), n_results=limit,
                where={"agent": agent}, include=["documents", "distances"],
            )
            return [
                {"id": memory_id, "text": document, "distance": distance}
                for memory_id, document, distance in zip(
                    result["ids"][0], result["documents"][0], result["distances"][0],
                    strict=True,
                )
            ]

    def browse(self, collection: str, agent: str | None = None,
               offset: int = 0, limit: int = 20) -> dict[str, Any]:
        """Read a bounded page for the authenticated administrative panel, without encoding."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Paginación no válida.")
        with self._lock:
            target = self._collection(collection)
            filters = {"agent": agent} if agent else None
            # Count the selected scope without reading document or vector payloads.
            total = len(target.get(where=filters, include=[])["ids"]) if agent else target.count()
            result = target.get(where=filters, offset=offset, limit=limit,
                                include=["documents", "metadatas", "embeddings"])
            embeddings = result["embeddings"]
            return {"total": total, "offset": offset, "limit": limit, "items": [
                {"id": key, "text": result["documents"][i],
                 "metadata": result["metadatas"][i],
                 "embedding": embeddings[i].tolist() if embeddings is not None else []}
                for i, key in enumerate(result["ids"])
            ]}

    def forget(self, collection: str, agent: str, memory_id: str) -> bool:
        self._validate(agent, memory_id)
        with self._lock:
            target = self._collection(collection)
            found = target.get(ids=[memory_id], where={"agent": agent})["ids"]
            if not found:
                return False
            target.delete(ids=found, where={"agent": agent})
            return True
