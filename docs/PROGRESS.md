# Project Progress & Traceability Log

This document tracks phase completion, verified requirements, toolchain versions, and architectural decisions throughout the development of the Payment Ledger & Real-Time Auditor.

---

## Toolchain & Environment Matrix (Verified)

| Component | Specification / Version | Verification Command | Status |
|---|---|---|---|
| OS | Windows 11 (AMD64) | System info | VERIFIED |
| Python | 3.14.5 | `python --version` | VERIFIED |
| PostgreSQL | 18.4 (x64 service `postgresql-x64-18`) | `SELECT version();` | VERIFIED |
| FastAPI | 0.142.2 | `pip list` | VERIFIED |
| SQLAlchemy | 2.0.51 (AsyncIO) | `pip list` | VERIFIED |
| asyncpg | 0.31.0 | `pip list` | VERIFIED |
| Alembic | 1.20.1 | `alembic --version` | VERIFIED |
| Pydantic | 2.13.4 (Pydantic-Settings 2.14.2) | `pip list` | VERIFIED |
| Pytest | 9.1.1 (pytest-asyncio 1.4.0) | `pytest --version` | VERIFIED |
| HTTPX | 0.28.1 | `pip list` | VERIFIED |
| Black | 26.10.1 | `black --version` | VERIFIED |
| Ruff | 0.17.0 | `ruff --version` | VERIFIED |
| Mypy | 2.4.0 | `mypy --version` | VERIFIED |
| Git | 2.50.1.windows.1 | `git --version` | VERIFIED |
| GitHub Remote | `https://github.com/ParjanyaReddy/payment-ledger.git` | `git remote -v` | VERIFIED |

---

## Phase Status Summary

- [x] **Phase 0: Scaffold, Repository & Local Setup** (Completed)
- [x] **Phase 1: Data Model, Migrations & Account Management** (Completed)
- [x] **Phase 2: Transfer Core (Double-Entry & Pessimistic Locking)** (Completed)
- [x] **Phase 3: Race-Safe Idempotency** (Completed)
- [x] **Phase 4: Ledger Immutability & Automated Reconciliation** (Completed)
- [x] **Phase 5: Transactional Outbox & AI Categorization** (Completed)
- [x] **Phase 6: Payment Realism (Lifecycle & Velocity Limits)** (Completed)
- [x] **Phase 7: Real-Time Web Auditor Frontend** (Completed)
- [ ] **Phase 8: Benchmarks & Empirical Validation** (Pending)
- [ ] **Phase 9: Hardening, Observability & Final Packaging** (Pending)

---

## Phase 7 Traceability Matrix

| Requirement | Code File | Function / Component | Test / Verification | Status |
|---|---|---|---|---|
| Minimalist SaaS UI (Figr & Cashline) | `app/static/index.html`, `style.css` | UI Theme & Layout | Clean sidebar navigation, Purrweb Cashline top metrics, and Match Proof Inspector | VERIFIED |
| Static Dashboard Serving (/dashboard) | `app/main.py` | `dashboard_view()` | `test_dashboard_endpoint_serves_html` | VERIFIED |
| Real-Time Account & Balance Explorer | `app/static/js/app.js` | `loadAccounts()`, `renderAccountsTable()` | Browser Subagent Inspection (4 accounts loaded) | VERIFIED |
| Interactive Transfer Terminal | `app/static/js/app.js` | `handleTransferSubmit()` | Live transfer of $25.00 executed | VERIFIED |
| One-Click Idempotency Replay Test | `app/static/js/app.js` | `handleReplayTest()` | Verified `X-Idempotent-Replay: true` banner in UI | VERIFIED |
| One-Click Payload Tampering Test | `app/static/js/app.js` | `handleTamperTest()` | Verified `422 Unprocessable Content` rejection in UI | VERIFIED |
| Card Lifecycle Simulator Panel | `app/static/js/app.js` | `handleCardAuthSubmit()`, Capture/Void/Refund | Browser Subagent State Machine interaction | VERIFIED |
| Append-Only Double-Entry Stream | `app/static/js/app.js` | `loadLedgerStream()` | `test_list_transactions_and_ledger_entries_endpoints` | VERIFIED |
| Asynchronous AI Outbox Feed | `app/static/js/app.js` | `renderTransactionsTable()` | Category badges displayed in UI | VERIFIED |
| Live Reconciliation & Invariant Proof | `app/static/js/app.js` | `executeReconciliationAudit()` | `test_reconciliation_tamper_and_heal_drills` | VERIFIED |
| Interactive Tamper & Heal Drills | `app/api/routes_reconciliation.py` | `/drill/tamper`, `/drill/heal` | Corrupts balance, flags drift, heals projections | VERIFIED |


