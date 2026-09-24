# ADR 0004: Use an explicit execution DAG

**Status:** Accepted

Plans contain nodes and dependencies. The executor runs unblocked nodes concurrently. A small typed graph is sufficient now and avoids adopting a workflow platform prematurely.
