"""Explicit hidden GitHub synchronization command."""
from app.application.iteration import _normalize

SYNC_PROMPT = (
    "Sincroniza los commits propios de Artemis con GitHub siguiendo AGENTS.md. "
    "Revisa los cambios pendientes; crea commits solo de cambios propios identificables, "
    "sin incluir trabajos ajenos ni secretos. Ejecuta python3 scripts/github_sync.py. "
    "No fuerces el push ni despliegues. Informa rama, commit y resultado real."
)


def is_sync_command(text: str) -> bool:
    return _normalize(text) in {"sincronizate", "/sincronizate"}
