"""Payment gateway abstraction with a mock implementation for development."""

import abc
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import logging

logger = logging.getLogger(__name__)


@dataclass
class PaymentResult:
    """Result of a payment or refund operation."""

    success: bool
    transaction_id: str
    message: str


class PaymentGateway(abc.ABC):
    """Abstract base class for payment processing."""

    @abc.abstractmethod
    async def process_payment(
        self,
        guest_id: str,
        amount: float | Decimal,
        description: str,
        metadata: dict | None = None,
    ) -> PaymentResult:
        """Process a payment for a guest.

        Args:
            guest_id: The guest's unique identifier.
            amount: The payment amount.
            description: Human-readable description of the charge.
            metadata: Optional key-value metadata for the payment.

        Returns:
            PaymentResult with success status, transaction ID, and message.
        """

    @abc.abstractmethod
    async def refund(self, transaction_id: str) -> PaymentResult:
        """Refund a previously processed payment.

        Args:
            transaction_id: The transaction to refund.

        Returns:
            PaymentResult with success status and message.
        """


class MockPayment(PaymentGateway):
    """Mock payment gateway for development/testing.

    Always returns success=True with a generated transaction ID.
    """

    async def process_payment(
        self,
        guest_id: str,
        amount: float | Decimal,
        description: str,
        metadata: dict | None = None,
    ) -> PaymentResult:
        txn_id = f"mock-{uuid.uuid4().hex[:12]}"
        logger.info(
            "MockPayment.process_payment: guest=%s amount=%.2f txn=%s desc=%s",
            guest_id,
            amount,
            txn_id,
            description,
        )
        return PaymentResult(
            success=True,
            transaction_id=txn_id,
            message=f"Mock payment of ${amount:.2f} processed successfully.",
        )

    async def refund(self, transaction_id: str) -> PaymentResult:
        refund_id = f"mock-refund-{uuid.uuid4().hex[:12]}"
        logger.info(
            "MockPayment.refund: original_txn=%s refund_txn=%s",
            transaction_id,
            refund_id,
        )
        return PaymentResult(
            success=True,
            transaction_id=refund_id,
            message=f"Mock refund for {transaction_id} processed successfully.",
        )


# Singleton instance
payment_service = MockPayment()
