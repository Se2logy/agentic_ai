"""
SEC-OTP-001: OTP API uses hmac.compare_digest for constant-time comparison.

Test approach:
1. Inspect source code of app/mcp_tools/otp_tools.py to confirm verify_otp uses hmac.compare_digest
2. Inspect app/api/otp.py to confirm it delegates to otp_tools (no direct comparison)
3. Mock verification: patch hmac.compare_digest in otp_tools, trigger OTP then verify, confirm mock was called
4. Supplementary: run 100 iterations of correct vs incorrect OTP verification, measure timing variance
   (std dev should be below 50ms threshold)
"""

import ast
import inspect
import statistics
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
async def db_engine():
    from app.database import Base
    from app.models import (  # noqa: F401
        Agreement, APIKey, AuditTrail, Guest,
        IncidentalSelection, KnowledgeBase, Message,
        OTPVerification, Reservation, Session,
    )
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
async def seeded(db_session: AsyncSession):
    """Seed guest, reservation, session. Returns dict with IDs."""
    from app.models.guest import Guest
    from app.models.reservation import Reservation
    from app.models.session import Session as Sess

    g = Guest(
        id=str(uuid.uuid4()), email="test@example.com",
        first_name="Alice", last_name="Johnson", phone="+1-555-0101",
    )
    db_session.add(g)
    await db_session.flush()

    r = Reservation(
        id=str(uuid.uuid4()), booking_reference="BK-SEC-OTP-001",
        property_name="Test Cottage",
        property_address="1 Test Lane",
        guest_name="Alice Johnson", guest_email="test@example.com",
        guest_phone="+1-555-0101",
        check_in_date=date(2024, 7, 1), check_out_date=date(2024, 7, 7),
        num_guests=2, wifi_network="TestWiFi", wifi_password="pass123",
        lockbox_code="1234", emergency_contact="+1-555-0911",
        house_rules_text="No smoking.", rental_agreement_text="Std.",
        privacy_policy_text="We respect your privacy.",
    )
    db_session.add(r)
    await db_session.flush()

    s = Sess(
        id=str(uuid.uuid4()), reservation_id=r.id, guest_id=g.id,
        current_state="INFO_VERIFY_PENDING",
        session_token="tok-sec-otp-001", status="active",
    )
    db_session.add(s)
    await db_session.flush()

    return {"db": db_session, "sid": s.id, "token": "tok-sec-otp-001"}


# ── Step 1: Source code inspection — otp_tools.py ───────────────────


class TestOtpToolsSourceInspection:
    """Verify that app/mcp_tools/otp_tools.py uses hmac.compare_digest
    and does NOT use == for OTP code comparison."""

    def test_verify_otp_uses_hmac_compare_digest(self):
        """SEC-OTP-001: verify_otp must use hmac.compare_digest for OTP comparison."""
        from app.mcp_tools import otp_tools
        source = inspect.getsource(otp_tools.verify_otp)
        assert "hmac.compare_digest" in source, (
            "verify_otp does NOT use hmac.compare_digest for comparison. "
            "This is a timing-attack vulnerability."
        )

    def test_verify_otp_no_direct_equality_comparison(self):
        """SEC-OTP-001: verify_otp must NOT use == for OTP code comparison."""
        from app.mcp_tools import otp_tools
        source = inspect.getsource(otp_tools.verify_otp)

        # Parse the function AST and look for == comparisons involving otp_code or otp_record.otp_code
        tree = ast.parse(source)
        eq_comparisons = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, ast.Eq):
                        # Get the left side as a string for inspection
                        left_str = ast.unparse(node.left) if hasattr(ast, 'unparse') else ""
                        for comparator in node.comparators:
                            comp_str = ast.unparse(comparator) if hasattr(ast, 'unparse') else ""
                            full = f"{left_str} == {comp_str}"
                            # Filter: only flag comparisons involving otp_code
                            if "otp_code" in full:
                                eq_comparisons.append(full)

        assert len(eq_comparisons) == 0, (
            f"verify_otp uses direct == comparison for OTP codes: {eq_comparisons}. "
            "This is vulnerable to timing attacks. Use hmac.compare_digest instead."
        )

    def test_otp_tools_imports_hmac(self):
        """SEC-OTP-001: otp_tools.py must import hmac module."""
        from app.mcp_tools import otp_tools
        source = inspect.getsource(otp_tools)
        assert "import hmac" in source, (
            "otp_tools.py does not import hmac. "
            "hmac.compare_digest is required for constant-time OTP comparison."
        )

    def test_otp_tools_imports_secrets(self):
        """SEC-OTP-002 (supplementary): otp_tools.py must import secrets module
        for cryptographically secure OTP generation."""
        from app.mcp_tools import otp_tools
        source = inspect.getsource(otp_tools)
        assert "import secrets" in source, (
            "otp_tools.py does not import secrets. "
            "secrets.randbelow/secrets.choice is required for secure OTP generation."
        )

    def test_trigger_otp_uses_secrets_not_random(self):
        """SEC-OTP-002 (supplementary): trigger_otp must use secrets.randbelow,
        not random.choices, for OTP generation."""
        from app.mcp_tools import otp_tools
        source = inspect.getsource(otp_tools.trigger_otp)
        assert "secrets.randbelow" in source or "secrets.choice" in source, (
            "trigger_otp does NOT use secrets.randbelow or secrets.choice for "
            "OTP generation. This is insecure — use CSPRNG, not random.choices."
        )
        assert "random.choices" not in source, (
            "trigger_otp uses random.choices which is NOT cryptographically secure. "
            "Use secrets.randbelow or secrets.choice instead."
        )


