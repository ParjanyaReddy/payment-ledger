# System Codebase Walkthrough & Interview Defense Guide

This document is designed for technical interview preparation. It guides an engineer through reading the codebase in the optimal chronological order and provides a complete 10-minute presentation script and technical defense for senior engineering interviews.

---

## 1. Optimal Code Reading Order (The 6 Core Files)

To understand this system completely within 25 minutes, read these 6 files in this exact sequence:

```mermaid
graph TD
    A[1. models/account.py & ledger_entry.py<br/>Schema & Invariant Constraints] --> B[2. services/transfer_service.py<br/>Ordered Row Locking & Double-Entry Engine]
    B --> C[3. services/idempotency.py<br/>Race-Safe Atomic Claim Flow]
    C --> D[4. workers/outbox_worker.py<br/>SKIP LOCKED Transactional Outbox]
    D --> E[5. services/card_service.py<br/>Card Hold & Settlement Lifecycle]
    E --> F[6. services/reconciliation.py<br/>Continuous Mathematical Invariant Auditor]
```

### File 1: `app/models/account.py` & `app/models/ledger_entry.py`
- **What it does:** Defines the core financial schema, `NUMERIC(18,2)` exact decimal storage, account versioning, and database-level integrity constraints.
- **The Bug it Prevents:** Floating-point rounding errors (e.g. `0.1 + 0.2 = 0.30000000000000004`) and negative account overdrafts via `CheckConstraint("balance >= 0")`.
- **Key Insight:** `ledger_entries` is protected by a PostgreSQL database trigger (`prevent_ledger_entry_mutation`) that aborts any raw `UPDATE` or `DELETE` with SQLSTATE `23505`. The ledger is physically append-only.

### File 2: `app/services/transfer_service.py`
- **What it does:** Core financial movement engine that executes atomic double-entry transfers with deterministic row-level locking.
- **The Bug it Prevents:** Concurrency deadlocks (`40P01`) under bidirectional opposing transfers (`A -> B` and `B -> A`).
- **Key Insight:** Sorts account UUIDs ascending (`sorted_ids = sorted([from_id, to_id])`) before issuing `SELECT ... FOR UPDATE`. All concurrent transactions acquire locks in identical global order, eliminating the circular wait condition.

### File 3: `app/services/idempotency.py`
- **What it does:** Race-safe request deduplication engine using an atomic claim pattern inside the same database transaction.
- **The Bug it Prevents:** Double-charging when 50 concurrent requests hit the API simultaneously with the identical idempotency key, or silent tampering if a client reuses an idempotency key with a modified amount.
- **Key Insight:** Uses PostgreSQL `INSERT INTO idempotency_keys ... ON CONFLICT DO NOTHING`. Exactly 1 request wins the insert and executes the transfer; the other 49 concurrent requests wait on row locks and receive the cached 201 response. If the payload's SHA-256 hash doesn't match the original, it returns `HTTP 422 Unprocessable Content`.

### File 4: `app/workers/outbox_worker.py`
- **What it does:** Polls pending transactional outbox events using `SELECT ... FOR UPDATE SKIP LOCKED` and delivers them to the Gemini AI categorization service with exponential backoff.
- **The Bug it Prevents:** Dual-write inconsistencies (database commits but external API call fails, or external call succeeds but database transaction rolls back) and thread lock contention among parallel workers.
- **Key Insight:** The transfer transaction writes both the ledger entries and the outbox row in a single ACID commit. Transfer response latency drops from ~368ms down to ~9.9ms (36.6x faster) because the payment path never awaits external networks.

### File 5: `app/services/card_service.py`
- **What it does:** Implements two-phase retail settlement: `AUTHORIZED` (hold balance) &rarr; `CAPTURED` (settle ledger transfer) or `VOIDED` (cancel hold) &rarr; `REFUNDED` (reverse double-entry).
- **The Bug it Prevents:** Overdrafting authorized funds via direct transfers while holds are open.
- **Key Insight:** Spendable balance is calculated as `available_balance = balance - holds`. Placing a card authorization modifies holds without writing ledger entries. Settling (capture) converts the hold into permanent double-entry ledger records.