---

## Phase 6 Traceability Matrix

| Requirement | Code File | Function / Component | Test Name | Status |
|---|---|---|---|---|
| Card Authorization Hold | `app/services/card_service.py` | `authorize_card_payment()` | `test_card_full_lifecycle_auth_capture_refund` | VERIFIED |
| Card Settlement Capture | `app/services/card_service.py` | `capture_card_payment()` | `test_card_full_lifecycle_auth_capture_refund` | VERIFIED |
| Card Pre-Settlement Void | `app/services/card_service.py` | `void_card_payment()` | `test_card_authorization_and_void` | VERIFIED |
| Card Reverse Double-Entry Refund | `app/services/card_service.py` | `refund_card_payment()` | `test_card_full_lifecycle_auth_capture_refund` | VERIFIED |
| Partial Capture Settlement | `app/services/card_service.py` | `capture_card_payment()` | `test_card_partial_capture` | VERIFIED |
| Available Balance Overdraft Isolation | `app/services/transfer_service.py` | `execute_transfer()` | `test_holds_prevent_direct_transfer_overdraft` | VERIFIED |
| Card Auth Idempotency Replay | `app/api/routes_cards.py` | `create_card_authorization()` | `test_card_authorization_idempotency_replay` | VERIFIED |
| Velocity Frequency Limit | `app/services/velocity.py` | `check_velocity_limits()` | `test_velocity_frequency_limit_triggers` | VERIFIED |
| Velocity Daily Volume Limit | `app/services/velocity.py` | `check_velocity_limits()` | `test_velocity_daily_volume_limit_triggers` | VERIFIED |
| Invalid State Transition Rejection | `app/services/card_service.py` | `InvalidCardStateTransitionError` | `test_invalid_state_transitions_rejected` | VERIFIED |
| Account Holds Check Constraints | `migrations/versions/c56b02a78129_*.py` | `check_account_balance_covers_holds` | `test_db_constraint_account_holds_exceed_balance` | VERIFIED |
| Card API Route Endpoints | `app/api/routes_cards.py` | `/authorize`, `/{id}/capture`, `/{id}/void`, `/{id}/refund`, `/{id}`, `/account/{acc_id}` | `tests/integration/test_cards.py` (8 tests) | VERIFIED |


---

## Phase 5 Traceability Matrix

| Requirement | Code File | Function / Component | Test Name | Status |
|---|---|---|---|---|
| Atomic Outbox record creation | `app/services/transfer_service.py` | `execute_transfer()` | `test_transfer_creates_pending_outbox_record` | VERIFIED |
| Asynchronous outbox processing | `app/workers/outbox_worker.py` | `process_outbox_batch()` | `test_process_outbox_batch_categorizes_transaction` | VERIFIED |
| Concurrency via SKIP LOCKED | `app/workers/outbox_worker.py` | `process_outbox_batch()` | `test_outbox_concurrent_workers_skip_locked` (0 lock contention) | VERIFIED |
| Retry & fallback resilience | `app/workers/outbox_worker.py` | `process_outbox_batch()` | `test_outbox_worker_retry_and_failure_fallback` (3 retries -> FAILED) | VERIFIED |
| Canonical category validation | `app/services/categorizer.py` | `CategorizationResult` | `test_categorizer_basic_categories` | VERIFIED |
| 100-sample memo accuracy benchmark | `tests/unit/test_categorizer.py` | `test_100_sample_transaction_memos_evaluation` | 100/100 correct (100.0% accuracy >= 95% threshold) | VERIFIED |
| Deterministic test mocks | `app/services/categorizer.py` | `FakeCategorizer` | `test_fake_categorizer_behavior` | VERIFIED |

---

## Phase 4 Traceability Matrix

