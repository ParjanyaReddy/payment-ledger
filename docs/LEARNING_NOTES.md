# Beginner-Friendly Learning Notes & Interview Prep

---

## Phase 0: Scaffolding, Architecture & Async Database Wiring

### 1. Plain-English Overview
Imagine you are building a physical bank branch. Before you start moving money into safes or accepting customer deposits, you need strong foundations: the building structure, security alarms, electricity, and a ledger room.
In software engineering, Phase 0 is building that sturdy foundation:
- Setting up the project folder structure so every file has one clear job.
- Wiring up a fast, asynchronous connection to our database (PostgreSQL).
- Adding health checks (`/health` and `/ready`) so we know the system is alive.
- Putting automated tests and quality checks (`black`, `ruff`, `mypy`) in place so our code remains clean, readable, and bug-free from Day 1.

---

### 2. Walkthrough of the Most Important File: `app/db.py`
In `app/db.py`, we initialize the asynchronous database engine:

```python
# 1. Create the async engine
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,   # Tests connection before using it
    pool_size=10,         # Maximum 10 permanent database connections
    max_overflow=20       # Up to 20 temporary extra connections during spikes
)

# 2. Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False, # Keeps loaded objects in memory after commit
    autocommit=False,       # Explicitly control when transactions commit
    autoflush=False
)
```

**What is happening here?**
- `create_async_engine`: Instead of blocking the whole server whenever we talk to PostgreSQL, `asyncpg` lets Python handle thousands of simultaneous requests on a single thread while waiting for database queries to return.
- `pool_pre_ping=True`: If a database connection goes stale (e.g., PostgreSQL restarted), the pool tests the connection with a quick ping first instead of throwing a random 500 error to a paying user.
- `AsyncSessionLocal`: A session is your "workspace" for a single HTTP request. When the request starts, you open a session; when the request finishes, the session automatically commits or rolls back and returns the connection to the pool.

---

### 3. The One Catastrophic Bug This Prevents
**The Database Connection Leak & Cascade Failure.**
- **The Bug:** If you create new database connections on every request without a connection pool or fail to close them in a `finally` block, your database will run out of connections (`FATAL: remaining connection slots are reserved for non-replication superuser connections`).
- **The Consequence:** Every single user trying to open the app or pay receives an immediate server crash.
- **How Phase 0 Prevents It:** We use `create_async_engine` with a bounded connection pool and `get_db()` with `async with` context management to guarantee connections are returned to the pool even if an error occurs.

---

### 4. Three Likely Interview Questions & Short Answers

#### Q1: "Why did you separate the `/health` and `/ready` endpoints instead of having just one `/status` endpoint?"
**Model Answer:**
> "In production orchestration (like Kubernetes or Docker Swarm), liveness and readiness serve two very different purposes.
>
> The **liveness probe** (`/health`) checks if the Python process itself is alive. If the app is stuck in an infinite loop or frozen, the liveness probe fails and orchestrators restart the container.
>
> The **readiness probe** (`/ready`) checks if external dependencies—specifically PostgreSQL—are reachable. If PostgreSQL has a temporary network hiccup, we do *not* want the container restarted (which causes reboot loops and worsens traffic spikes); we just want the load balancer to temporarily stop routing traffic to it until PostgreSQL recovers."

---

#### Q2: "Why use `asyncpg` and asynchronous SQLAlchemy 2.0 instead of standard synchronous database queries?"
**Model Answer:**
> "Payment and financial APIs spend over 90% of their request time waiting for database I/O—like acquiring row locks, inserting ledger entries, and checking balances.
>
> In a synchronous framework, while a thread is waiting for the database, it is completely blocked from doing anything else. With Python's async event loop and `asyncpg`, a single CPU core can initiate a database query for Request A, pause that coroutine, handle Request B, and resume Request A as soon as PostgreSQL replies. This dramatically increases concurrent throughput without having to run hundreds of heavy OS threads."

---

