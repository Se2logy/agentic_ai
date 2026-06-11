"""Float→DECIMAL for incidental amounts + FK indexes on session_id columns.

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

Changes:
- MF-5: Change incidental_selections.amount from Float to Numeric(10,2)
  (DECIMAL(10,2) in MySQL) to avoid floating-point precision loss on
  monetary values.
- SF-4: Add indexes on session_id FK columns in 5 tables that lack them:
  agreements, audit_trail, incidental_selections, messages, otp_verifications.
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- MF-5: Float → DECIMAL(10,2) ---
    op.alter_column(
        "incidental_selections",
        "amount",
        type_=sa.Numeric(10, 2),
        existing_type=sa.Float(),
        existing_nullable=False,
    )

    # --- SF-4: FK indexes on session_id ---
    op.create_index(
        "ix_agreements_session_id", "agreements", ["session_id"]
    )
    op.create_index(
        "ix_audit_trail_session_id", "audit_trail", ["session_id"]
    )
    op.create_index(
        "ix_incidental_selections_session_id",
        "incidental_selections",
        ["session_id"],
    )
    op.create_index(
        "ix_messages_session_id", "messages", ["session_id"]
    )
    op.create_index(
        "ix_otp_verifications_session_id", "otp_verifications", ["session_id"]
    )


def downgrade() -> None:
    # --- SF-4: Drop FK indexes on session_id ---
    op.drop_index("ix_otp_verifications_session_id", table_name="otp_verifications")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_index(
        "ix_incidental_selections_session_id", table_name="incidental_selections"
    )
    op.drop_index("ix_audit_trail_session_id", table_name="audit_trail")
    op.drop_index("ix_agreements_session_id", table_name="agreements")

    # --- MF-5: DECIMAL(10,2) → Float ---
    op.alter_column(
        "incidental_selections",
        "amount",
        type_=sa.Float(),
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
    )