| Requirement | Code File | Function / Component | Test Name | Status |
|---|---|---|---|---|
| Append-only trigger (rejects UPDATE) | `migrations/versions/f0553f9746bb_*.py` | `prevent_ledger_entry_mutation()` | `test_ledger_entry_update_prevented_by_trigger` | VERIFIED |
| Append-only trigger (rejects DELETE) | `migrations/versions/f0553f9746bb_*.py` | `prevent_ledger_entry_mutation()` | `test_ledger_entry_delete_prevented_by_trigger` | VERIFIED |
| Balance Invariant Verification | `app/services/reconciliation.py` | `run_reconciliation()` | `test_reconciliation_healthy_system` | VERIFIED |
| Double-entry Txn Invariant | `app/services/reconciliation.py` | `run_reconciliation()` | `test_reconciliation_healthy_system` (asserts credits == debits) | VERIFIED |
| Deliberate Tampering Drill | `app/services/reconciliation.py` | `run_reconciliation()` | `test_reconciliation_detects_deliberate_balance_corruption` (flags drift) | VERIFIED |
| Reconciliation API Endpoints | `app/api/routes_reconciliation.py` | `POST /run`, `GET /status` | `test_reconciliation_status_endpoint` | VERIFIED |

---

## Phase 3 Traceability Matrix

| Requirement | Code File | Function / Component | Test Name | Status |
|---|---|---|---|---|
| Mandatory Idempotency-Key header | `app/api/routes_transfers.py` | `create_transfer()` | `test_transfer_missing_idempotency_key` (422 response) | VERIFIED |
| Atomic claim without race window | `app/services/idempotency.py` | `claim_or_get_idempotency()` | `test_50_concurrent_identical_idempotent_requests` (PostgreSQL `ON CONFLICT DO NOTHING`) | VERIFIED |
| Identical request replay | `app/api/routes_transfers.py` | `create_transfer()` | `test_transfer_idempotent_replay` (Replays cached 201 with `X-Idempotent-Replay`) | VERIFIED |
| Hash mismatch detection | `app/services/idempotency.py` | `compute_request_hash()` | `test_transfer_same_key_different_payload_rejected` (422 Unprocessable Content) | VERIFIED |
| 50-request concurrent deduplication | `tests/concurrency/test_concurrency.py` | `test_50_concurrent_identical_idempotent_requests` | Proves 50 concurrent requests produce exactly 1 DB txn and 1 debit | VERIFIED |
| 24-hour key retention cleanup | `app/services/idempotency.py` | `cleanup_expired_keys()` | `test_cleanup_expired_idempotency_keys` | VERIFIED |

---

## Phase 2 Traceability Matrix

| Requirement | Code File | Function / Component | Test Name | Status |
|---|---|---|---|---|
| Deadlock-free ordered row locks | `app/services/transfer_service.py` | `execute_transfer()` | `test_opposing_transfers_no_deadlock` (200 parallel transfers, 0 deadlocks) | VERIFIED |
| Double-entry invariant ($\sum \text{entries} = 0$) | `app/services/transfer_service.py` | `execute_transfer()` | `test_transfer_happy_path` (asserts DEBIT == CREDIT) | VERIFIED |
| Insufficient funds rejection | `app/services/transfer_service.py` | `InsufficientFundsError` | `test_transfer_insufficient_funds` (422 response) | VERIFIED |
| Contended overdraft prevention | `app/services/transfer_service.py` | `execute_transfer()` | `test_200_concurrent_transfers_no_overdraft` (50 successes, 150 rejected, final bal = 0) | VERIFIED |
| Conservation of money | `app/services/transfer_service.py` | `execute_transfer()` | `test_conservation_of_money_across_random_transfers` (0 balance drift) | VERIFIED |
| Same-account transfer rejection | `app/services/transfer_service.py` | `SelfTransferError` | `test_transfer_self_transfer_rejected` (400 response) | VERIFIED |
| Cross-currency transfer rejection | `app/services/transfer_service.py` | `CurrencyMismatchError` | `test_transfer_currency_mismatch` (400 response) | VERIFIED |
| Non-existent account rejection | `app/services/transfer_service.py` | `AccountNotFoundError` | `test_transfer_nonexistent_account` (404 response) | VERIFIED |
| Transfer endpoint (POST /transfers) | `app/api/routes_transfers.py` | `create_transfer()` | `tests/integration/test_transfers.py` (5 tests) | VERIFIED |
| Transfer request & response schemas | `app/schemas/transfer.py` | `TransferRequest`, `TransferResponse` | `tests/unit/test_transfer_schema.py` (5 tests) | VERIFIED |