#### Q3: "Why did you choose decimal strings instead of floating-point numbers or integer cents in your API?"
**Model Answer:**
> "Floating-point numbers use binary representation (IEEE-754), which cannot accurately represent many base-10 decimals like `0.1` or `0.2`, leading to drift like `0.30000000000000004` that will fail ledger reconciliation.
>
> While integer minor units (like storing $10.00 as 1000 cents) are common, passing amounts as decimal strings (e.g. `\"10.00\"`) prevents JavaScript and JSON parsers from accidentally converting numbers into IEEE-754 floats while remaining human-readable across all audit logs, client SDKs, and user dashboards."

---

## Phase 1: Data Model, Migrations & Account Management

### 1. Plain-English Overview
In a bank, you cannot just trust application code to do the right thing; you must put physical steel guards inside the database.
In Phase 1, we defined the 5 foundational tables of our payment ledger and established **database-level invariants**:
1. An account balance can **never** be negative (`CHECK balance >= 0`).
2. Transfer amounts can **never** be zero or negative (`CHECK amount > 0`).
3. Ledger entries can only move in valid directions (`CHECK direction IN ('DEBIT', 'CREDIT')`).
4. Financial precision is guaranteed with exact `NUMERIC(18,2)`.
5. We set up Alembic migrations so schema changes are versioned, repeatable, and automated.

---

### 2. Walkthrough of the Most Important File: `app/models/account.py`
In `app/models/account.py`, we define the `accounts` table:

```python
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("balance >= 0", name="check_account_balance_non_negative"),
    )
```

**What makes this so special?**
- Notice `CheckConstraint("balance >= 0")`: Even if an attacker finds a zero-day exploit in our API or a rogue developer writes a bug that tries to subtract $1,000,000 from a $100 balance, **PostgreSQL itself rejects the transaction at the engine level** with an `IntegrityError`.
- `Numeric(18, 2)`: Stored as exact binary-coded decimal digits inside PostgreSQL storage pages, not IEEE-754 floating points.

---

### 3. The One Catastrophic Bug This Prevents
**The Silent Overdraft via Application Bug or Data Corruption.**
- **The Bug:** Relying solely on `if account.balance >= amount` in Python code. If two threads run simultaneously or if an unexpected code branch executes, an account's balance could drop to `-$500.00`.
- **The Consequence:** The bank loses real money; financial balance sheets fail audit compliance.
- **How Phase 1 Prevents It:** The database-level check constraint `check_account_balance_non_negative` makes negative balances mathematically impossible to write into PostgreSQL.

---

### 4. Three Likely Interview Questions & Short Answers

#### Q1: "Why enforce constraints like `balance >= 0` at the database level if your API already validates it?"
**Model Answer:**
> "Defense in depth. Application-level validation is your first line of defense, but under high concurrency, race conditions can bypass application checks. Furthermore, background jobs, database migration scripts, or internal admin tools can touch the database directly.
>
> A database-level `CHECK` constraint acts as an absolute physical boundary: regardless of who or what tries to execute the `UPDATE`, PostgreSQL guarantees the constraint can never be violated, preserving data integrity."

---

#### Q2: "What is the difference between `accounts.balance` and the rows in `ledger_entries`?"
**Model Answer:**
> "In double-entry ledger architecture, `ledger_entries` is the immutable source of truth. Every money movement writes an append-only debit and credit entry that can never be updated or deleted.
>
> `accounts.balance` is a **cached projection**—a pre-aggregated snapshot stored for $O(1)$ fast lookups so we don't have to scan and sum millions of historical ledger entries every time a customer checks their balance. If `accounts.balance` was ever lost or corrupted, it could be reconstructed with 100% accuracy by summing `ledger_entries`."

---