# ── Step 2: Source code inspection — api/otp.py ─────────────────────


class TestOtpApiSourceInspection:
    """Verify that app/api/otp.py delegates to otp_tools and does NOT
    perform any direct OTP code comparison."""

    def test_api_verify_delegates_to_otp_tools(self):
        """SEC-OTP-001: API verify endpoint must delegate to otp_tools.verify_otp."""
        from app.api import otp as otp_api
        source = inspect.getsource(otp_api.verify_otp)
        assert "otp_tools.verify_otp" in source, (
            "API verify_otp does NOT delegate to otp_tools.verify_otp. "
            "The API layer should be a thin HTTP wrapper around the secure MCP tool."
        )

    def test_api_no_direct_otp_comparison(self):
        """SEC-OTP-001: API layer must NOT contain any OTP code comparison logic."""
        from app.api import otp as otp_api
        source = inspect.getsource(otp_api)

        # The API file should NOT contain any == comparison involving otp_code
        # (it delegates everything to otp_tools)
        assert "otp_code ==" not in source and "== otp_code" not in source, (
            "API otp.py contains direct OTP code comparison (==). "
            "This should be handled by otp_tools.verify_otp using hmac.compare_digest."
        )
        assert "compare_digest" not in source, (
            "API otp.py contains compare_digest — this logic belongs in otp_tools, "
            "not the API layer. The API should be a thin HTTP wrapper."
        )

    def test_api_trigger_delegates_to_otp_tools(self):
        """SEC-OTP-002 (supplementary): API trigger endpoint delegates to otp_tools.trigger_otp."""
        from app.api import otp as otp_api
        source = inspect.getsource(otp_api.trigger_otp)
        assert "otp_tools.trigger_otp" in source, (
            "API trigger_otp does NOT delegate to otp_tools.trigger_otp. "
            "The API layer should be a thin HTTP wrapper around the secure MCP tool."
        )


# ── Step 3: Mock verification — patch hmac.compare_digest ───────────


