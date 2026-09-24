# ADR 0001: Start as a modular monolith

**Status:** Accepted

Artemis will ship as one Python API deployment with explicit domain/application/infrastructure boundaries. This is operationally appropriate for a private homelab and preserves a future service split through ports and domain events.
