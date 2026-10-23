# Implementation Plan: Production Payment Ledger & Real-Time Auditor

A double-entry payment ledger API and real-time interactive auditor dashboard built for mathematical correctness, zero balance drift, and strict concurrency safety.

---

## 1. System Architecture Overview

```
                      +------------------------------------------+
                      |         Web Dashboard / Client           |
                      |  (Transfer Terminal, Real-Time Ledger,    |
                      |   Reconciliation Monitor, Card Sim)      |
                      +--------------------+---------------------+
                                           | HTTP / REST (JSON)
                                           v
                      +------------------------------------------+
                      |               FastAPI App                |
                      |   - Route Handlers & Input Validation    |
                      |   - Idempotency Interceptor              |
                      |   - Static Dashboard File Server         |
                      +--------------------+---------------------+
                                           |
                +--------------------------+--------------------------+
                | In same DB Transaction                              |
                v                                                     v
+-------------------------------+                     +-------------------------------+
|     PostgreSQL (ACID Store)   |                     |     Transactional Outbox      |
| - accounts (Pessimistic Locks)|                     | - durable event queue         |
| - transactions (Metadata)     |                     | - status: PENDING / DONE      |
| - ledger_entries (Append-Only)|                     +---------------+---------------+
| - idempotency_keys            |                                     |
+-------------------------------+                                     | Polls with
                ^                                                     | SKIP LOCKED
                | Periodic check                                      v
+---------------+---------------+                     +-------------------------------+
|     Reconciliation Worker     |                     |       Outbox Worker           |
| - Verifies:                   |                     | - Calls Google Gemini LLM     |
|   balance == SUM(cr) - SUM(dr)|                     | - Validates with Pydantic     |
| - Flags any ledger drift      |                     | - Fallback to UNCATEGORIZED   |
+-------------------------------+                     +-------------------------------+
```

---

## 2. Core Architectural Guarantees & Decisions

1. **Monetary Precision:**
   - **No binary floating-point numbers (`float`).**
   - API inputs and outputs use **decimal strings** (e.g. `"150.75"`), parsed and computed in Python via `decimal.Decimal`, and stored in PostgreSQL as `NUMERIC(18,2)`. This prevents IEEE-754 precision artifacts (e.g., `0.1 + 0.2 = 0.30000000000000004`).
2. **Double-Entry Invariant:**
   - Every financial transfer writes exactly **two immutable `ledger_entries`** (one `DEBIT`, one `CREDIT`).
   - For every transfer transaction: `SUM(entries) = 0`.
   - Stored account balances are cached projections updated in lockstep within the same database transaction.
3. **Deadlock-Free Pessimistic Concurrency:**
   - Transfers acquire row-level locks on both involved accounts via `SELECT ... FOR UPDATE`.
   - Accounts are **always locked in strictly sorted UUID order** (`min(from_id, to_id)` then `max(from_id, to_id)`). This guarantees that concurrent opposing transfers (A -> B and B -> A) cannot deadlock.
4. **Atomic, Race-Safe Idempotency:**
   - Clients supply an `Idempotency-Key` header with mutation requests.
   - The key is claimed inside the transfer transaction via `INSERT INTO idempotency_keys (...) ON CONFLICT DO NOTHING`.
   - Identical concurrent requests are serialized safely: one transaction proceeds, while concurrent duplicates receive `409 Conflict` (if in-flight) or a cached replayed response (if completed), or `422 Unprocessable Entity` (if payload hash differs).
5. **Database-Level Immutability Guard:**
   - A PostgreSQL trigger on `ledger_entries` prevents any `UPDATE` or `DELETE` statement, ensuring append-only auditability.
6. **Decoupled AI Categorization (Transactional Outbox):**
   - The critical payment path never synchronously calls external AI services.
   - An outbox record is committed atomically with the transfer. A background worker polls with `SELECT ... FOR UPDATE SKIP LOCKED` to invoke Google Gemini, validate categories with Pydantic, and gracefully degrade to `UNCATEGORIZED` on failure.
7. **Interactive Real-Time Frontend:**
   - A modern, dark-mode, glassmorphism dashboard built with Vanilla HTML5, CSS, and JavaScript.
   - Zero compilation or Node.js build step needed; served directly by FastAPI.
   - Provides live ledger monitoring, transfer execution with idempotency replay testing, one-click reconciliation runs, and a card lifecycle simulator.

---

## 3. Repository Directory Structure

