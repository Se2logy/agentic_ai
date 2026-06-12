"""DATA-001: Monetary columns use Numeric(10,2) instead of Float.

Verifies that IncidentalSelection.amount (and any future Payment.amount)
column types are Numeric(10,2), NOT Float, to avoid floating-point
precision loss on monetary values.
"""

import pytest
from sqlalchemy import Numeric


class TestMonetaryNumericColumns:
    """Assert that every monetary column in ORM models uses Numeric(10,2)."""

    def test_incidental_selection_amount_is_numeric_10_2(self):
        """IncidentalSelection.amount must be Numeric(10,2), not Float."""
        from app.models.incidental_selection import IncidentalSelection

        col = IncidentalSelection.__table__.columns["amount"]
        assert isinstance(
            col.type, Numeric
        ), f"IncidentalSelection.amount type is {type(col.type).__name__}, expected Numeric"
        assert (
            col.type.precision == 10
        ), f"Expected precision 10, got {col.type.precision}"
        assert (
            col.type.scale == 2
        ), f"Expected scale 2, got {col.type.scale}"

    def test_no_payment_model_exists_yet(self):
        """Document that Payment ORM model does not yet exist.

        When a Payment model is added with an `amount` column, a matching
        test (test_payment_amount_is_numeric_10_2) must be added.
        """
        from app.models import __all__ as registered_models

        assert "Payment" not in registered_models, (
            "Payment model was added to __all__ — add a "
            "test_payment_amount_is_numeric_10_2 test and remove this placeholder."
        )
