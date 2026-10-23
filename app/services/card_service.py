# CORE LOGIC: understand this file line by line.
"""Payment Card Lifecycle State Machine and Balance Holds Engine.

Implements realistic credit/debit card processing primitives:
1. Authorization: Places a temporary hold against the account's available balance
   (available = balance - holds) without creating ledger entries.
2. Capture: Settles the authorization into an immutable double-entry transfer,
   releasing the hold and debiting the customer while crediting the merchant.
3. Void: Cancels an active authorization before settlement, immediately releasing
   the hold back to available balance with zero ledger mutation.
4. Refund: Executes a reverse double-entry transfer on a captured transaction,
   debiting the merchant and returning funds to the customer.
5. Velocity Fraud Check: Enforces rolling window transaction limits before authorization.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.card import CardAuthorization
from app.models.ledger_entry import LedgerEntry
from app.models.outbox import Outbox
from app.models.transaction import Transaction
from app.services.exceptions import (
    AccountNotFoundError,
    CardAuthorizationExpiredError,
    CardAuthorizationNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    InvalidCardStateTransitionError,
    InvalidRefundAmountError,
    SelfTransferError,
)
from app.services.velocity import check_velocity_limits


async def authorize_card_payment(
    db: AsyncSession,
    account_id: uuid.UUID,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    memo: str | None = None,
    hold_duration_hours: int = 168,
    check_velocity: bool = True,
) -> CardAuthorization:
    """Place an authorization hold on an account's available balance.

    Holds decrease the customer's available spendable balance while leaving
    the booked ledger balance untouched until settlement capture.

    Args:
        db: Active asynchronous database session.
        account_id: Customer account UUID to place hold on.
        merchant_id: Recipient merchant account UUID.
        amount: Exact positive decimal amount to hold.
        currency: Three-letter ISO currency code.
        memo: Optional description or merchant descriptor.
        hold_duration_hours: Expiration lifetime of the hold in hours.
        check_velocity: Whether to enforce velocity fraud rules.

    Returns:
        Created CardAuthorization record in 'AUTHORIZED' status.
    """
    if account_id == merchant_id:
        raise SelfTransferError(account_id)

    if amount <= Decimal("0.00"):
        raise InvalidAmountError(str(amount))

    # 1. Enforce velocity fraud controls
    if check_velocity:
        await check_velocity_limits(db, account_id, amount, include_authorizations=True)

    # 2. Acquire deadlock-free row locks in sorted UUID order
    sorted_ids = sorted([account_id, merchant_id])
    stmt = select(Account).where(Account.id.in_(sorted_ids)).order_by(Account.id).with_for_update()
    result = await db.execute(stmt)
    locked_accounts = {account.id: account for account in result.scalars().all()}

    if account_id not in locked_accounts:
        raise AccountNotFoundError(account_id)
    if merchant_id not in locked_accounts:
        raise AccountNotFoundError(merchant_id)

    customer = locked_accounts[account_id]
    merchant = locked_accounts[merchant_id]

    # 3. Currency match validation
    currency_clean = currency.strip().upper()
    if customer.currency != currency_clean:
        raise CurrencyMismatchError(expected=currency_clean, actual=customer.currency)
    if merchant.currency != currency_clean:
        raise CurrencyMismatchError(expected=currency_clean, actual=merchant.currency)

    # 4. Check available balance (booked balance minus existing active holds)
    available_balance = customer.balance - customer.holds
    if available_balance < amount:
        raise InsufficientFundsError(
            account_id=account_id,
            available=f"{available_balance:.2f}",
            requested=f"{amount:.2f}",
        )

    # 5. Place the hold on customer account
    customer.holds += amount
    customer.version += 1

    # 6. Record the authorization
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=hold_duration_hours)

    authorization = CardAuthorization(
        id=uuid.uuid4(),
        account_id=account_id,
        merchant_id=merchant_id,
        amount=amount,
        captured_amount=None,
        refunded_amount=Decimal("0.00"),
        currency=currency_clean,
        status="AUTHORIZED",
        memo=memo,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(authorization)
    await db.flush()

    return authorization


async def capture_card_payment(
    db: AsyncSession,
    authorization_id: uuid.UUID,
    capture_amount: Decimal | None = None,
) -> tuple[CardAuthorization, Transaction]:
    """Capture an authorized hold into an immutable settled double-entry transfer.

    Releases the hold and executes the irreversible debit/credit ledger transfer.
    Supports partial capture (up to authorized amount).

    Args:
        db: Active asynchronous database session.
        authorization_id: UUID of the authorization to capture.
        capture_amount: Optional amount to capture. Defaults to full authorized amount.

    Returns:
        Tuple of (updated CardAuthorization, settled Transaction).
    """
    # 1. Lock the authorization record
    auth_stmt = (
        select(CardAuthorization).where(CardAuthorization.id == authorization_id).with_for_update()
    )
    auth = await db.scalar(auth_stmt)
    if not auth:
        raise CardAuthorizationNotFoundError(authorization_id)

    if auth.status != "AUTHORIZED":
        raise InvalidCardStateTransitionError(
            current_status=auth.status,
            attempted_action="CAPTURE",
        )

    now = datetime.now(UTC)
    if now > auth.expires_at:
        raise CardAuthorizationExpiredError(authorization_id)

    # 2. Determine and validate capture amount
    final_amount = capture_amount if capture_amount is not None else auth.amount
    if final_amount <= Decimal("0.00") or final_amount > auth.amount:
        raise InvalidAmountError(
            f"Capture amount '{final_amount}' must be positive and <= authorized amount '{auth.amount}'"
        )

    # 3. Lock customer and merchant accounts in ascending UUID order to prevent deadlocks
    sorted_ids = sorted([auth.account_id, auth.merchant_id])
    stmt = select(Account).where(Account.id.in_(sorted_ids)).order_by(Account.id).with_for_update()
    result = await db.execute(stmt)
    locked_accounts = {account.id: account for account in result.scalars().all()}

    customer = locked_accounts[auth.account_id]
    merchant = locked_accounts[auth.merchant_id]

    # 4. Release the customer hold (the entire original authorization hold is released)
    customer.holds -= auth.amount

    # 5. Execute double-entry transfer for the captured amount
    customer.balance -= final_amount
    merchant.balance += final_amount
    customer.version += 1
    merchant.version += 1

    settle_txn = Transaction(
        id=uuid.uuid4(),
        from_account_id=customer.id,
        to_account_id=merchant.id,
        amount=final_amount,
        status="COMPLETED",
        memo=f"Capture: {auth.memo or 'Card purchase'}",
    )
    db.add(settle_txn)
    await db.flush()

    debit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=settle_txn.id,
        account_id=customer.id,
        direction="DEBIT",
        amount=final_amount,
    )
    credit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=settle_txn.id,
        account_id=merchant.id,
        direction="CREDIT",
        amount=final_amount,
    )
    db.add(debit_entry)
    db.add(credit_entry)

    # 6. Enqueue transactional outbox for async AI categorization
    outbox_entry = Outbox(
        id=uuid.uuid4(),
        transaction_id=settle_txn.id,
        status="PENDING",
        attempts=0,
    )
    db.add(outbox_entry)

    # 7. Update authorization state
    auth.status = "CAPTURED"
    auth.captured_amount = final_amount
    auth.captured_at = now
    auth.transaction_id = settle_txn.id

    await db.flush()
    return auth, settle_txn


async def void_card_payment(
    db: AsyncSession,
    authorization_id: uuid.UUID,
    reason: str | None = None,
) -> CardAuthorization:
    """Void an active authorization hold before capture.

    Immediately restores the customer's available balance with zero ledger movements.

    Args:
        db: Active asynchronous database session.
        authorization_id: UUID of authorization to cancel.
        reason: Optional cancellation reason.

    Returns:
        Updated CardAuthorization in 'VOIDED' status.
    """
    # 1. Lock authorization row
    auth_stmt = (
        select(CardAuthorization).where(CardAuthorization.id == authorization_id).with_for_update()
    )
    auth = await db.scalar(auth_stmt)
    if not auth:
        raise CardAuthorizationNotFoundError(authorization_id)

    if auth.status != "AUTHORIZED":
        raise InvalidCardStateTransitionError(
            current_status=auth.status,
            attempted_action="VOID",
        )

    # 2. Lock customer account and release hold
    acc_stmt = select(Account).where(Account.id == auth.account_id).with_for_update()
    customer = await db.scalar(acc_stmt)
    if not customer:
        raise AccountNotFoundError(auth.account_id)

    customer.holds -= auth.amount
    customer.version += 1

    # 3. Update authorization state
    now = datetime.now(UTC)
    auth.status = "VOIDED"
    auth.voided_at = now
    if reason:
        auth.memo = f"{auth.memo} (Voided: {reason})" if auth.memo else f"Voided: {reason}"

    await db.flush()
    return auth


async def refund_card_payment(
    db: AsyncSession,
    authorization_id: uuid.UUID,
    refund_amount: Decimal | None = None,
    reason: str | None = None,
) -> tuple[CardAuthorization, Transaction]:
    """Execute a reverse double-entry refund on a captured card payment.

    Debits the merchant and credits the customer. Supports partial refunds.

    Args:
        db: Active asynchronous database session.
        authorization_id: UUID of the captured authorization to refund.
        refund_amount: Optional refund amount. Defaults to remaining eligible refund.
        reason: Optional refund explanation note.

    Returns:
        Tuple of (updated CardAuthorization, refund Transaction).
    """
    # 1. Lock authorization row
    auth_stmt = (
        select(CardAuthorization).where(CardAuthorization.id == authorization_id).with_for_update()
    )
    auth = await db.scalar(auth_stmt)
    if not auth:
        raise CardAuthorizationNotFoundError(authorization_id)

    if auth.status != "CAPTURED":
        raise InvalidCardStateTransitionError(
            current_status=auth.status,
            attempted_action="REFUND",
        )

    assert auth.captured_amount is not None
    eligible_refund = auth.captured_amount - auth.refunded_amount
    final_refund = refund_amount if refund_amount is not None else eligible_refund

    if final_refund <= Decimal("0.00") or final_refund > eligible_refund:
        raise InvalidRefundAmountError(
            requested=f"{final_refund:.2f}",
            max_allowed=f"{eligible_refund:.2f}",
        )

    # 2. Lock accounts in sorted UUID order
    sorted_ids = sorted([auth.account_id, auth.merchant_id])
    stmt = select(Account).where(Account.id.in_(sorted_ids)).order_by(Account.id).with_for_update()
    result = await db.execute(stmt)
    locked_accounts = {account.id: account for account in result.scalars().all()}

    customer = locked_accounts[auth.account_id]
    merchant = locked_accounts[auth.merchant_id]

    # 3. Verify merchant has enough available balance to issue refund
    merchant_available = merchant.balance - merchant.holds
    if merchant_available < final_refund:
        raise InsufficientFundsError(
            account_id=merchant.id,
            available=f"{merchant_available:.2f}",
            requested=f"{final_refund:.2f}",
        )

    # 4. Reverse double-entry transfer (Merchant DEBIT -> Customer CREDIT)
    merchant.balance -= final_refund
    customer.balance += final_refund
    merchant.version += 1
    customer.version += 1

    refund_txn = Transaction(
        id=uuid.uuid4(),
        from_account_id=merchant.id,
        to_account_id=customer.id,
        amount=final_refund,
        status="COMPLETED",
        memo=f"Refund: {reason or auth.memo or 'Card purchase refund'}",
    )
    db.add(refund_txn)
    await db.flush()

    debit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=refund_txn.id,
        account_id=merchant.id,
        direction="DEBIT",
        amount=final_refund,
    )
    credit_entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=refund_txn.id,
        account_id=customer.id,
        direction="CREDIT",
        amount=final_refund,
    )
    db.add(debit_entry)
    db.add(credit_entry)

    outbox_entry = Outbox(
        id=uuid.uuid4(),
        transaction_id=refund_txn.id,
        status="PENDING",
        attempts=0,
    )
    db.add(outbox_entry)

    # 5. Update authorization state
    auth.refunded_amount += final_refund
    auth.refund_transaction_id = refund_txn.id
    if auth.refunded_amount == auth.captured_amount:
        auth.status = "REFUNDED"

    await db.flush()
    return auth, refund_txn


async def get_card_authorization(
    db: AsyncSession,
    authorization_id: uuid.UUID,
) -> CardAuthorization:
    """Retrieve a card authorization record by its UUID."""
    stmt = select(CardAuthorization).where(CardAuthorization.id == authorization_id)
    auth = await db.scalar(stmt)
    if not auth:
        raise CardAuthorizationNotFoundError(authorization_id)
    return auth


async def list_card_authorizations_for_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    limit: int = 50,
) -> list[CardAuthorization]:
    """List recent card authorizations involving an account (as customer or merchant)."""
    stmt = (
        select(CardAuthorization)
        .where(
            (CardAuthorization.account_id == account_id)
            | (CardAuthorization.merchant_id == account_id)
        )
        .order_by(desc(CardAuthorization.created_at))
        .limit(limit)
    )
    result = await db.scalars(stmt)
    return list(result.all())
