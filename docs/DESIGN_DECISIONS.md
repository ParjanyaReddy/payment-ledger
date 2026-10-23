# Architectural Decision Records (ADRs)

This document records the architectural choices, alternatives considered, and tradeoffs made throughout the lifecycle of the project.

---

### ADR 001: Decimal Strings & PostgreSQL `NUMERIC(18,2)` for Currency

- **Status:** Accepted
- **Context:** Financial applications must guarantee exact mathematical precision. Binary floating-point numbers (`float` in Python, standard IEEE-754 numbers in JSON) suffer from binary representation errors (e.g. `0.1 + 0.2 = 0.30000000000000004`).
- **Decision:**
  - Transport amounts over the API boundary as **decimal strings** (e.g., `"150.75"`).
  - Parse and perform all monetary arithmetic in Python using `decimal.Decimal`.
  - Store amounts in PostgreSQL as `NUMERIC(18,2)` with database-level `CHECK` constraints.
- **Alternatives Considered:**
  1. *Binary Floats:* Rejected immediately due to unavoidable floating-point drift and rounding errors.
  2. *Integer Cents (minor units):* Viable, but decimal strings provide immediate human readability in audits, logs, and UI without client-side division bugs.
- **Tradeoffs:** Slightly higher serialization overhead compared to native integer types, but eliminates floating-point rounding bugs entirely.

---

### ADR 002: Asynchronous Python Stack (FastAPI + SQLAlchemy 2.x + asyncpg)

- **Status:** Accepted
- **Context:** High-throughput payment systems handle concurrent network I/O operations (HTTP requests, database connection pools, outbox polling).
- **Decision:** Use FastAPI paired with SQLAlchemy 2.0 AsyncEngine and `asyncpg` (the fastest asynchronous PostgreSQL driver for Python).
- **Alternatives Considered:**
  1. *Synchronous Flask / Django with Psycopg2:* Slower under high concurrency; blocks OS threads on database round-trips.
  2. *Go / Java:* Excellent performance, but Python was selected to prioritize clean interview walkability while retaining high async performance.
- **Tradeoffs:** Requires strict adherence to asynchronous paradigms (`async/await`, `asynccontextmanager`, `pytest-asyncio`).

---

### ADR 003: Local PostgreSQL 18 with Docker Compose Fallback

- **Status:** Accepted
- **Context:** The development host has PostgreSQL 18 running locally as a Windows service, while containerization is required for CI pipelines and portable deployments.
- **Decision:** Support both seamlessly. Local `.env` connects directly to local PostgreSQL 18 for zero-friction local execution, while `docker-compose.yml` and `Dockerfile` provide isolated PostgreSQL 16 containers for GitHub Actions CI and production container deployments.
- **Tradeoffs:** Developer must ensure test database (`payment_ledger_test`) exists locally, which is automated via setup scripts.

---

### ADR 004: Distinct Liveness (`/health`) and Readiness (`/ready`) Probes

- **Status:** Accepted
- **Context:** In production orchestration (Kubernetes, Docker Swarm), routing traffic to an instance whose database connection is dead causes immediate cascading 500 errors.
- **Decision:** Provide two distinct endpoints:
  - `/api/v1/health` (Liveness): returns 200 immediately to verify process responsiveness.
  - `/api/v1/ready` (Readiness): executes `SELECT 1` against PostgreSQL; returns 503 if the database is unreachable, removing the instance from active load balancers.
- **Tradeoffs:** Slight database query overhead for readiness checks, mitigated by reasonable polling intervals (e.g., 5-10 seconds).

---

### ADR 005: Database-Level CHECK Constraints vs. Application-Only Validation

- **Status:** Accepted
- **Context:** In financial ledger systems, software bugs, race conditions, or uncoordinated database scripts can attempt to write negative balances, negative transfer amounts, or invalid ledger directions.
- **Decision:** Enforce non-negative balances (`CHECK balance >= 0`), positive transfer amounts (`CHECK amount > 0`), valid statuses, and valid ledger directions at the PostgreSQL schema level via table `CheckConstraint` definitions.
- **Alternatives Considered:**
  1. *Application-Only Validation:* Vulnerable to race conditions, manual database interventions, and bugs in unvalidated code paths.
- **Tradeoffs:** Requires handling database `IntegrityError` when constraints trigger, but guarantees mathematical impossibilities cannot be stored in the database.

---

### ADR 006: Deterministic Ascending Lock Ordering for Deadlock Elimination

- **Status:** Accepted
- **Context:** Opposing concurrent transfers (A->B and B->A) that acquire locks in arbitrary order create circular wait conditions, triggering PostgreSQL `40P01` deadlock errors and transaction aborts.
- **Decision:** Always sort account IDs prior to querying and acquire pessimistic row locks in ascending order (`ORDER BY id FOR UPDATE`).
- **Alternatives Considered:**
  1. *Arbitrary Lock Acquisition with Retry Loops:* Retrying on deadlock adds latency variance and burns CPU cycles on hot accounts.
  2. *Optimistic Versioning:* Results in massive retry storms and elevated failure rates under heavy contention.
- **Tradeoffs:** Requires sorting two UUIDs in memory ($O(1)$) before executing the query, resulting in provably zero deadlocks.

---

### ADR 007: Session Loop Scope & Bounded Connection Pooling for Async Testing

- **Status:** Accepted
- **Context:** Running 200 concurrent tasks against `NullPool` opens 200 simultaneous socket connections, exceeding PostgreSQL's default `max_connections = 100` limit and raising `sorry, too many clients already`. Furthermore, function-scoped event loops on Windows leave orphaned asyncpg connection teardowns.
- **Decision:** Configure pytest-asyncio to use `session` loop scope and configure `test_engine` with a bounded connection pool (`pool_size=25, max_overflow=25, pool_timeout=30.0`).
- **Tradeoffs:** High-concurrency tests queue up on the pool and reuse connections efficiently, exactly mirroring production reverse proxy connection queuing.

---

### ADR 008: Database-Native Atomic Idempotency via `ON CONFLICT DO NOTHING`

- **Status:** Accepted
- **Context:** API retry traffic and client-side rapid double-clicks create race conditions that can charge accounts multiple times if duplicate requests execute in parallel.
- **Decision:** Use client-generated UUID `Idempotency-Key` headers paired with PostgreSQL-native `INSERT INTO idempotency_keys ... ON CONFLICT (key) DO NOTHING RETURNING key` in the exact same database transaction as the financial transfer. In addition, compute a deterministic SHA-256 fingerprint of the request method, path, and payload to detect tampering (422 Unprocessable Content), and cache the completed HTTP status and body for identical replay (`X-Idempotent-Replay: true`).
- **Alternatives Considered:**
  1. *Redis Distributed Lock (Redlock):* Introducing an external cache risks split-brain state where Redis confirms a lock or key but PostgreSQL transfer fails (or vice versa), breaking ACID consistency.
  2. *Application-Level `SELECT then INSERT`:* Vulnerable to race windows where two simultaneous requests both observe an empty key row before either inserts.
- **Tradeoffs:** Adds an idempotency table lookup and insert per financial request, but guarantees provably zero duplicate charges and zero split-brain inconsistencies under concurrent retries.

