"""Unit tests for the state machine — states, transitions, audit trail."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.reservation import Reservation
from app.models.session import Session
from app.state_machine import (
    ActionRequiredError,
    InvalidTransitionError,
    SessionNotFoundError,
    State,
    StateMachine,
    VALID_TRANSITIONS,
    can_transition,
    get_next_state,
    get_required_action,
)
from app.state_machine.audit import log_audit

# ── In-memory SQLite for DB-dependent tests ────────────────────────

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
async def db():
    """Provide a clean async DB session for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_session_row(db: AsyncSession) -> Session:
    """Insert a minimal session row (with guest + reservation) and return it."""
    reservation = Reservation(
        booking_reference=f"BR-{uuid.uuid4().hex[:8]}",
        guest_name="Test Guest",
        guest_email="test@example.com",
        property_name="Test Property",
        property_address="123 Test St",
        check_in_date=date(2025, 7, 1),
        check_out_date=date(2025, 7, 5),
        house_rules_text="No smoking",
        rental_agreement_text="Standard rental terms",
        privacy_policy_text="We respect your privacy",
    )
    db.add(reservation)
    await db.flush()

    guest = Guest(
        email=f"guest-{uuid.uuid4().hex[:8]}@example.com",
        first_name="Test",
        last_name="Guest",
    )
    db.add(guest)
    await db.flush()

    session = Session(
        id=str(uuid.uuid4()),
        reservation_id=reservation.id,
        guest_id=guest.id,
        session_token=f"tok-{uuid.uuid4().hex[:12]}",
        current_state=State.INIT.value,
    )
    db.add(session)
    await db.flush()
    return session


def _make_sm(db: AsyncSession, session: Session) -> StateMachine:
    """Return a StateMachine bound to the given session."""
    return StateMachine(db_session=db, session_id=session.id)


async def _advance_full_flow(sm: StateMachine) -> State:
    """Advance the state machine through the happy path and return final state."""
    await sm.advance("start")
    await sm.advance("agree")  # PRIVACY → HOUSE_RULES
    await sm.advance("agree")  # HOUSE_RULES → RENTAL
    await sm.advance("agree")  # RENTAL → INFO_VERIFY
    await sm.advance("confirm")  # INFO_VERIFY → ID_VERIFY
    await sm.advance("upload_id")  # ID_VERIFY → INCIDENTAL
    return await sm.advance("select_option")  # INCIDENTAL → COMPLETED


# ═══════════════════════════════════════════════════════════════════
# Pure unit tests (no DB required)
# ═══════════════════════════════════════════════════════════════════


class TestStateEnum:
    """Tests for the State enum and STATE_INFO definitions."""

    def test_all_states_defined(self):
        expected = {
            "INIT",
            "PRIVACY_POLICY_PENDING",
            "HOUSE_RULES_PENDING",
            "RENTAL_AGREEMENT_PENDING",
            "INFO_VERIFY_PENDING",
            "ID_VERIFY_PENDING",
            "INCIDENTAL_PROTECTION_PENDING",
            "COMPLETED",
            "REFUSED",
        }
        actual = {s.value for s in State}
        assert actual == expected

    def test_state_is_str_subclass(self):
        assert isinstance(State.INIT, str)
        assert State.INIT == "INIT"

    def test_state_info_keys_match_enum(self):
        from app.state_machine.states import STATE_INFO
        assert set(STATE_INFO.keys()) == set(State)

    def test_state_info_fields_present(self):
        from app.state_machine.states import STATE_INFO
        for state, info in STATE_INFO.items():
            assert "required_action" in info, f"{state} missing required_action"
            assert "valid_intents" in info, f"{state} missing valid_intents"
            assert "on_enter" in info, f"{state} missing on_enter"
            assert "description" in info, f"{state} missing description"

    def test_completed_has_no_valid_intents(self):
        from app.state_machine.states import STATE_INFO
        assert STATE_INFO[State.COMPLETED]["valid_intents"] == []


