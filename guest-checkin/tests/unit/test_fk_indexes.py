"""Verify FK indexes exist on session_id columns (TASK-005-006)."""

import pytest

from app.models.agreement import Agreement
from app.models.audit_trail import AuditTrail
from app.models.incidental_selection import IncidentalSelection
from app.models.message import Message
from app.models.otp_verification import OTPVerification


@pytest.mark.parametrize(
    "model_class",
    [
        Agreement,
        AuditTrail,
        IncidentalSelection,
        Message,
        OTPVerification,
    ],
    ids=[
        "agreement.session_id",
        "audit_trail.session_id",
        "incidental_selection.session_id",
        "message.session_id",
        "otp_verification.session_id",
    ],
)
def test_session_id_has_index(model_class):
    """Each model's session_id FK column must have index=True."""
    col = model_class.__table__.c["session_id"]
    assert col.index is True, (
        f"{model_class.__name__}.session_id is missing index=True"
    )