#### Q3: "Why did you use Alembic migrations instead of `Base.metadata.create_all()`?"
**Model Answer:**
> "`Base.metadata.create_all()` is only suitable for quick prototypes because it cannot modify existing tables, alter column types, add check constraints, or track schema versions over time.
>
> Alembic provides version-controlled, reversible migration scripts (`upgrade` and `downgrade`) tracked in an `alembic_version` table. In production CI/CD pipelines, migrations can be audited in pull requests, applied incrementally without downtime, and rolled back if needed."

---

## Phase 2: Double-Entry Core & Deadlock-Free Pessimistic Locking

### 1. Plain-English Overview
Imagine two people share a single bank account that has $100. At the exact same microsecond, Person A taps their card at an ATM in New York, and Person B taps their card at an ATM in London, both attempting to withdraw $100.
If the system checks "Does the account have $100?" simultaneously for both, both checks say **YES**, and both ATMs dispense $100. The bank just lost $100 to an overdraft race condition.
Phase 2 solves this permanently:
- **Pessimistic Row Locking (`SELECT ... FOR UPDATE`):** The first request locks the account row. The second request must wait in line until the first transaction finishes.
- **Ordered Locking (Deadlock Prevention):** If Alice sends money to Bob while Bob sends money to Alice, locking accounts in arbitrary order can freeze both transactions forever in a deadlock. Sorting account IDs ensures both transactions request locks in the exact same order.
- **Strict Double-Entry:** Every transfer creates two offsetting entries (one debit, one credit), guaranteeing money is conserved.

---

### 2. Walkthrough of the Core File: `app/services/transfer_service.py`
In `app/services/transfer_service.py` (`CORE LOGIC: understand this file line by line`), we execute the transfer:

```python
# 1. Sort IDs to prevent circular wait deadlocks
sorted_ids = sorted([from_account_id, to_account_id])

# 2. Acquire exclusive row-level locks in sorted order
stmt = (
    select(Account)
    .where(Account.id.in_(sorted_ids))
    .order_by(Account.id)
    .with_for_update()
)
result = await db.execute(stmt)
locked_accounts = {account.id: account for account in result.scalars().all()}

# 3. Check sufficient funds on the locked row
if sender.balance < amount:
    raise InsufficientFundsError(...)

# 4. Atomically insert Transaction and Ledger Entries
db.add(transfer_txn)
await db.flush() # Ensure parent transaction row exists for FK constraints

db.add(debit_entry)
db.add(credit_entry)

# 5. Update cached balance projections
sender.balance -= amount
receiver.balance += amount
```

**Why this code is completely bulletproof:**
- `order_by(Account.id).with_for_update()`: Because every transaction in our system requests locks in ascending UUID order, circular wait is mathematically broken. No two transactions can ever hold a lock that the other needs while waiting for each other.
- `sender.balance < amount` happens *after* `with_for_update()`: We are inspecting the true, locked state of the balance, not a stale snapshot.
- Single atomic transaction: The transaction row, both ledger entries, and both balance updates either commit together or roll back together.

---

### 3. The One Catastrophic Bug This Prevents
**The ATM Double-Spend & The Opposing Transfer Deadlock.**
- **The Bug:** Without ordered `SELECT FOR UPDATE`, 200 concurrent requests against a $50 account would all see a positive balance and allow $200 to be spent (a $150 overdraft). Meanwhile, opposing transfers (A $\rightarrow$ B and B $\rightarrow$ A) would deadlock inside the database engine.
- **How Phase 2 Prevents It:** Our automated tests prove that under 200 simultaneous transfer requests, exactly 50 succeed, 150 fail with insufficient funds, and the final balance is exactly $0.00 with **0 overdrafts and 0 deadlocks**.

---

### 4. Three Likely Interview Questions & Short Answers

