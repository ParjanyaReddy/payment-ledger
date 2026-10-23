"""Domain Exceptions for Payment Ledger Business Logic.

Defines typed business exceptions raised during transfer execution,
reconciliation audits, and account validation.
"""

import uuid


class LedgerError(Exception):
    """Base exception for all domain errors within the ledger system."""

    pass


class AccountNotFoundError(LedgerError):
    """Raised when an account referenced in an operation does not exist."""

    def __init__(self, account_id: uuid.UUID) -> None:
        self.account_id = account_id
        super().__init__(f"Account '{account_id}' was not found")


class InsufficientFundsError(LedgerError):
    """Raised when an account balance is insufficient to cover a debit."""

    def __init__(self, account_id: uuid.UUID, available: str, requested: str) -> None:
        self.account_id = account_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"Insufficient funds in account '{account_id}': available {available}, requested {requested}"
        )


class SelfTransferError(LedgerError):
    """Raised when a transfer is initiated where source equals destination."""

    def __init__(self, account_id: uuid.UUID) -> None:
        self.account_id = account_id
        super().__init__("Cannot transfer funds to the same account")


class CurrencyMismatchError(LedgerError):
    """Raised when accounts involved in a transfer have differing currencies."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Currency mismatch: expected {expected}, got {actual}")


class InvalidAmountError(LedgerError):
    """Raised when an invalid or non-positive amount is supplied."""

    def __init__(self, amount: str) -> None:
        self.amount = amount
        super().__init__(f"Transfer amount must be strictly positive: '{amount}'")


class CardAuthorizationNotFoundError(LedgerError):
    """Raised when a card authorization cannot be located by ID."""

    def __init__(self, authorization_id: uuid.UUID) -> None:
        self.authorization_id = authorization_id
        super().__init__(f"Card authorization '{authorization_id}' was not found")


class InvalidCardStateTransitionError(LedgerError):
    """Raised when attempting an illegal state transition in the card lifecycle."""

    def __init__(self, current_status: str, attempted_action: str) -> None:
        self.current_status = current_status
        self.attempted_action = attempted_action
        super().__init__(
            f"Cannot execute '{attempted_action}' on authorization in '{current_status}' status"
        )


class CardAuthorizationExpiredError(LedgerError):
    """Raised when attempting to capture or manipulate an expired authorization."""

    def __init__(self, authorization_id: uuid.UUID) -> None:
        self.authorization_id = authorization_id
        super().__init__(f"Card authorization '{authorization_id}' has expired")


class VelocityLimitExceededError(LedgerError):
    """Raised when an account exceeds frequency or volume velocity fraud rules."""

    def __init__(self, account_id: uuid.UUID, reason: str) -> None:
        self.account_id = account_id
        self.reason = reason
        super().__init__(f"Velocity limit exceeded for account '{account_id}': {reason}")


class InvalidRefundAmountError(LedgerError):
    """Raised when a refund amount exceeds the eligible captured amount."""

    def __init__(self, requested: str, max_allowed: str) -> None:
        self.requested = requested
        self.max_allowed = max_allowed
        super().__init__(
            f"Refund amount '{requested}' exceeds maximum eligible refund '{max_allowed}'"
        )