```
payment-ledger/
  app/
    __init__.py
    main.py                  # FastAPI application entrypoint, middleware, static mounts
    config.py                # Environment configuration (Pydantic Settings)
    db.py                    # Async SQLAlchemy engine & async sessionmaker
    models/                  # SQLAlchemy ORM declarations
      __init__.py
      account.py             # accounts table (id, currency, balance, version)
      transaction.py         # transactions table (id, from/to, amount, status, memo, ai_category)
      ledger_entry.py        # ledger_entries table (id, txn_id, account_id, direction, amount)
      idempotency_key.py     # idempotency_keys table (key, request_hash, status, response)
      outbox.py              # outbox table (id, transaction_id, status, attempts)
      card.py                # card_authorizations table (holds, captures, refunds)
    schemas/                 # Pydantic v2 boundary models
      __init__.py
      account.py             # AccountCreate, AccountResponse
      transfer.py            # TransferRequest, TransferResponse
      card.py                # CardAuthRequest, CardCaptureRequest, RefundRequest
      reconciliation.py      # ReconciliationReport, AccountAuditResult
    api/                     # Route definitions
      __init__.py
      routes_health.py       # GET /health, GET /metrics
      routes_accounts.py     # POST /accounts, GET /accounts/{id}
      routes_transfers.py    # POST /transfers (with Idempotency-Key)
      routes_reconciliation.py # POST /reconciliation/run, GET /reconciliation/status
      routes_cards.py        # POST /cards/authorize, /capture, /void, /refund
    services/                # Core business logic
      transfer_service.py    # CORE LOGIC: ordered row locking + double-entry transfer
      idempotency.py         # CORE LOGIC: ON CONFLICT key claim & hash verification
      reconciliation.py      # CORE LOGIC: balance drift & ledger integrity checks
      categorizer.py         # LLM prompt, Pydantic schema validation, fallback
      card_service.py        # Card lifecycle state machine & velocity fraud rule
    workers/                 # Background workers
      outbox_worker.py       # Asynchronous outbox polling worker (SKIP LOCKED)
    static/                  # Frontend Web Dashboard (Vanilla HTML5 / CSS / JS)
      index.html             # Single-page dashboard interface
      css/
        style.css            # Dark mode, glassmorphism design tokens, responsive layout
      js/
        api.js               # Typed client calling FastAPI endpoints
        app.js               # Reactive DOM updates, live transfer terminal, charts
  migrations/                # Alembic migration scripts
    versions/
    env.py
    script.py.mako
    alembic.ini
  tests/                     # Automated test suites
    conftest.py              # Test DB fixtures, async HTTP client, fake LLM
    unit/                    # Pure logic tests (schemas, state transitions, math)
    integration/             # API endpoint tests with PostgreSQL
    concurrency/             # High-concurrency stress tests (200 parallel transfers, deadlocks)
  benchmarks/                # Performance benchmarks
    k6/
      transfers_load.js      # Baseline transfer throughput and p50/p95/p99 latency
      inline_vs_outbox.js    # Direct AI vs Outbox worker latency comparison
      ordered_vs_unordered.js# Deadlock rate under opposing transfer contention
  docs/                      # Documentation
    IMPLEMENTATION_PLAN.md   # This document
    ARCHITECTURE.md          # Visual architecture & data flow diagrams
    DESIGN_DECISIONS.md      # Detailed ADRs (Architectural Decision Records)
    LEARNING_NOTES.md        # Beginner-friendly explanations, code walkthroughs, interview Q&A
    GLOSSARY.md              # Plain-English definitions of all financial/distributed terms
    RESULTS.md               # Empirical benchmark measurements and hardware details
    PROGRESS.md              # Living phase tracker and requirement traceability
    WALKTHROUGH.md           # 5-file tour + 10-minute interview script
  docker-compose.yml         # Container definitions for app and PostgreSQL
  Dockerfile                 # Production-ready multi-stage Python container
  .env.example               # Template environment configuration
  .gitignore                 # Git ignore rules
  LICENSE                    # MIT License
  README.md                  # Comprehensive project presentation and guide
  pyproject.toml             # Pinned project dependencies and tool configurations
  .github/workflows/ci.yml   # Continuous Integration pipeline
```

---

## 4. Phase-by-Phase Roadmap

