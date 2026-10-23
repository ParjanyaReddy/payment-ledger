# CORE LOGIC: understand this file line by line.
"""Double-Entry Transfer Service with Deadlock-Free Pessimistic Row Locking.

This module is the core financial engine of the ledger system. It enforces:
1. Deadlock elimination by strictly locking accounts in ascending UUID order.
2. Balance sufficiency checks against freshly locked, uncommitted row data.
3. Strict double-entry accounting: exactly two ledger entries per transfer (SUM = 0).
4. Atomic update of cached balance projections within the same DB transaction.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.ledger_entry import LedgerEntry
from app.models.outbox import Outbox
from app.models.transaction import Transaction
from app.services.exceptions import (
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    SelfTransferError,
)


class TransferResult:
    """Container holding the results of an atomic double-entry transfer."""

    def __init__(
        self,
        transaction: Transaction,
        debit_entry: LedgerEntry,
        credit_entry: LedgerEntry,
        from_account_balance: Decimal,
        to_account_balance: Decimal,
    ) -> None:
        self.transaction = transaction
        self.debit_entry = debit_entry
        self.credit_entry = credit_entry
        self.from_account_balance = from_account_balance
        self.to_account_balance = to_account_balance


async def execute_transfer(
    db: AsyncSession,
    from_account_id: uuid.UUID,
    to_account_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    memo: str | None = None,
) -> TransferResult:
    """Execute an atomic double-entry transfer between two accounts.

    Deadlock Prevention Strategy:
    Two concurrent transfers going in opposite directions (A->B and B->A)
    can deadlock if one locks A then B, while the other locks B then A.
    By sorting the account IDs and acquiring locks in ascending order,
    every concurrent transaction requests locks in the identical sequence.
    This breaks the circular wait condition required for deadlocks.

    Args:
        db: Active asynchronous SQLAlchemy session.
        from_account_id: Sender account UUID.
        to_account_id: Recipient account UUID.
        amount: Exact positive decimal amount to move.
        currency: Three-letter ISO currency code.
        memo: Optional description or merchant note.

    Returns:
        TransferResult containing the created transaction, two entries, and updated balances.

    Raises:
        SelfTransferError: If sender and recipient are the same account.
        InvalidAmountError: If amount is less than or equal to zero.
        AccountNotFoundError: If either account does not exist.
        CurrencyMismatchError: If account currencies do not match transfer currency.
        InsufficientFundsError: If sender does not have enough balance.
    """
    # 1. Reject transfers to the same account
    if from_account_id == to_account_id:
        raise SelfTransferError(from_account_id)

    # 2. Reject non-positive amounts
    if amount <= Decimal("0.00"):
        raise InvalidAmountError(str(amount))

    # 3. Sort account IDs to enforce a global, deterministic lock acquisition order
    sorted_ids = sorted([from_account_id, to_account_id])

    # 4. Acquire pessimistic row-level exclusive locks in sorted order
    # SELECT ... FOR UPDATE blocks any concurrent transaction from modifying
    # these accounts until this transaction commits or rolls back.
    stmt = select(Account).where(Account.id.in_(sorted_ids)).order_by(Account.id).with_for_update()
    result = await db.execute(stmt)
    locked_accounts = {account.id: account for account in result.scalars().all()}

    # 5. Verify both accounts exist in the database
    if from_account_id not in locked_accounts:
        raise AccountNotFoundError(from_account_id)
    if to_account_id not in locked_accounts:
        raise AccountNotFoundError(to_account_id)

    sender = locked_accounts[from_account_id]
    receiver = locked_accounts[to_account_id]

    # 6. Verify currency consistency
    currency_clean = currency.strip().upper()
    if sender.currency != currency_clean:
        raise CurrencyMismatchError(expected=currency_clean, actual=sender.currency)
    if receiver.currency != currency_clean:
        raise CurrencyMismatchError(expected=currency_clean, actual=receiver.currency)

    # 7. Check sufficient funds on the freshly locked row
    # Because we hold the FOR UPDATE lock, no other transaction can concurrently
    # reduce this balance between our check and our debit.
    if sender.balance < amount:
        raise InsufficientFundsError(
            account_id=from_account_id,
            available=f"{sender.balance:.2f}",
            requested=f"{amount:.2f}",
        )

    # 8. Create the parent Transaction record
    transfer_txn = Transaction(
        id=uuid.uuid4(),
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=amount,
        status="COMPLETED",
        memo=memo,
    )
    db.add(transfer_txn)
    # Flush parent transaction first so foreign key references in ledger_entries resolve
    await db.flush()

    # 9. Update cached balance projections and bump version numbers
    sender.balance -= amount
    receiver.balance += amount
    sender.version += 1
    receiver.version += 1

    # 10. Write strictly two immutable double-entry ledger rows
    # Invariant: SUM(entries) = (+amount) + (-amount) = 0
    debit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=transfer_txn.id,
        account_id=from_account_id,
        direction="DEBIT",
        amount=amount,
    )
    credit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=transfer_txn.id,
        account_id=to_account_id,
        direction="CREDIT",
        amount=amount,
    )
    db.add(debit_entry)
    db.add(credit_entry)

    # 11. Enqueue durable Outbox record for asynchronous AI categorization
    outbox_entry = Outbox(
        id=uuid.uuid4(),
        transaction_id=transfer_txn.id,
        status="PENDING",
        attempts=0,
    )
    db.add(outbox_entry)

    # Flush session to populate database-generated fields while retaining the transaction
    await db.flush()

    return TransferResult(
        transaction=transfer_txn,
        debit_entry=debit_entry,
        credit_entry=credit_entry,
        from_account_balance=sender.balance,
        to_account_balance=receiver.balance,
    )