#### Q1: "Why do deadlocks happen in concurrent financial transfers, and how did you prevent them?"
**Model Answer:**
> "A deadlock occurs under a **circular wait** condition. For example, if Transfer 1 is moving funds from Account A to Account B, and Transfer 2 is moving funds from Account B to Account A:
>
> If Transfer 1 locks A and waits for B, while Transfer 2 locks B and waits for A, both transactions are blocked indefinitely until the database detects the deadlock and aborts one.
>
> We eliminate deadlocks by **enforcing a global lock acquisition order**: we sort the account IDs and lock them in ascending order (`ORDER BY id`). Regardless of transfer direction, both transactions request lock A first, then lock B. Transfer 2 cannot lock A until Transfer 1 commits, completely eliminating circular wait."

---

#### Q2: "Why choose pessimistic locking (`SELECT ... FOR UPDATE`) over optimistic locking (version column) or Serializable isolation?"
**Model Answer:**
> "Optimistic concurrency control checks a `version` number on commit. If another transaction changed the version, the transaction fails and must retry. In payment systems with **hot accounts** (like a popular merchant, payroll account, or marketplace seller), dozens of concurrent transfers hit the same account simultaneously. Under optimistic locking, high contention causes massive retry churn, high latency spikes, and wasted database CPU.
>
> Pessimistic row locking acquires the lock upfront, queues waiting transactions efficiently at the database level, and avoids retry overhead."

---

#### Q3: "How does double-entry accounting guarantee the conservation of money?"
**Model Answer:**
> "In single-entry systems, money is just an updated number in an account record. If a bug decrements one account without incrementing the other, money vanishes.
>
> In double-entry systems, every transfer writes two immutable entries: a debit and a credit of equal value. For every transaction, the net sum of entries is strictly zero ($\sum \text{entries} = 0$). By verifying that total credits equal total debits across the system, we mathematically prove that no money was created or destroyed."

---

## Phase 3: Race-Safe Idempotency & Duplicate Request Coalescing

### 1. Plain-English Overview
Imagine you are buying an expensive flight ticket online. You click "Pay Now", but your internet connection drops for 2 seconds. The browser shows a spinner or network timeout error.
You naturally click "Pay Now" again.
Without **idempotency**, you will be charged twice for two tickets.
Worse yet, imagine an eager customer rapidly double-clicking a "Transfer $500" button in their mobile app within 10 milliseconds. Two identical HTTP requests hit our servers at the exact same instant.
Phase 3 protects against both scenarios:
- **Client-Generated Key (`Idempotency-Key` header):** Every payment attempt must include a unique UUID.
- **Atomic Database Claim (`ON CONFLICT DO NOTHING`):** When two requests with the same key arrive simultaneously, PostgreSQL allows only ONE to insert the row. The loser does NOT run the transfer; it waits for the winner to finish.
- **Request Fingerprinting (SHA-256):** We hash the endpoint method, path, and request JSON body. If someone reuses an old idempotency key with different payment details (e.g., changing the amount from $10 to $1,000), we detect tampering and immediately reject it.
- **Cached Replay:** The winner stores the exact HTTP response code and body in PostgreSQL. When retried, the API returns the original receipt instantly with `X-Idempotent-Replay: true` without touching account balances.

---

### 2. Walkthrough of the Core File: `app/services/idempotency.py`
In `app/services/idempotency.py` (`CORE LOGIC: understand this file line by line`):

```python
# 1. Attempt atomic claim in PostgreSQL
stmt = (
    pg_insert(IdempotencyKey)
    .values(key=key, request_hash=request_hash, status="IN_PROGRESS")
    .on_conflict_do_nothing(index_elements=["key"])
    .returning(IdempotencyKey.key)
)
result = await db.execute(stmt)
if result.scalar_one_or_none() is not None:
    return IdempotencyClaim(is_new=True) # Winner owns execution

# 2. Loser enters poll loop for completion
while elapsed <= max_wait_seconds:
    record = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.key == key)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if record.request_hash != request_hash:
        raise IdempotencyHashMismatchError(...) # 422 if payload changed

    if record.status == "COMPLETED":
        return IdempotencyClaim(
            is_new=False,
            cached_status_code=record.response_code,
            cached_body=record.response_body
        ) # Replay cached response
    await asyncio.sleep(0.05)
```

