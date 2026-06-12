"""Unit tests for SessionManager — Bug 3: instructions_html separation.

Verifies that:
1. instructions_html is returned as a separate field from agent_content
   (not concatenated into agent_content) for COMPLETED sessions.
2. When a COMPLETED session receives a subsequent message, arrival
   instructions are NOT re-appended/duplicated in agent_content.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models import (  # noqa: F401
    Agreement, APIKey, AuditTrail, Guest,
    IncidentalSelection, KnowledgeBase, Message,
    OTPVerification, Reservation, Session,
)
from app.session_manager import SessionManager
from app.state_machine.states import State

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_engine():
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seeded_completed(db_session: AsyncSession):
    """Seed a session in COMPLETED state so we can test
    instructions_html separation and dedup."""
    guest = Guest(
        id=str(uuid.uuid4()),
        email="guest@example.com",
        first_name="Bob",
        last_name="Smith",
        phone="+1-555-0202",
    )
    db_session.add(guest)
    await db_session.flush()

    from datetime import date

    reservation = Reservation(
        id=str(uuid.uuid4()),
        booking_reference="BK-DEDUP-001",
        property_name="Mountain Lodge",
        property_address="1 Summit Rd",
        guest_name="Bob Smith",
        guest_email="guest@example.com",
        guest_phone="+1-555-0202",
        check_in_date=date(2024, 8, 1),
        check_out_date=date(2024, 8, 5),
        num_guests=1,
        wifi_network="LodgeWiFi",
        wifi_password="mountain123",
        lockbox_code="9911",
        emergency_contact="+1-555-0911",
        house_rules_text="No pets.",
        rental_agreement_text="Standard terms.",
        privacy_policy_text="We respect your privacy.",
    )
    db_session.add(reservation)
    await db_session.flush()

    session = Session(
        id=str(uuid.uuid4()),
        reservation_id=reservation.id,
        guest_id=guest.id,
        current_state=State.COMPLETED.value,
        session_token="tok-completed-test",
        status="active",
    )
    db_session.add(session)
    await db_session.flush()

    return {
        "db": db_session,
        "session_id": session.id,
        "guest_id": guest.id,
        "reservation_id": reservation.id,
    }


class TestInstructionsHtmlSeparation:
    """Bug 3: instructions_html should be a separate field,
    NOT concatenated into agent_content."""

    @pytest.mark.asyncio
    async def test_instructions_html_separate_from_agent_content(
        self, seeded_completed
    ):
        """When SessionManager returns a COMPLETED result,
        instructions_html must be present as a separate field and
        agent_content must NOT contain raw HTML tags from instructions."""
        db = seeded_completed["db"]
        session_id = seeded_completed["session_id"]

        sample_html = (
            "<div class='instructions'>"
            "<h2>Arrival Instructions</h2>"
            "<p>Lockbox code: 9911</p>"
            "</div>"
        )

        # Mock the internal methods so we don't need LLM/DB
        sm = SessionManager()

        with patch.object(
            sm, "_detect_intent", new_callable=AsyncMock, return_value="greeting"
        ), patch.object(
            sm, "_extract_entities", new_callable=AsyncMock, return_value={}
        ), patch.object(
            sm, "_route_tool", new_callable=AsyncMock,
            return_value=(None, None),
        ), patch.object(
            sm, "_advance_state", new_callable=AsyncMock,
            return_value=(
                "Your check-in is complete! Here are your arrival instructions.",
                State.COMPLETED,
                sample_html,
            ),
        ), patch.object(
            sm, "_enrich_response",
            side_effect=lambda content, state, sess, db_sess: content,
        ):
            result = await sm.process_message(
                session_id=session_id,
                guest_message="hello",
                db=db,
            )

        # instructions_html is a separate top-level key
        assert "instructions_html" in result
        assert result["instructions_html"] == sample_html

        # agent_content does NOT contain HTML tags
        agent_content = result["agent_content"]
        assert "<div" not in agent_content
        assert "<h2>" not in agent_content
        assert "<p>" not in agent_content

    @pytest.mark.asyncio
    async def test_instructions_html_not_duplicated_on_subsequent_message(
        self, seeded_completed
    ):
        """When a COMPLETED session receives a second message,
        arrival instructions must NOT be re-appended to agent_content.

        This tests the dedup bug: previously, every call to
        _process_guest_message would concatenate instructions HTML
        into agent_content for COMPLETED sessions, causing duplication.
        Now, instructions_html is a separate field and is never
        concatenated into agent_content.
        """
        db = seeded_completed["db"]
        session_id = seeded_completed["session_id"]

        sample_html = (
            "<div class='instructions'>"
            "<h2>Arrival Instructions</h2>"
            "<p>Lockbox code: 9911</p>"
            "</div>"
        )

        sm = SessionManager()

        # First message (enters COMPLETED)
        with patch.object(
            sm, "_detect_intent", new_callable=AsyncMock, return_value="agree"
        ), patch.object(
            sm, "_extract_entities", new_callable=AsyncMock, return_value={}
        ), patch.object(
            sm, "_route_tool", new_callable=AsyncMock,
            return_value=(None, None),
        ), patch.object(
            sm, "_advance_state", new_callable=AsyncMock,
            return_value=(
                "Your check-in is complete! Here are your arrival instructions.",
                State.COMPLETED,
                sample_html,
            ),
        ), patch.object(
            sm, "_enrich_response",
            side_effect=lambda content, state, sess, db_sess: content,
        ):
            result1 = await sm.process_message(
                session_id=session_id,
                guest_message="agree",
                db=db,
            )

        content1 = result1["agent_content"]

        # Second message to the same COMPLETED session
        with patch.object(
            sm, "_detect_intent", new_callable=AsyncMock, return_value="greeting"
        ), patch.object(
            sm, "_extract_entities", new_callable=AsyncMock, return_value={}
        ), patch.object(
            sm, "_route_tool", new_callable=AsyncMock,
            return_value=(None, None),
        ), patch.object(
            sm, "_advance_state", new_callable=AsyncMock,
            return_value=(
                "Your check-in is complete! Here are your arrival instructions.",
                State.COMPLETED,
                sample_html,
            ),
        ), patch.object(
            sm, "_enrich_response",
            side_effect=lambda content, state, sess, db_sess: content,
        ):
            result2 = await sm.process_message(
                session_id=session_id,
                guest_message="hi again",
                db=db,
            )

        content2 = result2["agent_content"]

        # The second message's agent_content should NOT contain
        # the instructions HTML concatenated into it
        assert "<div" not in content2
        assert "<h2>" not in content2

        # Also: the second content should not be a doubled version
        # of the first content (no duplication of plain text either)
        # The content should be the same template, not template repeated
        assert content2 == content1  # same base text, no duplication

        # instructions_html is still available separately
        assert result2["instructions_html"] == sample_html
