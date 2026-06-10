"""Initial schema — all tables.

Revision ID: 001
Revises: None
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- reservations ---
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("booking_reference", sa.String(50), unique=True, nullable=False),
        sa.Column("property_name", sa.String(255), nullable=False),
        sa.Column("property_address", sa.Text(), nullable=False),
        sa.Column("guest_name", sa.String(255), nullable=False),
        sa.Column("guest_email", sa.String(255), nullable=False),
        sa.Column("guest_phone", sa.String(50), nullable=True),
        sa.Column("check_in_date", sa.Date(), nullable=False),
        sa.Column("check_out_date", sa.Date(), nullable=False),
        sa.Column("num_guests", sa.Integer(), server_default="1"),
        sa.Column("wifi_network", sa.String(255), nullable=True),
        sa.Column("wifi_password", sa.String(255), nullable=True),
        sa.Column("lockbox_code", sa.String(50), nullable=True),
        sa.Column("emergency_contact", sa.String(255), nullable=True),
        sa.Column("house_rules_text", sa.Text(), nullable=False),
        sa.Column("rental_agreement_text", sa.Text(), nullable=False),
        sa.Column("privacy_policy_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_reservations_booking_ref", "reservations", ["booking_reference"])

    # --- guests ---
    op.create_table(
        "guests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("id_document_path", sa.String(255), nullable=True),
        sa.Column("id_verified", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_guests_email", "guests", ["email"])

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.String(36),
            sa.ForeignKey("reservations.id"),
            nullable=False,
        ),
        sa.Column(
            "guest_id",
            sa.String(36),
            sa.ForeignKey("guests.id"),
            nullable=False,
        ),
        sa.Column("current_state", sa.String(50), server_default="INIT"),
        sa.Column("session_token", sa.String(255), unique=True, nullable=False),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_token", "sessions", ["session_token"])

    # --- agreements ---
    op.create_table(
        "agreements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("agreement_type", sa.String(50), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("guest_response", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- otp_verifications ---
    op.create_table(
        "otp_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("otp_code", sa.String(10), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default="0"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("max_attempts", sa.Integer(), server_default="3"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_otp_code", "otp_verifications", ["otp_code"])

    # --- incidental_selections ---
    op.create_table(
        "incidental_selections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("selection_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_status", sa.String(20), server_default="pending"),
        sa.Column("payment_reference", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- messages ---
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent_detected", sa.String(50), nullable=True),
        sa.Column("tools_called", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- audit_trail ---
    op.create_table(
        "audit_trail",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("from_state", sa.String(50), nullable=True),
        sa.Column("to_state", sa.String(50), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("actor", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- knowledge_base ---
    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("property_id", sa.String(50), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_kb_property_id", "knowledge_base", ["property_id"])

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key", "api_keys", ["key"])


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("knowledge_base")
    op.drop_table("audit_trail")
    op.drop_table("messages")
    op.drop_table("incidental_selections")
    op.drop_table("otp_verifications")
    op.drop_table("agreements")
    op.drop_table("sessions")
    op.drop_table("guests")
    op.drop_table("reservations")