**Why this code is completely race-safe:**
- Standard naive implementations check `SELECT * FROM keys WHERE key = X` and then `INSERT INTO keys`. Under concurrent execution, two threads both run `SELECT` at the same time, both find nothing, and both proceed to execute the transfer.
- Our implementation uses `INSERT ... ON CONFLICT (key) DO NOTHING RETURNING key`. In PostgreSQL, this is an atomic single-engine operation guaranteed by the primary key unique index. Only one transaction can win.

---

### 3. The One Catastrophic Bug This Prevents
**The Double-Charge via Network Timeout Retry or Rapid Double-Click.**
- **The Bug:** A client pays $1,000. The server successfully transfers the money, but the network drops right before sending the HTTP 201 response back. The client retries. If the server does not recognize the duplicate key, the client is charged another $1,000 ($2,000 total).
- **The Consequence:** Customer rage, disputed chargebacks, Visa/Mastercard fines, financial liability.
- **How Phase 3 Prevents It:** In our concurrency tests, firing **50 simultaneous identical requests** with the same idempotency key results in exactly 1 transaction written to the database, 1 debit, and all 50 callers receive the identical 201 receipt with 0 double-charges.

---

### 4. Three Likely Interview Questions & Short Answers

#### Q1: "Why must the idempotency record be saved in the same database and transaction as the transfer itself?"
**Model Answer:**
> "If you store idempotency keys in an external cache like Redis without two-phase commit, you face distributed state desynchronization.
>
> If Redis crashes after saving the key but before the database transfer commits, future retries will believe the payment succeeded when it never occurred. Conversely, if the transfer commits in PostgreSQL but Redis fails to save the cached response, a client retry will execute the transfer a second time (double-charge).
>
> Storing `idempotency_keys` in PostgreSQL allows the claim, the ledger entries, and the account balance updates to participate in the exact same ACID transaction."

---

#### Q2: "How do you handle a concurrent request arriving while the original request is still being processed?"
**Model Answer:**
> "There are three states:
> 1. If the key doesn't exist, we atomically claim it as `IN_PROGRESS` and execute the transfer.
> 2. If the key exists and is `COMPLETED`, we immediately return the cached status code and response payload with an `X-Idempotent-Replay: true` header.
> 3. If the key exists and is `IN_PROGRESS`, a concurrent duplicate is currently running. We briefly poll the database (e.g., up to 3 seconds) for the in-flight transaction to finish. If it completes, we return the cached result. If it times out or encounters a permanent conflict, we return HTTP 409 Conflict instructing the client to retry."

---

#### Q3: "What happens if a malicious client reuses an existing idempotency key with a completely different payload?"
**Model Answer:**
> "We compute a deterministic SHA-256 fingerprint of the HTTP method, endpoint path, and normalized JSON payload.
>
> When a conflicting key is observed, we compare the incoming hash against `idempotency_keys.request_hash`. If they do not match, we immediately reject the request with HTTP 422 Unprocessable Content. This prevents idempotency key hijacking or accidental parameter collision."

---

## Phase 4: Ledger Immutability & Automated Reconciliation

### 1. Plain-English Overview
In medieval accounting, scribes wrote transactions into physical leather-bound ledgers with permanent ink. Tearing out a page or using an ink eraser was considered a criminal act. If an error was made, you did not erase it—you recorded a corrective entry.
In modern distributed systems, data corruption can happen silently: a database migration bug, a developer manually running an `UPDATE` in pgAdmin, or a server glitch.
Phase 4 implements two layers of protection:
- **Append-Only Database Trigger:** We attached a PostgreSQL trigger function to `ledger_entries`. Even if someone connects directly to PostgreSQL with full admin privileges and tries to run `UPDATE` or `DELETE`, PostgreSQL raises an exception and aborts the command.
- **Automated Reconciliation Engine:** An auditor service that continuously verifies two mathematical invariants across the entire system:
  1. **Account Balance Invariant:** $\text{Account Balance} = \text{Initial Balance} + \sum \text{Credits} - \sum \text{Debits}$.
  2. **Double-Entry Invariant:** For every transaction, $\sum \text{Credits} = \sum \text{Debits}$.
