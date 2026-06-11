"""Tests for app/utils.py — shared helper functions.

Covers:
- agreement_type_for_state() for all known states
- answer_question() with knowledge base entries
- Import provenance: session_manager and fallback import from app.utils, not local duplicates
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.state_machine.states import State
from app.utils import agreement_type_for_state, answer_question

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── agreement_type_for_state ──────────────────────────────────────


class TestAgreementTypeForState:
    """agreement_type_for_state returns correct type for agreement states."""

    def test_privacy_policy_pending(self):
        assert agreement_type_for_state(State.PRIVACY_POLICY_PENDING) == "privacy_policy"

    def test_house_rules_pending(self):
        assert agreement_type_for_state(State.HOUSE_RULES_PENDING) == "house_rules"

    def test_rental_agreement_pending(self):
        assert agreement_type_for_state(State.RENTAL_AGREEMENT_PENDING) == "rental_agreement"

    def test_non_agreement_states_return_none(self):
        """States without an agreement type should return None."""
        non_agreement_states = [
            State.INIT,
            State.INFO_VERIFY_PENDING,
            State.ID_VERIFY_PENDING,
            State.INCIDENTAL_PROTECTION_PENDING,
            State.COMPLETED,
            State.REFUSED,
        ]
        for state in non_agreement_states:
            assert agreement_type_for_state(state) is None, (
                f"Expected None for {state}, got {agreement_type_for_state(state)}"
            )


# ── answer_question ───────────────────────────────────────────────


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite session with all tables."""
    from app.database import Base
    from app.models import (  # noqa: F401
        Agreement, APIKey, AuditTrail, Guest,
        IncidentalSelection, KnowledgeBase, Message,
        OTPVerification, Reservation, Session,
    )

    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def seeded_kb(db_session: AsyncSession):
    """Seed knowledge base entries and return them."""
    from app.models.knowledge_base import KnowledgeBase

    entries = [
        KnowledgeBase(
            id=str(uuid.uuid4()),
            property_id="prop-1",
            question="What is the WiFi password?",
            answer="The WiFi password is ocean2024.",
            category="amenities",
        ),
        KnowledgeBase(
            id=str(uuid.uuid4()),
            property_id="prop-1",
            question="What time is checkout?",
            answer="Checkout is at 11:00 AM.",
            category="policies",
        ),
    ]
    for entry in entries:
        db_session.add(entry)
    await db_session.flush()
    return entries


class TestAnswerQuestion:
    """answer_question queries the knowledge base for matching answers."""

    @pytest.mark.asyncio
    async def test_returns_answer_for_matching_question(
        self, db_session, seeded_kb
    ):
        """A question containing keywords from a KB entry returns the answer."""
        mock_session = MagicMock()
        result = await answer_question(
            mock_session, "wifi password", db_session
        )
        # "wifi" and "password" match the WiFi entry
        assert result == "The WiFi password is ocean2024."

    @pytest.mark.asyncio
    async def test_returns_answer_for_checkout_question(
        self, db_session, seeded_kb
    ):
        """Question matching keywords from a KB entry returns the matching answer.

        Note: answer_question() does simple keyword matching and returns the
        first entry whose question words overlap with the query. The exact
        entry returned depends on iteration order. We verify the result is
        one of the KB answers (not None) and is a valid string.
        """
        mock_session = MagicMock()
        result = await answer_question(
            mock_session, "checkout time", db_session
        )
        # "checkout" and "time" should match the checkout KB entry
        # (no overlap with WiFi entry which has "what", "is", "the", "wifi", "password")
        assert result == "Checkout is at 11:00 AM."

    @pytest.mark.asyncio
    async def test_returns_none_for_no_match(self, db_session, seeded_kb):
        """A question that doesn't match any KB entry returns None."""
        mock_session = MagicMock()
        result = await answer_question(
            mock_session, "xylophone zebra", db_session
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_kb_empty(self, db_session):
        """If the knowledge base has no entries, return None."""
        mock_session = MagicMock()
        result = await answer_question(
            mock_session, "WiFi password", db_session
        )
        assert result is None


# ── Import provenance ─────────────────────────────────────────────


class TestImportProvenance:
    """Verify session_manager and fallback import from app.utils, not local duplicates."""

    def test_session_manager_imports_from_utils(self):
        """session_manager.py imports agreement_type_for_state and answer_question from app.utils."""
        import app.session_manager as sm
        assert sm.agreement_type_for_state is agreement_type_for_state
        assert sm.answer_question is answer_question

    def test_fallback_imports_from_utils(self):
        """fallback.py imports agreement_type_for_state and answer_question from app.utils."""
        import app.agent.fallback as fb
        assert fb.agreement_type_for_state is agreement_type_for_state
        assert fb.answer_question is answer_question

    def test_no_local_agreement_type_in_session_manager(self):
        """session_manager.py should NOT have a local _agreement_type_for_state."""
        import inspect
        source = inspect.getsource(__import__("app.session_manager", fromlist=["session_manager"]))
        assert "_agreement_type_for_state" not in source, (
            "Found local _agreement_type_for_state in session_manager.py — should be imported from utils"
        )

    def test_no_local_answer_question_in_session_manager(self):
        """session_manager.py should NOT have a local _answer_question."""
        import inspect
        source = inspect.getsource(__import__("app.session_manager", fromlist=["session_manager"]))
        assert "_answer_question" not in source, (
            "Found local _answer_question in session_manager.py — should be imported from utils"
        )

    def test_no_local_agreement_type_in_fallback(self):
        """fallback.py should NOT have a local _agreement_type_for_state."""
        import inspect
        source = inspect.getsource(__import__("app.agent.fallback", fromlist=["fallback"]))
        assert "_agreement_type_for_state" not in source, (
            "Found local _agreement_type_for_state in fallback.py — should be imported from utils"
        )

    def test_no_local_answer_question_in_fallback(self):
        """fallback.py should NOT have a local _answer_question."""
        import inspect
        source = inspect.getsource(__import__("app.agent.fallback", fromlist=["fallback"]))
        assert "_answer_question" not in source, (
            "Found local _answer_question in fallback.py — should be imported from utils"
        )