class TestTransitions:
    """Tests for transition validation functions."""

    def test_can_transition_valid(self):
        assert can_transition(State.INIT, "start") is True
        assert can_transition(State.PRIVACY_POLICY_PENDING, "agree") is True
        assert can_transition(State.REFUSED, "resume") is True

    def test_can_transition_invalid(self):
        assert can_transition(State.INIT, "agree") is False
        assert can_transition(State.COMPLETED, "start") is False
        assert can_transition(State.PRIVACY_POLICY_PENDING, "confirm") is False

    def test_get_next_state_valid(self):
        assert get_next_state(State.INIT, "start") == State.PRIVACY_POLICY_PENDING
        assert get_next_state(State.PRIVACY_POLICY_PENDING, "agree") == State.HOUSE_RULES_PENDING
        assert get_next_state(State.REFUSED, "resume") == State.INIT

    def test_get_next_state_invalid_raises(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            get_next_state(State.COMPLETED, "start")
        assert exc_info.value.current_state == "COMPLETED"
        assert exc_info.value.intent == "start"

    def test_get_next_state_skip_raises(self):
        with pytest.raises(InvalidTransitionError):
            get_next_state(State.INIT, "agree")

    def test_get_required_action(self):
        action = get_required_action(State.PRIVACY_POLICY_PENDING)
        assert "Privacy Policy" in action

    def test_get_required_action_completed(self):
        action = get_required_action(State.COMPLETED)
        assert "None" in action or "finished" in action.lower()

    def test_decline_transitions_to_refused(self):
        agreement_states = [
            State.PRIVACY_POLICY_PENDING,
            State.HOUSE_RULES_PENDING,
            State.RENTAL_AGREEMENT_PENDING,
        ]
        for state in agreement_states:
            assert can_transition(state, "decline") is True
            assert get_next_state(state, "decline") == State.REFUSED

    def test_non_agreement_states_cannot_decline(self):
        non_agreement_states = [
            State.INIT,
            State.INFO_VERIFY_PENDING,
            State.ID_VERIFY_PENDING,
            State.INCIDENTAL_PROTECTION_PENDING,
            State.COMPLETED,
        ]
        for state in non_agreement_states:
            assert can_transition(state, "decline") is False

    def test_provide_info_stays_in_info_verify(self):
        assert get_next_state(State.INFO_VERIFY_PENDING, "provide_info") == State.INFO_VERIFY_PENDING

    def test_all_transition_keys_use_state_enum(self):
        for from_state, intent in VALID_TRANSITIONS:
            assert isinstance(from_state, State)
            assert isinstance(intent, str)


class TestExceptions:
    """Tests for custom exception classes."""

    def test_invalid_transition_error(self):
        err = InvalidTransitionError("COMPLETED", "start")
        assert err.current_state == "COMPLETED"
        assert err.intent == "start"
        assert "COMPLETED" in str(err)
        assert "start" in str(err)

    def test_session_not_found_error(self):
        err = SessionNotFoundError("abc-123")
        assert err.session_id == "abc-123"
        assert "abc-123" in str(err)

    def test_action_required_error(self):
        err = ActionRequiredError("INFO_VERIFY_PENDING", "Confirm your info")
        assert err.current_state == "INFO_VERIFY_PENDING"
        assert err.required_action == "Confirm your info"
        assert "INFO_VERIFY_PENDING" in str(err)


# ═══════════════════════════════════════════════════════════════════
# DB-dependent integration tests
# ═══════════════════════════════════════════════════════════════════


class TestStateMachineAdvance:
    """Tests for StateMachine.advance()."""

    @pytest.mark.asyncio
    async def test_advance_start(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        new_state = await sm.advance("start")
        assert new_state == State.PRIVACY_POLICY_PENDING
        await db.commit()

    @pytest.mark.asyncio
    async def test_advance_full_happy_path(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        final = await _advance_full_flow(sm)
        assert final == State.COMPLETED
        await db.commit()

    @pytest.mark.asyncio
    async def test_advance_updates_db(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await db.commit()
        await db.refresh(session)
        assert session.current_state == State.PRIVACY_POLICY_PENDING.value

    @pytest.mark.asyncio
    async def test_advance_invalid_raises(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        with pytest.raises(InvalidTransitionError):
            await sm.advance("agree")

    @pytest.mark.asyncio
    async def test_advance_completed_raises(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await _advance_full_flow(sm)
        with pytest.raises(InvalidTransitionError):
            await sm.advance("start")

    @pytest.mark.asyncio
    async def test_advance_with_guest_response(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start", guest_response="Let's begin")
        await db.commit()

    @pytest.mark.asyncio
    async def test_advance_nonexistent_session_raises(self, db):
        sm = StateMachine(db_session=db, session_id=str(uuid.uuid4()))
        with pytest.raises(SessionNotFoundError):
            await sm.advance("start")


class TestStateMachineDecline:
    """Tests for StateMachine.decline()."""

    @pytest.mark.asyncio
    async def test_decline_privacy_policy(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        new_state = await sm.decline("I disagree with the privacy policy")
        assert new_state == State.REFUSED
        await db.commit()

    @pytest.mark.asyncio
    async def test_decline_house_rules(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.advance("agree")
        new_state = await sm.decline("I don't accept the house rules")
        assert new_state == State.REFUSED
        await db.commit()

    @pytest.mark.asyncio
    async def test_decline_rental_agreement(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.advance("agree")
        await sm.advance("agree")
        new_state = await sm.decline()
        assert new_state == State.REFUSED
        await db.commit()

    @pytest.mark.asyncio
    async def test_decline_invalid_state_raises(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        with pytest.raises(InvalidTransitionError):
            await sm.decline()

    @pytest.mark.asyncio
    async def test_decline_updates_db(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline()
        await db.commit()
        await db.refresh(session)
        assert session.current_state == State.REFUSED.value


class TestStateMachineResume:
    """Tests for StateMachine.resume()."""

    @pytest.mark.asyncio
    async def test_resume_from_refused(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline()
        new_state = await sm.resume()
        assert new_state == State.INIT
        await db.commit()

    @pytest.mark.asyncio
    async def test_resume_from_active_state_raises(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        with pytest.raises(InvalidTransitionError):
            await sm.resume()

    @pytest.mark.asyncio
    async def test_resume_updates_db(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline()
        await sm.resume()
        await db.commit()
        await db.refresh(session)
        assert session.current_state == State.INIT.value

    @pytest.mark.asyncio
    async def test_resume_and_restart_happy_path(self, db):
        """After resume, the guest can complete the full flow again."""
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline()
        await sm.resume()
        final = await _advance_full_flow(sm)
        assert final == State.COMPLETED
        await db.commit()


class TestStateMachineGetCurrentState:
    """Tests for StateMachine.get_current_state()."""

    @pytest.mark.asyncio
    async def test_initial_state(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        state, action = await sm.get_current_state()
        assert state == State.INIT
        assert "Initialize" in action

    @pytest.mark.asyncio
    async def test_state_after_advance(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        state, action = await sm.get_current_state()
        assert state == State.PRIVACY_POLICY_PENDING
        assert "Privacy Policy" in action

    @pytest.mark.asyncio
    async def test_state_after_completion(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await _advance_full_flow(sm)
        state, action = await sm.get_current_state()
        assert state == State.COMPLETED

    @pytest.mark.asyncio
    async def test_nonexistent_session_raises(self, db):
        sm = StateMachine(db_session=db, session_id=str(uuid.uuid4()))
        with pytest.raises(SessionNotFoundError):
            await sm.get_current_state()


class TestAuditTrail:
    """Tests that every transition creates an AuditTrail record."""

    @pytest.mark.asyncio
    async def test_advance_creates_audit_entry(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].action == "advance"
        assert entries[0].from_state == State.INIT.value
        assert entries[0].to_state == State.PRIVACY_POLICY_PENDING.value
        assert entries[0].actor == "guest"
        assert entries[0].details["intent"] == "start"

    @pytest.mark.asyncio
    async def test_decline_creates_audit_entry(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline("I decline the privacy policy")
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 2
        decline_entry = [e for e in entries if e.action == "decline"][0]
        assert decline_entry.from_state == State.PRIVACY_POLICY_PENDING.value
        assert decline_entry.to_state == State.REFUSED.value
        assert decline_entry.details["guest_response"] == "I decline the privacy policy"

    @pytest.mark.asyncio
    async def test_resume_creates_audit_entry(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start")
        await sm.decline()
        await sm.resume()
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entries = result.scalars().all()
        resume_entry = [e for e in entries if e.action == "resume"][0]
        assert resume_entry.from_state == State.REFUSED.value
        assert resume_entry.to_state == State.INIT.value
        assert resume_entry.actor == "system"

    @pytest.mark.asyncio
    async def test_full_flow_creates_audit_trail(self, db):
        """Every transition in the happy path creates an audit entry."""
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await _advance_full_flow(sm)
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 7

        state_chain = [(e.from_state, e.to_state) for e in entries]
        expected_chain = [
            ("INIT", "PRIVACY_POLICY_PENDING"),
            ("PRIVACY_POLICY_PENDING", "HOUSE_RULES_PENDING"),
            ("HOUSE_RULES_PENDING", "RENTAL_AGREEMENT_PENDING"),
            ("RENTAL_AGREEMENT_PENDING", "INFO_VERIFY_PENDING"),
            ("INFO_VERIFY_PENDING", "ID_VERIFY_PENDING"),
            ("ID_VERIFY_PENDING", "INCIDENTAL_PROTECTION_PENDING"),
            ("INCIDENTAL_PROTECTION_PENDING", "COMPLETED"),
        ]
        assert state_chain == expected_chain

    @pytest.mark.asyncio
    async def test_audit_guest_response_captured(self, db):
        session = await _make_session_row(db)
        sm = _make_sm(db, session)
        await sm.advance("start", guest_response="Ready to check in")
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entry = result.scalar_one()
        assert entry.details["guest_response"] == "Ready to check in"

    @pytest.mark.asyncio
    async def test_log_audit_directly(self, db):
        """Test the standalone log_audit function."""
        session = await _make_session_row(db)
        await log_audit(
            db_session=db,
            session_id=session.id,
            action="test_action",
            from_state=State.INIT,
            to_state=State.COMPLETED,
            details={"key": "value"},
            actor="system",
        )
        await db.commit()

        result = await db.execute(
            select(AuditTrail).where(AuditTrail.session_id == session.id)
        )
        entry = result.scalar_one()
        assert entry.action == "test_action"
        assert entry.from_state == "INIT"
        assert entry.to_state == "COMPLETED"
        assert entry.details == {"key": "value"}
        assert entry.actor == "system"
