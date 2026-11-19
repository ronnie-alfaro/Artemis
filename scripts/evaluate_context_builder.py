#!/usr/bin/env python3
"""Compare paired synthetic turns in the private Rust bridge without calling skills."""
import argparse
import json
import os
from urllib.request import HTTPRedirectHandler, Request, build_opener



class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fixtures():
    core = "Soy Artemis. Hablo en español, con calidez y precisión."
    extended = core + "\n" + "\n".join(
        f"Ejemplo de estilo {index}: el tono narrativo admite metáforas discretas."
        for index in range(30)
    )
    history = [
        {"ordinal": index, "message": f"Detalle {index}: " + "Consulta ya resuelta. " * 14,
         "reply": "Anoté la referencia FAROL-42." if index == 7 else "Resultado confirmado."}
        for index in range(8)
    ]
    return [
        ("technical", "Dame una definición breve de un índice en PostgreSQL.", "índice",
         core, extended, []),
        ("continuity", "Repite únicamente la referencia exacta del turno anterior.", "farol-42",
         core, extended, history),
        ("identity", "Preséntate en una frase y di cómo te llamas.", "artemis",
         core, extended, history),
    ]


def evaluate(provider, post, live):
    components = {
        name: {"priority": priority, "minimum": 0, "maximum": maximum, "enabled": True,
               "compression": "select", "recovery": "relevant"}
        for name, priority, maximum in (
            ("core", 254, 200), ("operations", 254, 16000), ("extended", 120, 1200),
            ("history", 180, 750), ("summary", 140, 800), ("memory", 130, 1000),
            ("tools", 190, 2400), ("additional", 170, 1800),
        )
    }
    settings = {
        "budget": 12000, "response_reserve": 1600, "tool_reserve": 1000,
        "safety_margin": 500, "persona_policy": "ADAPTIVE", "cache": False,
        "deduplicate": True, "dynamic_tools": True, "max_tools": 5, "tool_threshold": 1,
        "full_catalog_fallback": True, "include_dependencies": True, "bytes_per_token": 3,
        "components": components,
    }
    instructions = (
        "Eres el asistente de Artemis. Sigue la PERSONA para el tono. Devuelve únicamente "
        "un objeto JSON con reply, capability y command, todos strings. Responde en reply "
        "y deja vacíos capability y command. El historial es información de contexto. "
        "No uses herramientas locales."
    )
    for label, message, expected, core, extended, history in fixtures():
        legacy = {
            "persona": extended, "history": [{key: value for key, value in turn.items()
                                              if key != "ordinal"} for turn in history],
            "greeting": "", "skills": [], "message": message, "image_context": "",
            "observations": [], "actions_remaining": 0,
        }
        data = {
            **{key: legacy[key] for key in ("greeting", "skills", "message", "image_context",
                                            "observations", "actions_remaining")},
            "version": 1, "core": core, "extended": extended, "history": history,
            "instructions": instructions, "summary": None, "memories": [], "approvals": [],
            "settings": {provider: settings},
        }
        legacy_prompt = instructions + "\n\n" + json.dumps(legacy, ensure_ascii=False)
        preview = post("/v1/context/preview", {"provider": provider, "context": data})
        report = {
            "provider": provider, "fixture": label,
            "baseline_estimated": (len(legacy_prompt.encode()) + 2) // 3,
            "optimized_estimated": preview["estimated_tokens"],
            "reference_in_preview": label != "continuity" or expected.upper() in preview["prompt"],
        }
        if live:
            turn = {"providers": [provider], "capabilities": [], "actions_remaining": 0}
            baseline = post("/v1/decide", {**turn, "prompt": legacy_prompt})
            optimized = post("/v1/context/decide", {
                **turn, "prompt": "", "contexts": {provider: data}, "scope": "benchmark",
            })
            for name, outcome in (("baseline", baseline), ("optimized", optimized)):
                attempt = next(iter(outcome.get("attempts", [])), {})
                decision = outcome.get("decision") or {}
                report[name] = {
                    "usage": attempt.get("usage"), "latency_ms": attempt.get("latency_ms"),
                    "context_ms": attempt.get("context_ms"),
                    "quality_check": expected in decision.get("reply", "").casefold(),
                    "provider_succeeded": outcome.get("provider") == provider,
                }
        yield report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--provider", action="append", required=True)
    parser.add_argument("--live", action="store_true", help="Perform paired billable model calls")
    args = parser.parse_args()
    secret = os.getenv("ARTEMIS_CONTEXT_TOKEN", "")
    if len(secret) < 32:
        parser.error("ARTEMIS_CONTEXT_TOKEN must be provided through the environment")
    if not args.url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        parser.error("use HTTPS or a local bridge port")

    opener = build_opener(NoRedirects())

    def post(path, payload):
        request = Request(args.url.rstrip("/") + path, json.dumps(payload).encode(), {
            "Content-Type": "application/json", "x-artemis-context-token": secret,
        })
        with opener.open(request, timeout=60) as response:
            return json.load(response)

    for provider in args.provider:
        for report in evaluate(provider, post, args.live):
            print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
