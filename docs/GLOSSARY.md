# Engineering & Payment Systems Glossary

Plain-English definitions of terms and architectural concepts used in this project.

---

### Double-Entry Bookkeeping
An accounting principle dating back to the Renaissance: every financial transaction must record at least two offsetting entries—a debit and an credit.
- **Rule:** Total Debits = Total Credits, meaning the sum of all entries for a single transaction equals zero (`SUM(entries) = 0`).
- **Why it matters:** Money cannot appear from nowhere or vanish. If Account A transfers $50 to Account B, Account A is debited $50 and Account B is credited $50.

### Double-Entry Invariant
The mathematical law of the payment ledger: for every transfer transaction $T$, $\sum_{e \in T} \text{amount}_e \times \text{direction}_e = 0$, where credits add and debits subtract.

### Cached Projection
A derived value stored for fast read performance that can always be completely recomputed from the underlying source of truth.
- **In this system:** The `balance` column in the `accounts` table is a cached projection. The absolute ground truth is the complete log of immutable rows in `ledger_entries`.

### Check Constraint
A database-level rule enforced directly by PostgreSQL that verifies every row satisfies a boolean condition before allowing an `INSERT` or `UPDATE`.
- **Examples in our system:** `CHECK (balance >= 0)`, `CHECK (amount > 0)`, `CHECK (direction IN ('DEBIT', 'CREDIT'))`.
- **Why it matters:** Even if application code has a bug, the database physically rejects corrupting changes.

### Pessimistic Locking (`SELECT ... FOR UPDATE`)
A concurrency control strategy where a transaction locks database rows as soon as it reads them, preventing other concurrent transactions from modifying or reading those rows until the lock is released upon commit or rollback.
- **Why it matters:** Prevents "check-then-act" race conditions where two simultaneous transactions check that a user has $100 and both withdraw $100.

### Circular Wait & Deadlock
A situation in concurrent systems where two or more processes are unable to proceed because each is waiting for the other to release a lock.
- **Classic example:** Transaction 1 locks Account A and tries to lock Account B. Simultaneously, Transaction 2 locks Account B and tries to lock Account A. Both are stuck forever.

### Deterministic Lock Ordering
A technique for eliminating deadlocks by requiring all transactions to acquire locks according to a global, total ordering.
- **In our system:** Before locking accounts in a transfer, account IDs are sorted: `sorted([from_id, to_id])`. All transactions acquire locks in ascending UUID order. Since all transactions request locks in the same sequence, circular wait is mathematically broken.

### Foreign Key & Referential Integrity (`RESTRICT` vs. `CASCADE`)
A foreign key links a column in one table to the primary key of another table, ensuring that the referenced row actually exists.
- **`ON DELETE RESTRICT`:** Prevents an account from being deleted if it still has transactions or ledger entries associated with it. Used in financial ledgers to prevent data loss.
- **`ON DELETE CASCADE`:** Automatically deletes dependent rows if the parent is deleted. Used for temporary task queues like `outbox` when a parent transaction is removed.

### Database Index
A data structure (usually a B-Tree) that allows PostgreSQL to locate specific rows in $O(\log N)$ time rather than performing a full table scan ($O(N)$).
- **In our system:** Added on `ledger_entries(account_id)`, `ledger_entries(transaction_id)`, and `outbox(status, created_at)`.

### ACID Guarantees
The four fundamental properties of relational databases that guarantee database transactions are processed reliably:
1. **Atomicity:** All parts of a transaction succeed, or the entire transaction is rolled back. (e.g., both debit and credit entries are written together, or neither is).
2. **Consistency:** Any transaction will bring the database from one valid state to another, maintaining all constraints (e.g., balance cannot be negative).
3. **Isolation:** Concurrent execution of transactions leaves the database in the same state that would have been obtained if the transactions were executed sequentially.
4. **Durability:** Once a transaction has been committed, it remains committed even in the event of a system crash or power outage.

### Idempotency
An operation is idempotent if performing it once produces the exact same result as performing it multiple times without unintended side effects.
- **In payments:** If a network timeout occurs while paying, the client re-sends the request with the same `Idempotency-Key`. The server detects the duplicate and returns the cached result without charging the card twice.

### Transactional Outbox Pattern
A reliable distributed systems pattern used to publish events or execute asynchronous work without dual-write inconsistencies.
- **Mechanism:** Instead of calling an external service (like an LLM or payment gateway) directly inside the payment transaction, a task row is written to an `outbox` table in the same DB transaction. A background worker polls the table with `SKIP LOCKED` and performs the work reliably.

### Reconciliation
An automated auditing process that compares two sets of records to ensure they are in agreement.
- **In this system:** An automated job scans all accounts and verifies that `balance == SUM(credits) - SUM(debits)`. If any manual tampering or drift occurred, an alert is raised immediately.

### Liveness vs. Readiness Probes
- **Liveness (`/health`):** Verifies that the application process is alive and responding to HTTP requests. If it fails, the container orchestrator restarts the process.
- **Readiness (`/ready`):** Verifies that the application is ready to accept user traffic by checking external dependencies (such as active PostgreSQL connectivity).