- If even one cent drifts anywhere in the system, reconciliation immediately catches it, logs the discrepancy, and alerts operators.

---

### 2. Walkthrough of the Core File: `app/services/reconciliation.py`
In `app/services/reconciliation.py` (`CORE LOGIC: understand this file line by line`):

```python
# 1. Single-query aggregation across all accounts
account_audit_stmt = (
    select(
        Account.id, Account.currency, Account.balance, Account.initial_balance,
        func.coalesce(func.sum(case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount), else_=0)), 0),
        func.coalesce(func.sum(case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount), else_=0)), 0),
    )
    .outerjoin(LedgerEntry, Account.id == LedgerEntry.account_id)
    .group_by(Account.id, Account.currency, Account.balance, Account.initial_balance)
)

# 2. Mathematical drift check
for row in account_rows:
    acc_id, currency, actual_bal, initial_bal, total_credits, total_debits = row
    expected_bal = initial_bal + total_credits - total_debits
    drift = actual_bal - expected_bal
    if drift != 0:
        discrepancies.append(DiscrepancyDetail(drift=f"{drift:+.2f}", ...))
```

**Why this design is so scalable:**
- Instead of issuing separate database queries for every account in a loop ($O(N)$ network round-trips), we execute a single SQL `GROUP BY` query with conditional aggregation. PostgreSQL computes sums over indexed foreign keys in milliseconds.

---

### 3. The One Catastrophic Bug This Prevents
**The Silent Ledger Drift & Untraceable Money Disappearance.**
- **The Bug:** If an attacker or rogue script modifies an account's balance directly from $100.00 to $10,000.00, normal API endpoints reading `accounts.balance` would honor the fraudulent balance without anyone noticing.
- **How Phase 4 Prevents It:** In our automated test drill (`test_reconciliation_detects_deliberate_balance_corruption`), we intentionally tampered with an account balance in raw SQL. The reconciliation engine immediately caught the +$9,799.00 drift, flagged status as `DRIFT_DETECTED`, and recorded the exact discrepancy in `reconciliation_runs`.

---

### 4. Three Likely Interview Questions & Short Answers

#### Q1: "Why enforce append-only immutability with a PostgreSQL trigger instead of application-level permissions?"
**Model Answer:**
> "Application-level permission checks only protect the HTTP API layer. They do not protect against direct database queries run by database administrators, third-party analytics pipelines, background worker scripts, or migration bugs.
>
> A PostgreSQL `BEFORE UPDATE OR DELETE` trigger executes directly inside the database engine. It acts as an unbreakable physical law: no matter where the SQL command originates, PostgreSQL aborts the transaction with an error."

---

#### Q2: "How do you correct an incorrect transaction if ledger entries can never be modified or deleted?"
**Model Answer:**
> "By issuing a **reversal transaction**.
>
> In GAAP-compliant banking systems, you never edit past history. If an accidental transfer of $100 from Alice to Bob occurred, you create a new transaction with a memo like 'Reversal of Txn #123', debiting Bob $100 and crediting Alice $100. Both the original mistake and the correction are preserved permanently in the audit trail."

---

#### Q3: "What is the computational complexity of reconciliation, and how does it scale in production?"
**Model Answer:**
> "In a naive approach, iterating through millions of accounts and querying entries for each takes $O(N)$ queries and minutes of execution.
>
> We use a single batch SQL aggregation query with `LEFT JOIN` and `GROUP BY`, which scales to hundreds of thousands of accounts in tens of milliseconds. In massive production systems, reconciliation is typically scheduled asynchronously (e.g. nightly or hourly batches) or run in a continuous streaming window using database change-data-capture (CDC)."


