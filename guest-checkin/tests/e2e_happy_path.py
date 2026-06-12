#!/usr/bin/env python3
"""End-to-end test: creates a session → sends 6 messages (one for each
step) → verifies state advances → gets arrival instructions.

Uses an in-memory SQLite database so no MySQL/Docker is needed.
Ollama is NOT required — the regex fallback handles all intents.

Run:  python3 tests/e2e_happy_path.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# ── Patch database to use SQLite ──────────────────────────────────
import app.database as _db_mod

# Override the engine + session factory before anything else imports them
_SQLITE_URL = "sqlite+aiosqlite:///./test_e2e.db"

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

test_engine = create_async_engine(
    _SQLITE_URL, echo=False, connect_args={"check_same_thread": False}
)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)

# Monkey-patch the module-level objects
_db_mod.engine = test_engine
_db_mod.async_session_factory = test_session_factory


async def main() -> None:
    # Now import the rest (they will pick up the patched DB)
    from app.database import Base, get_db
    from app.models.session import Session
    from app.models.reservation import Reservation
    from app.models.guest import Guest
    from app.models.api_key import APIKey
    from app.mcp_tools.registry import tool_registry
    from app.session_manager import SessionManager
    from app.state_machine.states import State
    from app.state_machine.transitions import get_required_action
    from app.auth.session_token import generate_session_token

    # ── Create tables ────────────────────────────────────────────
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created")

    # ── Seed data ────────────────────────────────────────────────
    async with test_session_factory() as db:
        # API key
        api_key = APIKey(
            key="test-e2e-api-key",
            name="E2E Test Key",
            is_active=True,
        )
        db.add(api_key)

        # Reservation
        reservation = Reservation(
            booking_reference="E2E-TEST-001",
            property_name="Sunset Villa",
            property_address="123 Beach Rd, Malibu, CA",
            guest_name="Jane Doe",
            guest_email="jane@example.com",
            guest_phone="+1234567890",
            check_in_date=date(2025, 7, 1),
            check_out_date=date(2025, 7, 7),
            num_guests=2,
            wifi_network="VillaWiFi",
            wifi_password="beach2025",
            lockbox_code="4321",
            emergency_contact="+18005551234",
            house_rules_text="No smoking. No parties. Quiet hours 10pm-8am.",
            rental_agreement_text="Standard rental agreement terms apply.",
            privacy_policy_text="We respect your privacy. Data usage per policy.",
        )
        db.add(reservation)

        # Guest
        guest = Guest(
            email="jane@example.com",
            first_name="Jane",
            last_name="Doe",
            phone="+1234567890",
        )
        db.add(guest)

        await db.commit()

        # Refresh to get IDs
        await db.refresh(reservation)
        await db.refresh(guest)
        reservation_id = reservation.id
        guest_id = guest.id

    print(f"✓ Seed data created (reservation={reservation_id}, guest={guest_id})")

    # ── Initialize tool registry ─────────────────────────────────
    if not tool_registry.get_tool_names():
        tool_registry.register_all()
    print(f"✓ Tool registry initialized ({len(tool_registry.get_tool_names())} tools)")

    # ── Create session ───────────────────────────────────────────
    async with test_session_factory() as db:
        session = Session(
            reservation_id=reservation_id,
            guest_id=guest_id,
            session_token=generate_session_token(),
            current_state="INIT",
            status="active",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    print(f"✓ Session created: {session_id}")
    print(f"  Initial state: INIT")

    # ── Process messages through SessionManager ──────────────────
    sm = SessionManager()

    messages = [
        ("Let's start the check-in", "start", "PRIVACY_POLICY_PENDING"),
        ("Yes, I agree to the privacy policy", "agree", "HOUSE_RULES_PENDING"),
        ("I accept the house rules", "agree", "RENTAL_AGREEMENT_PENDING"),
        ("I accept the rental agreement", "agree", "INFO_VERIFY_PENDING"),
        ("I confirm my information is correct", "confirm", "INFO_VERIFY_PENDING"),  # triggers OTP, stays
        ("123456", "verify_otp", "ID_VERIFY_PENDING"),  # OTP code → advance to ID
        ("I have uploaded my ID", "upload_id", "INCIDENTAL_PROTECTION_PENDING"),
        ("I select the damage waiver option", "select_option", "COMPLETED"),
    ]

    all_passed = True

    for i, (guest_msg, expected_intent, expected_next_state) in enumerate(messages, 1):
        async with test_session_factory() as db:
            try:
                result = await sm.process_message(
                    session_id=session_id,
                    guest_message=guest_msg,
                    db=db,
                )
                await db.commit()

                actual_state = result["current_state"]
                intent_detected = result["intent_detected"]
                agent_content = result["agent_content"]
                required_action = result["required_action"]

                # Verify state advanced correctly
                if actual_state != expected_next_state:
                    print(f"\n✗ Step {i} FAILED:")
                    print(f"  Message:     {guest_msg!r}")
                    print(f"  Intent:      {intent_detected}")
                    print(f"  Expected:    {expected_next_state}")
                    print(f"  Actual:      {actual_state}")
                    all_passed = False
                else:
                    print(f"\n✓ Step {i}: {guest_msg!r}")
                    print(f"  Intent:      {intent_detected}")
                    print(f"  State:       {actual_state}")
                    print(f"  Action:      {required_action}")
                    print(f"  Agent:       {agent_content[:80]}...")

            except Exception as exc:
                print(f"\n✗ Step {i} EXCEPTION: {exc}")
                import traceback
                traceback.print_exc()
                all_passed = False

    # ── Verify arrival instructions ──────────────────────────────
    async with test_session_factory() as db:
        instructions = await sm.get_arrival_instructions(session_id, db)
        if instructions:
            print(f"\n✓ Arrival instructions retrieved ({len(instructions)} chars)")
        else:
            print("\n⚠ No arrival instructions (tool may not have data)")

    # ── Verify final state ───────────────────────────────────────
    async with test_session_factory() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(Session).where(Session.id == session_id)
        )
        final_session = result.scalar_one()
        print(f"\n✓ Final session state: {final_session.current_state}")
        print(f"  Session status: {final_session.status}")

        # Count messages
        from app.models.message import Message
        result = await db.execute(
            select(Message).where(Message.session_id == session_id)
        )
        messages_list = result.scalars().all()
        print(f"  Total messages: {len(messages_list)}")
        for msg in messages_list:
            print(f"    [{msg.role}] {msg.content[:60]}... (intent={msg.intent_detected})")

    # ── Test decline path ────────────────────────────────────────
    print("\n\n── Testing Decline Path ──")
    async with test_session_factory() as db:
        decline_session = Session(
            reservation_id=reservation_id,
            guest_id=guest_id,
            session_token=generate_session_token(),
            current_state="INIT",
            status="active",
        )
        db.add(decline_session)
        await db.commit()
        await db.refresh(decline_session)
        decline_session_id = decline_session.id

    # Start → agree to privacy → decline house rules
    async with test_session_factory() as db:
        result = await sm.process_message(
            session_id=decline_session_id,
            guest_message="Let's start",
            db=db,
        )
        await db.commit()
        print(f"  After 'start': state={result['current_state']}")

    async with test_session_factory() as db:
        result = await sm.process_message(
            session_id=decline_session_id,
            guest_message="I agree to the privacy policy",
            db=db,
        )
        await db.commit()
        print(f"  After 'agree' privacy: state={result['current_state']}")

    async with test_session_factory() as db:
        result = await sm.process_message(
            session_id=decline_session_id,
            guest_message="I decline the house rules",
            db=db,
        )
        await db.commit()
        print(f"  After 'decline' house rules: state={result['current_state']}")
        if result["current_state"] == "REFUSED":
            print("  ✓ Decline path works correctly")
        else:
            print(f"  ✗ Expected REFUSED, got {result['current_state']}")
            all_passed = False

    # ── Test resume path ─────────────────────────────────────────
    print("\n── Testing Resume Path ──")
    async with test_session_factory() as db:
        from app.state_machine import StateMachine
        sm_machine = StateMachine(db_session=db, session_id=decline_session_id)
        new_state = await sm_machine.resume()
        await db.commit()
        print(f"  After resume: state={new_state.value}")
        if new_state == State.INIT:
            print("  ✓ Resume path works correctly")
        else:
            print(f"  ✗ Expected INIT, got {new_state.value}")
            all_passed = False

    # ── Test question handling ───────────────────────────────────
    print("\n── Testing Question Handling ──")
    async with test_session_factory() as db:
        # Use the resumed session (INIT state)
        result = await sm.process_message(
            session_id=decline_session_id,
            guest_message="What time is check-in?",
            db=db,
        )
        await db.commit()
        print(f"  Question at INIT: intent={result['intent_detected']}")
        print(f"  State: {result['current_state']}")
        print(f"  Agent: {result['agent_content'][:80]}...")

    # ── Cleanup ──────────────────────────────────────────────────
    import os
    try:
        os.unlink("./test_e2e.db")
    except FileNotFoundError:
        pass

    # ── Final result ─────────────────────────────────────────────
    if all_passed:
        print("\n" + "=" * 50)
        print("  ALL E2E TESTS PASSED ✓")
        print("=" * 50)
        sys.exit(0)
    else:
        print("\n" + "=" * 50)
        print("  SOME E2E TESTS FAILED ✗")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
