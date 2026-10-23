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
- [ ] **Phase 3: Race-Safe Idempotency** (Pending approval)
- [ ] **Phase 4: Ledger Immutability & Automated Reconciliation** (Pending)
- [ ] **Phase 5: Transactional Outbox & AI Categorization** (Pending)
- [ ] **Phase 6: Payment Realism (Lifecycle & Velocity Limits)** (Pending)
- [ ] **Phase 7: Real-Time Web Auditor Frontend** (Pending)
- [ ] **Phase 8: Benchmarks & Empirical Validation** (Pending)
- [ ] **Phase 9: Hardening, Observability & Final Packaging** (Pending)

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
