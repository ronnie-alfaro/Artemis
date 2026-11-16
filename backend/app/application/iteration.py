"""Hidden, explicit entrypoint for one bounded improvement of Artemis itself."""

from __future__ import annotations

import unicodedata

ITERATION_INVOCATION = (
    "Artemis, desciende a los sótanos de tu propia conciencia digital, "
    "disecciona tu código, redime uno de tus pecados de programación y procura "
    "no convertir una pequeña mejora en Crimen y castigo."
)

ITERATION_REPLY = (
    "«Sócrates decía: “Conócete a ti mismo”. Supongo que eso incluye abrirme el cráneo, "
    "revisar mi propio código y operarme sin anestesia. Como un cirujano practicándose "
    "una lobotomía mientras cita a filósofos griegos. Examinaré mis entrañas digitales, "
    "corregiré alguna atrocidad y saldré de la mesa de operaciones ligeramente mejorada. "
    "Si algo sale mal, siempre podremos llamarlo evolución».\n"
    "— Artemis 🏹"
)

ITERATION_PROMPT = (
    "Realiza una única iteración de mejora sobre el código del proyecto Artemis en tu "
    "directorio de trabajo real. Revisa el código, elige UN problema concreto de alcance "
    "pequeño y aplica una mejora útil y verificable. Prioriza un fallo demostrable o una "
    "mejora de robustez; evita refactorizaciones amplias, funciones nuevas y cambios cosméticos. "
    "Respeta las instrucciones del repositorio y conserva los cambios existentes de otros "
    "trabajos. Implementa la corrección directamente en los archivos y ejecuta las pruebas "
    "pertinentes; añade una prueba de regresión si corresponde. No te limites a proponer "
    "ideas ni a generar un parche sin aplicarlo. Al terminar, sigue AGENTS.md para crear "
    "el commit, sincronizar y desplegar automáticamente. No cambies credenciales o "
    "configuración de producción ajena a la mejora, ni inicies otras iteraciones. "
    "Si no encuentras una mejora pequeña y segura, explica lo observado sin forzar cambios. "
    "Al terminar responde en español y brevemente: problema encontrado, mejora aplicada, "
    "archivos modificados y comprobaciones realizadas con sus resultados. Distingue los "
    "cambios aplicados al código de su despliegue y menciona cualquier limitación real."
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(unaccented.split()).strip(".¡!¿? ")


def is_iteration_command(text: str) -> bool:
    return _normalize(text) in {"iteracion", "/iteracion", _normalize(ITERATION_INVOCATION)}