### File 6: `app/services/reconciliation.py`
- **What it does:** Continuous background audit engine verifying formal mathematical invariants across all accounts and transactions in a single batch SQL query.
- **The Bug it Prevents:** Undetected silent database corruption from rogue administrator scripts, hardware bit-flips, or unverified manual updates.
- **Key Insight:** Verifies two strict financial invariants:
  1. $\forall \text{account}: \text{Cached\_Balance} = \text{Initial\_Balance} + \sum(\text{Credits}) - \sum(\text{Debits})$
  2. $\forall \text{transaction}: \sum(\text{Credits}) - \sum(\text{Debits}) = 0.00$

---

## 2. 10-Minute Technical Interview Presentation Script

### Act 1: The Problem with Naive Ledgers (Minutes 0:00 – 2:00)
> *"Most software engineers build ledgers by adding a `balance` column to a `users` table and executing `UPDATE users SET balance = balance - 10 WHERE id = 1`. In high-scale financial systems, this approach fails in four catastrophic ways:
> 1. **No Audit Trail:** You only know the current state, not how you arrived there.
> 2. **Rounding Drift:** Using standard floating-point numbers silently destroys fractional cents.
> 3. **Concurrency Deadlocks:** Parallel transfers going in opposite directions (`A -> B` and `B -> A`) cause circular wait deadlocks in PostgreSQL.
> 4. **Network Retries:** An idempotency retry can easily double-charge a user if deduplication isn't atomically tied to the database transaction.
>
> I built this payment ledger to solve these fundamental financial engineering challenges using mathematically proven double-entry bookkeeping, append-only integrity triggers, and deterministic row locking."*

### Act 2: Concurrency & Invariant Enforcement (Minutes 2:00 – 5:00)
> *"The core transfer engine enforces three mathematical guarantees:
> First, **zero floating-point math**. All monetary values are strictly represented as decimal strings at API boundaries and stored as PostgreSQL `NUMERIC(18,2)`.
>
> Second, **deadlock elimination**. If Account A transfers to B while B transfers to A, naive code locks A then B in one thread, and B then A in the other. To eliminate this, my engine sorts the account UUIDs ascending before acquiring pessimistic row locks via `SELECT ... FOR UPDATE`. In our benchmarks running 100 concurrent opposing transfers, this dropped the deadlock rate from **95.0% down to exactly 0.0%**.
>
> Third, **conservation of money**. Every transaction writes exactly two immutable ledger entries—a debit and a credit of identical magnitude. PostgreSQL database check constraints enforce `balance >= 0`, and an append-only database trigger blocks any `UPDATE` or `DELETE` on historical ledger entries. In stress tests running 200 concurrent requests against a $50 balance, exactly 50 transfers were approved, 150 were rejected, and the balance remained strictly $0.00."*

### Act 3: Asynchronous Outbox & Real-World Realism (Minutes 5:00 – 7:30)
> *"In real banking systems, transfers must trigger external notifications, analytics, or AI categorization. Calling an external LLM like Gemini synchronously inside the payment transaction would hold database row locks for 350 to 700 milliseconds, choking throughput.
>
> To solve this, I implemented the **Transactional Outbox pattern**. The transfer endpoint commits the financial records and writes an outbox event in the same ACID transaction. An asynchronous background worker uses `SELECT ... FOR UPDATE SKIP LOCKED` to process events concurrently with zero lock contention. In our empirical benchmarks, this reduced median transfer latency from **368ms down to 9.93ms—a 36.6x performance improvement**.
>
> Additionally, I modeled retail card realism through a two-phase settlement state machine (`AUTHORIZED`, `CAPTURED`, `VOIDED`, `REFUNDED`) with available balance holds and rolling velocity fraud limits."*

### Act 4: Observability, Auditor UI & Benchmark Results (Minutes 7:30 – 10:00)
> *"For production operations, the system exposes structured JSON logs with propagated `X-Request-ID` headers and Prometheus `/metrics` tracking request duration histograms and financial counters.
>
> I also built a real-time web auditor dashboard inspired by modern fintech design systems (Figr and Purrweb Cashline). It visualizes accounts, provides an interactive Transfer Terminal with one-click idempotency replay and tampering drills, and features an integrated Match Proof inspector drawer that verifies double-entry receipts.
>
> Finally, every metric in our documentation was measured empirically on PostgreSQL 18 with 3 test runs: k6 sustained 46+ req/s under 20-VU concurrent load with a 0.00% error rate and zero drift detected."*