### Phase 0: Scaffolding, Repository & Local Setup
- **Goal:** Set up a clean, runnable repository with code formatters, database connection, healthcheck endpoint, documentation templates, and Git tracking.
- **Deliverables:**
  - Initialize local Git repository with `main` branch.
  - Create `.gitignore`, `LICENSE` (MIT), `.env.example`, and `.env` configured for local PostgreSQL 18.
  - Create `pyproject.toml` with pinned dependencies (`fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `httpx`, `ruff`, `black`, `mypy`).
  - Configure `app/config.py`, `app/db.py`, and `app/main.py` with `/health` and `/ready` endpoints.
  - Setup `docker-compose.yml` and `Dockerfile` (for container deployment and CI).
  - Setup `.github/workflows/ci.yml` for automated CI testing and linting.
  - Initialize living documentation: `docs/PROGRESS.md`, `docs/GLOSSARY.md`, `docs/DESIGN_DECISIONS.md`, and `docs/LEARNING_NOTES.md`.
  - Smoke test: verify local database connectivity and health endpoint.

### Phase 1: Data Model, Migrations & Account Management
- **Goal:** Establish the schema with strict database-level constraints and account management endpoints.
- **Deliverables:**
  - Alembic async environment initialization.
  - Schema definition for tables: `accounts`, `transactions`, `ledger_entries`, `idempotency_keys`, `outbox`.
  - DB Constraints: `accounts.balance >= 0`, `transactions.amount > 0`, `ledger_entries.amount > 0`, all amounts stored as `NUMERIC(18,2)`.
  - Pydantic models for accounts (`AccountCreate`, `AccountResponse`) with decimal string amounts.
  - API routes: `POST /accounts` (create account with initial balance) and `GET /accounts/{id}`.
  - Automated integration tests verifying constraint enforcement (e.g., negative balance rejection).

### Phase 2: Double-Entry Transfer Core & Deadlock-Free Locking
- **Goal:** Implement the central payment engine with provable conservation of money and deadlock prevention.
- **Deliverables:**
  - `app/services/transfer_service.py` (**CORE LOGIC**):
    - Sort account IDs: `first_id = min(from_id, to_id)`, `second_id = max(from_id, to_id)`.
    - Acquire row locks in sorted order using `SELECT ... FOR UPDATE`.
    - Check sufficient funds on the locked row.
    - Atomically create 1 `transactions` row and 2 `ledger_entries` (debit from sender, credit to receiver).
    - Update sender and receiver balances in the same transaction.
    - Enforce business rules: same-currency verification, reject self-transfers (`from_id != to_id`).
  - API route: `POST /transfers`.
  - Concurrency test suite:
    - 200 parallel transfers against an account with funds for only 50 (asserts 0 overdrafts, exact balance = 0).
    - 1,000 opposing transfers A->B and B->A in parallel (asserts 0 deadlocks).
    - Randomized multi-account transfers asserting `Total Money Before == Total Money After`.

### Phase 3: Race-Safe Idempotency
- **Goal:** Ensure identical or re-transmitted requests cannot cause duplicate charges.
- **Deliverables:**
  - `app/services/idempotency.py` (**CORE LOGIC**):
    - Mandatory `Idempotency-Key` UUID header.
    - Compute SHA-256 hash of `HTTP Method + Path + Request Body`.
    - Inside the transfer transaction, execute `INSERT INTO idempotency_keys (key, request_hash, status) VALUES (...) ON CONFLICT DO NOTHING`.
    - If conflict occurs: inspect existing row:
      - Different request hash -> return `422 Unprocessable Entity`.
      - Status `IN_PROGRESS` -> return `409 Conflict`.
      - Status `COMPLETED` -> return cached response body and status code.
    - On success: update idempotency key to `COMPLETED` with stored response.
  - Periodic key cleanup helper (expired keys older than 24h).
  - Concurrency test: 50 concurrent requests with identical idempotency key produce exactly 1 transaction.

### Phase 4: Ledger Immutability & Automated Reconciliation
- **Goal:** Enforce append-only ledger properties at the database level and continuously verify balance integrity.
- **Deliverables:**
  - PostgreSQL trigger function on `ledger_entries` that raises an exception on `UPDATE` or `DELETE`.
  - `app/services/reconciliation.py` (**CORE LOGIC**):
    - Invariant 1: For each account, `balance == SUM(credits) - SUM(debits)`.
    - Invariant 2: For each transaction, `SUM(entries) = 0`.
    - Returns comprehensive audit report detailing status of every account and any detected drift.
  - API endpoints: `POST /reconciliation/run` and `GET /reconciliation/status`.
  - Test Drill: Deliberately tamper with an account balance directly in SQL and verify that the reconciliation engine immediately flags the discrepancy.

### Phase 5: Transactional Outbox & AI Transaction Categorization
- **Goal:** Asynchronously categorize transaction memos using Google Gemini LLM without adding latency or risk to the payment path.
- **Deliverables:**
  - Insert `outbox` record atomically within the transfer transaction.
  - `app/workers/outbox_worker.py`: background polling loop using `SELECT ... FOR UPDATE SKIP LOCKED`.
  - `app/services/categorizer.py`: Gemini client calling Google GenAI SDK behind an abstract protocol.
  - Pydantic schema validation for AI output (categories: `Food & Dining`, `Transportation`, `Utilities`, `Entertainment`, `Payroll`, `Transfer`, etc.).
  - Resilience: exponential backoff retry up to 3 attempts, with safe fallback to `UNCATEGORIZED` on timeout or invalid JSON.
  - Fake LLM implementation for deterministic unit and integration tests.
  - Accuracy evaluation on a dataset of 100 sample transaction memos.

### Phase 6: Payment Realism (Card Lifecycle & Velocity Fraud Rules)
- **Goal:** Add industry-standard payment primitives: authorizations, holds, captures, refunds, and rate limits.
- **Deliverables:**
  - Card lifecycle state machine: `AUTHORIZED` -> `CAPTURED` -> `SETTLED`, `VOIDED`, `REFUNDED`.
  - Balance holds: authorization decreases *available balance* while leaving *booked ledger balance* unchanged until capture.
  - Velocity fraud rule: reject transfers if an account exceeds *N* transfers per *M* seconds or exceeds daily cumulative volume limits.
  - Unit and integration tests covering every valid state transition and rejecting all invalid transitions.

### Phase 7: Real-Time Web Auditor Frontend
- **Goal:** Provide a responsive, high-aesthetic web dashboard for interacting with and demonstrating the ledger in real-time.
- **Deliverables:**
  - `app/static/index.html`, `css/style.css`, `js/app.js`, `js/api.js`.
  - Aesthetic: Dark mode glassmorphism, modern typography (Outfit/Inter), crisp micro-animations, color-coded debit/credit badges.
  - Feature 1: **Live Account & Ledger Explorer** (view all accounts, balances, and real-time ledger entries).
  - Feature 2: **Interactive Transfer Terminal** (execute transfers, generate idempotency keys, simulate duplicate requests with one click).
  - Feature 3: **Reconciliation Dashboard** (run live audit, view mathematical proofs, test balance tampering detection).
  - Feature 4: **AI Outbox Feed** (observe transaction memos being picked up and categorized asynchronously).
  - Feature 5: **Card Lifecycle Simulator** (authorize hold -> capture / void / refund).

### Phase 8: Benchmarks & Empirical Validation
- **Goal:** Measure real-world performance under high concurrency and document actual numbers.
- **Deliverables:**
  - k6 load test scripts measuring throughput (req/s) and latency percentiles (p50, p95, p99).
  - Baseline comparison 1: Synchronous inline AI call vs. asynchronous transactional outbox.
  - Baseline comparison 2: Ordered row locks vs. unordered row locks (demonstrating deadlock frequency).
  - Record verified metrics, hardware specifications, and statistical spreads (median & range across >= 3 runs) in `docs/RESULTS.md`.

### Phase 9: Hardening, Observability & Final Packaging
- **Goal:** Finalize production readiness, observability, comprehensive documentation, and interview preparation.
- **Deliverables:**
  - Structured JSON logging with request correlation IDs (`X-Request-ID`).
  - `/metrics` endpoint with Prometheus metrics.
  - `README.md` with Mermaid architecture diagram, quickstart instructions, curl examples, tradeoffs, limitations, and PCI tokenization guidance.
  - Finalized resume bullets with verified measured metrics.
  - `docs/WALKTHROUGH.md` containing a 5-file code tour and a 10-minute interview defense script.

---

## 5. Beginner-Friendly Teaching Strategy

For each phase, the companion `docs/LEARNING_NOTES.md` will explain:
1. **The Plain-English Concept:** What real-world problem does this solve? (e.g., why bank transfers need double-entry accounting).
2. **The "Why":** What catastrophic bug happens if you don't do this? (e.g., race conditions allowing two ATMs to withdraw the same $100 simultaneously).
3. **Core File Walkthrough:** Line-by-line explanation of the most critical file in that phase.
4. **3 Likely Interview Questions & Model Answers:** Exactly how to explain this mechanism to a senior engineering interviewer.
