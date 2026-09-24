# ADR 0006: Use PostgreSQL for platform state

**Status:** Accepted

PostgreSQL will persist conversations, plans, agent runs, tool invocations, approvals, configuration metadata, and audit events through SQLAlchemy 2/Alembic. It is private to the Compose network; secrets are never stored in its rows. Vector memory is a separate port.
