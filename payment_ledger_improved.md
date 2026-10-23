# Payment Ledger & AI Auditor (Improved Guide)

A double-entry payment ledger API built for **correctness under concurrency**. The goal is not features, it is *provable* guarantees: no overdrafts, no duplicate charges, no money created or destroyed.

**Stack:** Python, FastAPI, PostgreSQL, SQLAlchemy (async), Docker Compose, pytest, k6.
(Optional: re-implement the core transfer path in Java/Spring Boot to match Visa's likely stack. Check the job posting.)

---

## 0. Ground Rules

- **Write the core yourself:** locking, idempotency, ledger entries, reconciliation. Use AI for boilerplate, config, and test scaffolding only.
- **Every claim needs a test.** If you can't show a test that proves it, don't put it on your resume.
- **Never use Float for money.** Use `NUMERIC(18,2)` or integer minor units (cents).

---

## 1. Architecture

```
Client -> FastAPI -> PostgreSQL (accounts, ledger_entries, transactions, idempotency_keys, outbox)
                          |
                    Outbox Worker -> LLM API -> updates transactions.ai_category
```

### Double-entry invariant
Every transfer writes **two immutable `ledger_entries` rows** (a debit and a credit) in one DB transaction. For every transaction, `SUM(entries) = 0`. Balances in `accounts` are a cached projection that can always be recomputed from entries.

---

## 2. Schema

```sql
accounts(
  id UUID PK,
  currency CHAR(3) NOT NULL,
  balance NUMERIC(18,2) NOT NULL CHECK (balance >= 0),   -- cached projection
  version INT NOT NULL DEFAULT 0
)

transactions(
  id UUID PK,
  from_account_id UUID FK, to_account_id UUID FK,
  amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  status TEXT NOT NULL,            -- PENDING | COMPLETED | FAILED
  memo TEXT,
  ai_category TEXT,                -- filled asynchronously
  created_at TIMESTAMPTZ
)

ledger_entries(                    -- append-only, never UPDATE or DELETE
  id UUID PK,
  transaction_id UUID FK,
  account_id UUID FK,
  direction TEXT NOT NULL,         -- DEBIT | CREDIT
  amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
  created_at TIMESTAMPTZ
)

idempotency_keys(
  key UUID PK,
  request_hash TEXT NOT NULL,      -- hash of method + path + body
  status TEXT NOT NULL,            -- IN_PROGRESS | COMPLETED
  response_code INT,
  response_body JSONB,
  created_at TIMESTAMPTZ
)

outbox(                            -- durable job queue for AI categorization
  id UUID PK,
  transaction_id UUID FK,
  status TEXT NOT NULL,            -- PENDING | DONE | FAILED
  attempts INT DEFAULT 0,
  created_at TIMESTAMPTZ
)
```

Add a DB-level guard (trigger or revoked privileges) so `ledger_entries` rows cannot be updated or deleted.

---

## 3. Core Mechanisms

### A. Concurrency: row-level locking with ordered locks
1. Begin transaction.
2. Lock **both** accounts with `SELECT ... FOR UPDATE`, **ordered by account ID** (prevents deadlocks, since all transactions lock in the same order).
3. Check sufficient funds on the freshly locked row.
4. Insert transaction row + two ledger entries, update both balances.
5. Commit.

Know the alternatives and tradeoffs: optimistic locking (`version` column, retry on conflict), `SERIALIZABLE` isolation (retry on serialization failure), and why you chose pessimistic locking (high contention on hot accounts, simple reasoning).

### B. Idempotency (race-safe version)
The naive "check, then process" flow has a race: two identical requests can both see "key not found."

1. In the same DB transaction, run
   `INSERT INTO idempotency_keys (key, request_hash, status) VALUES (...) ON CONFLICT DO NOTHING`.
2. If the insert **succeeded**, you own the key: process the transfer, store the response, mark `COMPLETED`, commit.
3. If it **conflicted**, read the existing row:
   - `request_hash` differs -> return **422** (same key, different payload).
   - `status = COMPLETED` -> return the stored response.
   - `status = IN_PROGRESS` -> return **409** (or wait briefly and retry).
4. Run a cleanup job to expire old keys (e.g. 24h).

### C. AI categorizer via transactional outbox
`BackgroundTasks` are lost if the process crashes. Instead:
1. In the same transaction as the transfer, insert an `outbox` row.
2. A separate worker polls with `SELECT ... FOR UPDATE SKIP LOCKED`, calls the LLM, validates output against a Pydantic schema, and updates `ai_category`.
3. On timeout, invalid JSON, or API failure: retry with backoff up to N attempts, then set `UNCATEGORIZED`. The payment is never affected.

Log categorization accuracy on a small hand-labeled set (e.g. 100 memos) so you have a real number.

### D. Reconciliation job
A scheduled job that, for every account, checks `balance == SUM(credits) - SUM(debits)`, and for every transaction, checks entries sum to zero. Any mismatch raises an alert/log. Add a test that deliberately corrupts a balance and confirms the job catches it.

---

## 4. Payment Realism Add-ons (pick 1-2 after the core works)

- **Card lifecycle state machine:** `AUTHORIZED -> CAPTURED -> SETTLED`, with `VOIDED` and `REFUNDED`. Authorization places a *hold* (reduces available balance, not ledger balance). Enforce valid transitions only.
- **Velocity fraud rule:** reject if an account makes more than N transfers in M seconds, or exceeds a daily amount cap. Rule-based is enough; explain how you'd extend it with ML.
- **README section on PCI/tokenization:** explain you would never store raw card numbers and would use tokens. Describe, don't fake, the implementation.
- **Multi-currency:** reject cross-currency transfers, or model FX as separate paired transactions.

---

## 5. Build Roadmap

| Phase | You write | AI may help with |
|---|---|---|
| 1. Setup | Schema, migrations (Alembic) | Docker Compose, FastAPI scaffolding |
| 2. Ledger core | Transfer logic, lock ordering, entries | Pydantic models, route boilerplate |
| 3. Idempotency | The ON CONFLICT flow, hash check | Cleanup job |
| 4. Reconciliation | The invariant queries | Scheduler wiring |
| 5. Outbox + AI | Worker loop, retry/fallback logic | LLM SDK call, prompt iteration |
| 6. Tests + benchmarks | Test design and assertions | k6 script scaffolding |
| 7. Hygiene | Architecture diagram, tradeoffs | CI YAML, logging config |

---

## 6. Test Plan (this is where your metrics come from)

| Test | Assertion | Metric to record |
|---|---|---|
| 200 concurrent transfers from one account with balance for only 50 | Exactly 50 succeed, final balance >= 0 | `[X]` concurrent requests, 0 overdrafts |
| Many random transfers among 20 accounts | Total money before == after | `[X]` transfers, 0 units of drift |
| Same idempotency key sent 50x concurrently | Exactly 1 transaction, 49 identical replays | `[X]` duplicates prevented |
| Same key, different body | 422 returned | |
| Opposing transfers A->B and B->A in parallel, 1000x | No deadlock | 0 deadlocks |
| Kill the app mid-transfer | No partial entries, no lost money | |
| LLM returns garbage / times out | Payment succeeds, category = UNCATEGORIZED | |
| Corrupt a balance manually | Reconciliation job flags it | |

### Benchmarks (k6)
Record: throughput (transfers/sec), p50/p95/p99 latency, at `[X]` concurrent users, on your stated hardware. Compare *with and without* the AI step in the request path to quantify why it's async. Compare lock-ordering vs. no ordering to show the deadlock rate.

---

## 7. Repo Checklist

- [ ] `docker-compose up` runs everything
- [ ] CI (GitHub Actions) runs the tests on every push
- [ ] README: architecture diagram, how to run, **design tradeoffs** section, **known limitations** section
- [ ] Structured JSON logging with a request/transaction ID
- [ ] `/metrics` endpoint (Prometheus format) or at least a health endpoint
- [ ] A results table of your test and benchmark numbers

---

## 8. Interview Defense

- **Why Decimal, not Float?** Binary floats can't represent most decimals exactly (0.1 + 0.2 = 0.30000000000000004). Use `NUMERIC` or integer cents.
- **Deadlocks?** Two transactions locking the same accounts in opposite order. Fixed by always locking in sorted ID order. Postgres also detects deadlocks and aborts one, so retry logic is a safety net.
- **Two identical requests arrive at the same instant?** The `ON CONFLICT` insert on the idempotency key's primary key serializes them: one wins and processes, the other sees the row and replays or gets a 409.
- **Why not just check the balance, then update?** Check-then-act race. Another transaction can change the balance in between. The lock makes check and update atomic.
- **Why an outbox, not BackgroundTasks?** Durability. The job is written in the same transaction as the payment, so it survives crashes. Tradeoff: at-least-once processing, so the worker must be idempotent.
- **Why is the stored balance safe if entries are the truth?** It's a projection updated in the same transaction, verified by the reconciliation job.
- **How would you scale this?** Shard by account ID, read replicas for reporting, partition `ledger_entries` by time, hot-account contention strategies. Be honest that you haven't built these.
- **What would you change?** Have one ready (e.g. "I'd move to integer cents," "I'd add per-account sequence numbers to entries").

---

## 9. Resume Bullets (fill in only measured values)

- Built a double-entry payment ledger in Python/FastAPI/PostgreSQL with immutable ledger entries and a reconciliation job; verified **0 balance drift across `[X]` randomized concurrent transfers**.
- Eliminated overdraft race conditions using ordered `SELECT FOR UPDATE` row locks; **0 overdrafts and 0 deadlocks in `[X]` concurrent requests** against a contended account.
- Implemented race-safe API idempotency (`ON CONFLICT` key claim + request hashing); **`[X]` concurrent duplicate requests produced exactly 1 charge**.
- Moved LLM transaction categorization to a transactional-outbox worker with schema validation and fallback; kept **p99 transfer latency at `[X]` ms vs `[Y]` ms** with inline calls, at `[Z]` categorization accuracy on a hand-labeled set.
- Sustained **`[X]` transfers/sec at p99 `[Y]` ms** (k6, `[N]` users, `[hardware]`), with CI-enforced tests (`[X]%` coverage).

> If a bullet's number isn't measured, delete the number and describe the mechanism instead. Never guess.