class TestOtpToolsMockVerification:
    """Patch hmac.compare_digest in otp_tools, trigger OTP then verify,
    and confirm the mock was actually called (proving the code path
    goes through hmac.compare_digest)."""

    @pytest.mark.asyncio
    async def test_verify_otp_calls_hmac_compare_digest(self, seeded):
        """SEC-OTP-001: verify_otp must call hmac.compare_digest for comparison.
        Patch it and verify it's invoked."""
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp

        # Step 1: Trigger OTP (with email mocked)
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            trigger_result = await trigger_otp(seeded["db"], seeded["sid"])

        assert trigger_result["otp_sent"] is True, (
            f"OTP trigger failed: {trigger_result}"
        )

        # Step 2: Retrieve the generated OTP code from DB
        from app.models.otp_verification import OTPVerification
        stmt = select(OTPVerification).where(
            OTPVerification.session_id == seeded["sid"]
        )
        res = await seeded["db"].execute(stmt)
        otp_record = res.scalar_one()
        generated_code = otp_record.otp_code

        # Step 3: Patch hmac.compare_digest and verify it gets called
        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            return_value=True,  # Always return True so verify succeeds
        ) as mock_compare:
            result = await verify_otp(seeded["db"], seeded["sid"], generated_code)

            # The mock MUST have been called — this proves the code path
            # goes through hmac.compare_digest
            assert mock_compare.called, (
                "hmac.compare_digest was NOT called during OTP verification. "
                "The verify_otp function is not using hmac.compare_digest for "
                "code comparison. This is a timing-attack vulnerability."
            )
            # Verify it was called with the correct arguments
            assert mock_compare.call_count >= 1, (
                "hmac.compare_digest was not called at least once."
            )
            # Check that the call involved the OTP code
            call_args = mock_compare.call_args
            assert generated_code in call_args[0] or generated_code in str(call_args), (
                f"hmac.compare_digest was called but not with the expected OTP code. "
                f"Call args: {call_args}"
            )

        # Also verify the result indicates success (since our mock returns True)
        assert result["verified"] is True, (
            f"OTP verification should succeed with mocked compare_digest. Got: {result}"
        )

    @pytest.mark.asyncio
    async def test_verify_otp_wrong_code_still_calls_hmac(self, seeded):
        """SEC-OTP-001: Even with a wrong OTP code, hmac.compare_digest must be
        called (not short-circuited by == comparison before reaching compare_digest)."""
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp

        # Trigger OTP (with email mocked)
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            await trigger_otp(seeded["db"], seeded["sid"])

        # Verify with a WRONG code, patching compare_digest to return False
        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            return_value=False,
        ) as mock_compare:
            result = await verify_otp(seeded["db"], seeded["sid"], "000000")

            assert mock_compare.called, (
                "hmac.compare_digest was NOT called even for wrong OTP code. "
                "The code path must always use constant-time comparison regardless "
                "of whether the code is correct or not."
            )
            assert result["verified"] is False, (
                f"Wrong OTP code should not verify. Got: {result}"
            )
            assert result["attempts_remaining"] == 2, (
                f"Should have 2 attempts remaining after 1 wrong attempt. Got: {result}"
            )


# ── Step 4: Timing variance supplementary test ─────────────────────


class TestOtpTimingVariance:
    """Supplementary: Run 100 iterations of correct vs incorrect OTP verification,
    measure timing variance. Standard deviation should be below 50ms threshold.

    NOTE: This is a supplementary test — true constant-time guarantees are
    hardware-dependent and a strict statistical test would be flaky. Source
    inspection + mock verification are the primary assertions. This test
    provides supplementary evidence only.
    """

    @pytest.mark.asyncio
    async def test_timing_variance_below_threshold(self, seeded):
        """SEC-OTP-001 (supplementary): OTP verification timing for correct vs
        incorrect codes should not leak information. Run 100 iterations, measure
        timing variance (std dev < 50ms)."""
        import asyncio
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp
        from app.models.otp_verification import OTPVerification

        NUM_ITERATIONS = 100
        correct_times = []
        incorrect_times = []

        for i in range(NUM_ITERATIONS):
            # Trigger a fresh OTP each iteration
            with patch(
                "app.mcp_tools.otp_tools.email_service.send_otp_email",
                new_callable=AsyncMock, return_value=True,
            ):
                await trigger_otp(seeded["db"], seeded["sid"])

            # Get the generated code
            stmt = select(OTPVerification).where(
                OTPVerification.session_id == seeded["sid"],
                OTPVerification.verified == False,  # noqa: E712
            ).order_by(OTPVerification.created_at.desc())
            res = await seeded["db"].execute(stmt)
            otp_record = res.scalars().first()
            if otp_record is None:
                pytest.fail("No unverified OTP record found — test fixture issue")
            generated_code = otp_record.otp_code

            # Time correct OTP verification
            start = time.perf_counter()
            await verify_otp(seeded["db"], seeded["sid"], generated_code)
            correct_times.append(time.perf_counter() - start)

            # Trigger another OTP for incorrect test
            with patch(
                "app.mcp_tools.otp_tools.email_service.send_otp_email",
                new_callable=AsyncMock, return_value=True,
            ):
                await trigger_otp(seeded["db"], seeded["sid"])

            # Get the new code
            stmt = select(OTPVerification).where(
                OTPVerification.session_id == seeded["sid"],
                OTPVerification.verified == False,  # noqa: E712
            ).order_by(OTPVerification.created_at.desc())
            res = await seeded["db"].execute(stmt)
            otp_record = res.scalars().first()
            if otp_record is None:
                pytest.fail("No unverified OTP record found — test fixture issue")

            # Time incorrect OTP verification
            start = time.perf_counter()
            await verify_otp(seeded["db"], seeded["sid"], "000000")
            incorrect_times.append(time.perf_counter() - start)

        # Calculate statistics (in milliseconds)
        correct_ms = [t * 1000 for t in correct_times]
        incorrect_ms = [t * 1000 for t in incorrect_times]

        correct_mean = statistics.mean(correct_ms)
        incorrect_mean = statistics.mean(incorrect_ms)
        correct_std = statistics.stdev(correct_ms) if len(correct_ms) > 1 else 0
        incorrect_std = statistics.stdev(incorrect_ms) if len(incorrect_ms) > 1 else 0

        # The timing difference between correct and incorrect should not be significant
        mean_diff = abs(correct_mean - incorrect_mean)

        # Assert std dev is below 50ms (generous threshold — not a strict constant-time test)
        assert correct_std < 50, (
            f"Correct OTP timing std dev ({correct_std:.2f}ms) exceeds 50ms threshold. "
            f"Mean: {correct_mean:.2f}ms. This may indicate inconsistent comparison timing."
        )
        assert incorrect_std < 50, (
            f"Incorrect OTP timing std dev ({incorrect_std:.2f}ms) exceeds 50ms threshold. "
            f"Mean: {incorrect_mean:.2f}ms. This may indicate inconsistent comparison timing."
        )

        # The mean difference should not be large enough to distinguish correct from incorrect
        # A timing-attack-vulnerable == comparison typically shows measurable difference
        # This assertion uses a generous threshold
        assert mean_diff < 50, (
            f"Timing difference between correct ({correct_mean:.2f}ms) and incorrect "
            f"({incorrect_mean:.2f}ms) OTP verification is {mean_diff:.2f}ms, "
            f"exceeding the 50ms threshold. This may indicate timing leakage."
        )


