# ADR 0002: Isolate channels with adapters

**Status:** Accepted

Channels implement `receive`, `send`, and `health` against typed messages. The core has no WhatsApp semantics. This permits REST/Web/CLI now and an official WhatsApp implementation later.