---

## 3. Senior Engineer Interview Defense & Tough Q&A

### Q1: Why did you choose pessimistic row locking (`SELECT ... FOR UPDATE`) over optimistic concurrency control (OCC with versions)?
**Defense Answer:**
> *"Optimistic Concurrency Control (OCC) works well when conflict rates are very low (under 1–2%). However, in high-volume payment ledgers (such as hot merchant accounts or payroll accounts receiving hundreds of simultaneous debits/credits), OCC causes massive retry storms because almost every transaction fails its version check and must roll back and re-execute. This burns database CPU and amplifies latency.
> 
> Pessimistic row locking queues conflicting transactions efficiently at the database row level without rolling back valid work. Furthermore, by enforcing canonical lock ordering (`min(from, to) -> max(from, to)`), we guarantee zero deadlocks while holding locks for only ~9.9ms."*

---

### Q2: What happens if the Outbox worker crashes midway through categorizing a transaction?
**Defense Answer:**
> *"The outbox worker is designed for crash resilience and at-least-once delivery:
> 1. When a worker selects pending rows, it uses `SELECT ... FOR UPDATE SKIP LOCKED`, which locks only the records it is currently processing without blocking other worker threads.
> 2. The outbox record maintains an `attempts` counter and a `status` column (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`).
> 3. If the worker process abruptly crashes or times out, its database transaction automatically rolls back, releasing the row lock. Another worker will pick up the record on the next polling cycle.
> 4. If an external service repeatedly errors, the worker uses exponential backoff and safely falls back to a deterministic `UNCATEGORIZED` label after 3 failed attempts."*

---

### Q3: How does your idempotency implementation handle 50 concurrent duplicate requests?
**Defense Answer:**
> *"We use an atomic database-level claim pattern rather than a distributed lock or separate cache:
> 1. When requests arrive with the same `Idempotency-Key` header, each thread attempts `INSERT INTO idempotency_keys (key, request_hash, status) VALUES (...) ON CONFLICT (key) DO NOTHING`.
> 2. Because PostgreSQL serializes unique index conflicts, exactly 1 thread inserts the row and receives row count = 1. This thread proceeds to execute the transfer.
> 3. The other 49 threads receive row count = 0 (conflict). They execute `SELECT ... WHERE key = :key FOR UPDATE`, which pauses them until the winning thread commits.
> 4. Once the winning thread commits the transfer and stores the response payload, the waiting threads wake up, read the cached status code and body, and return `X-Idempotent-Replay: true`. Zero duplicate transfers or charges are ever created."*

---

### Q4: How do you prevent ledger tampering by an insider or rogue database script?
**Defense Answer:**
> *"We implement defense-in-depth across three architectural layers:
> 1. **Database-Level Immutability:** A PostgreSQL trigger (`prevent_ledger_entry_mutation`) intercepts any `UPDATE` or `DELETE` statement targeting `ledger_entries` and raises an uncatchable exception.
> 2. **Continuous Reconciliation Invariant:** The reconciliation service continuously computes $\sum(\text{Credits}) - \sum(\text{Debits})$ across historical entries and compares it against the cached `accounts.balance`. If any row was silently modified outside the ledger, the auditor flags the exact account, amount of drift, and diagnostic reason.
> 3. **Cryptographic Payload Hashes:** Every transfer and idempotency record stores a SHA-256 hash of the exact request body. If a tampered payload attempts to replay under an existing key, it is rejected with `HTTP 422 Unprocessable Content`."*

---

### Q5: Why is PCI DSS tokenization described rather than having actual credit card numbers stored in the database?
**Defense Answer:**
> *"Storing Primary Account Numbers (PANs) or CVVs directly in an application database places the entire infrastructure into the highest PCI DSS compliance scope (Level 1), requiring certified hardware security modules (HSMs), key rotation ceremonies, and expensive annual audits.
>
> In modern financial engineering (Stripe, Modern Treasury, Adyen), client card details never touch backend servers. Instead, card data is tokenized in the user's browser directly via client-side SDKs and exchanged for an opaque token (e.g. `tok_visa_1234`). Our ledger stores this token alongside an internal `account_id`, maintaining full isolation between payment authorization workflows and sensitive cardholder data environments."*