# ── Step 5: Cross-state recovery (SEC-OTP-001 coverage) ────────────


class TestOtpRecoveryFlow:
    """SEC-OTP-001 coverage: Wrong OTP → retry with correct code → verified.
    Also: Wrong OTP 3 times → max attempts → must trigger new OTP."""

    @pytest.mark.asyncio
    async def test_wrong_otp_then_correct_recovers(self, seeded):
        """SEC-OTP-001 (CSR-SEC-003): After wrong OTP, retry with correct
        code should succeed. hmac.compare_digest must be used on both attempts."""
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp
        from app.models.otp_verification import OTPVerification

        # Trigger OTP
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            await trigger_otp(seeded["db"], seeded["sid"])

        # Get the generated code
        stmt = select(OTPVerification).where(
            OTPVerification.session_id == seeded["sid"]
        )
        res = await seeded["db"].execute(stmt)
        otp_record = res.scalar_one()
        generated_code = otp_record.otp_code

        # First attempt: wrong code (uses hmac.compare_digest)
        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            return_value=False,
        ) as mock_cmp:
            r1 = await verify_otp(seeded["db"], seeded["sid"], "000000")
            assert mock_cmp.called
        assert r1["verified"] is False
        assert r1["attempts_remaining"] == 2

        # Second attempt: correct code (uses hmac.compare_digest)
        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            return_value=True,
        ) as mock_cmp:
            r2 = await verify_otp(seeded["db"], seeded["sid"], generated_code)
            assert mock_cmp.called
        assert r2["verified"] is True

    @pytest.mark.asyncio
    async def test_max_attempts_then_new_otp(self, seeded):
        """SEC-OTP-001 (CSR-SEC-004): Wrong OTP 3 times → max attempts
        exceeded → must trigger new OTP. hmac.compare_digest is used
        on each wrong attempt."""
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp
        from app.models.otp_verification import OTPVerification

        # Trigger OTP
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            await trigger_otp(seeded["db"], seeded["sid"])

        # 3 wrong attempts
        for attempt in range(3):
            with patch(
                "app.mcp_tools.otp_tools.hmac.compare_digest",
                return_value=False,
            ) as mock_cmp:
                r = await verify_otp(seeded["db"], seeded["sid"], "000000")
                assert mock_cmp.called, (
                    f"hmac.compare_digest not called on attempt {attempt + 1}"
                )

        # Should be max attempts
        assert r["verified"] is False
        assert "Maximum attempts" in r.get("error", "")
        assert r["attempts_remaining"] == 0

        # Trigger new OTP and verify it works
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            trigger_result = await trigger_otp(seeded["db"], seeded["sid"])

        assert trigger_result["otp_sent"] is True

        # Get the new code
        stmt = select(OTPVerification).where(
            OTPVerification.session_id == seeded["sid"],
            OTPVerification.verified == False,  # noqa: E712
        ).order_by(OTPVerification.created_at.desc())
        res = await seeded["db"].execute(stmt)
        new_otp = res.scalars().first()

        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            return_value=True,
        ) as mock_cmp:
            r = await verify_otp(seeded["db"], seeded["sid"], new_otp.otp_code)
            assert mock_cmp.called
        assert r["verified"] is True
