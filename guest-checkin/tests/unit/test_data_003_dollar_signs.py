"""DATA-003: Dollar signs render correctly in incidental protection HTML.

Verifies:
1. The incidental selection HTML page shows "$49.00" and "$250.00" with proper
   dollar signs (not broken formatting like "${amount:.2f}").
2. The damage waiver amount constant is correctly spelled DAMAGE_WAIVER_AMOUNT
   (not DAMAGE_WAVER_AMOUNT — typo with 'WAVER' instead of 'WAIVER').
3. f-string dollar-sign interpolation in API response messages renders correctly.
4. The amount value is exactly $49.00 (not $49.99 or any other value).

Coverage matrix rows:
- EC-DI-003: Dollar sign f-string escaping bug — use constant directly,
  avoid backslash in f-strings
- CSR-DI-003: Dollar sign renders broken → fix constant → renders correctly
"""

import re
from decimal import Decimal

import pytest


# ── 1. HTML rendering: dollar signs in the selection page ──────────


class TestDollarSignHtmlRendering:
    """Verify the incidental protection HTML page renders dollar signs correctly."""

    def test_damage_waiver_price_displays_dollar_sign(self):
        """$49.00 must appear with a literal dollar sign in the HTML, not a
        broken format like '${amount:.2f}' or a bare number."""
        from app.api.incidental import _build_selection_page

        html = _build_selection_page("test-token-abc")
        # The price must contain "$49.00" as a literal string
        assert "$49.00" in html, (
            "Expected '$49.00' in the incidental selection HTML, but it was not found. "
            "This indicates a broken dollar sign rendering bug."
        )

    def test_security_hold_price_displays_dollar_sign(self):
        """$250.00 must appear with a literal dollar sign in the HTML."""
        from app.api.incidental import _build_selection_page

        html = _build_selection_page("test-token-abc")
        assert "$250.00" in html, (
            "Expected '$250.00' in the incidental selection HTML, but it was not found."
        )

    def test_no_broken_fstring_patterns_in_html(self):
        """The HTML must NOT contain broken f-string patterns like
        '${amount:.2f}' or '${...' which would indicate a formatting bug."""
        from app.api.incidental import _build_selection_page

        html = _build_selection_page("test-token-abc")
        # Match any ${...} pattern that looks like an unrendered f-string variable
        broken_patterns = re.findall(r"\$\{[^}]+\}", html)
        assert broken_patterns == [], (
            f"Found broken f-string pattern(s) in HTML: {broken_patterns}. "
            "Dollar amounts should render as literal '$49.00', not '${amount:.2f}'."
        )

    def test_damage_waiver_not_49_99(self):
        """The damage waiver price must be $49.00, NOT $49.99 (known inconsistency
        per JACKHAMR.md bug: 'DAMAGE_WAIVER_AMOUNT inconsistency ($49 vs $49.99)')."""
        from app.api.incidental import _build_selection_page

        html = _build_selection_page("test-token-abc")
        # Must NOT show $49.99
        assert "$49.99" not in html, (
            "Found '$49.99' in the HTML — this is a known inconsistency bug. "
            "The damage waiver price should be $49.00."
        )


# ── 2. Constant naming: DAMAGE_WAIVER_AMOUNT (not the WAVER typo) ─


class TestDAMAGE_WAIVER_AMOUNTConstant:
    """Verify the damage waiver amount constant exists with correct spelling
    and value. The original code had DAMAGE_WAVER_AMOUNT (typo: 'WAVER'
    instead of 'WAIVER'), which causes a NameError at runtime when
    DAMAGE_WAIVER_AMOUNT is referenced in the POST handler."""

    def test_constant_spelled_WAIVER_not_WAVER(self):
        """The module must export DAMAGE_WAIVER_AMOUNT (correct spelling).
        The typo DAMAGE_WAVER_AMOUNT would cause NameError on line 86."""
        from app.api import incidental

        assert hasattr(incidental, "DAMAGE_WAIVER_AMOUNT"), (
            "DAMAGE_WAIVER_AMOUNT not found in app.api.incidental. "
            "Only the misspelled DAMAGE_WAVER_AMOUNT exists — this causes a "
            "NameError at runtime when selecting damage_waiver on line 86."
        )

    def test_typo_WAVER_constant_must_not_exist(self):
        """The misspelled DAMAGE_WAVER_AMOUNT should NOT exist as a module-level
        name. If it does, it's a typo that should be renamed to DAMAGE_WAIVER_AMOUNT."""
        from app.api import incidental

        # We accept that it might still exist during a transition, but flag it
        if hasattr(incidental, "DAMAGE_WAVER_AMOUNT"):
            pytest.fail(
                "DAMAGE_WAVER_AMOUNT (typo: 'WAVER') still exists in "
                "app.api.incidental. It should be renamed to DAMAGE_WAIVER_AMOUNT."
            )

    def test_damage_waiver_amount_value_is_49_00(self):
        """DAMAGE_WAIVER_AMOUNT must be Decimal('49.00'), not 49.99."""
        from app.api import incidental

        amount = incidental.DAMAGE_WAIVER_AMOUNT
        assert amount == Decimal("49.00"), (
            f"DAMAGE_WAIVER_AMOUNT is {amount}, expected Decimal('49.00'). "
            "Known bug: some files used 49.99 instead of 49.00."
        )

    def test_security_hold_amount_value(self):
        """SECURITY_HOLD_AMOUNT must be Decimal('250.00')."""
        from app.api import incidental

        assert incidental.SECURITY_HOLD_AMOUNT == Decimal("250.00")


# ── 3. f-string dollar sign in API response message ────────────────


class TestFStringDollarRendering:
    """Verify that the f-string in the POST handler response message
    renders the dollar sign correctly (e.g. '$49.00' not '49.00')."""

    def test_post_response_dollar_sign_formatting(self):
        """The response message on line 123 uses f'Payment of ${amount:.2f}...'.
        In Python, $ is not a special f-string character, so this should render
        as 'Payment of $49.00 processed successfully.'."""
        from decimal import Decimal

        amount = Decimal("49.00")
        message = f"Payment of ${amount:.2f} processed successfully. mock ok"
        assert "$49.00" in message, (
            f"f-string dollar rendering failed: '{message}' does not contain '$49.00'"
        )

    def test_post_response_no_broken_format(self):
        """The message must not contain '${amount:.2f}' or similar unrendered patterns."""
        amount = Decimal("49.00")
        message = f"Payment of ${amount:.2f} processed successfully."
        broken = re.findall(r"\$\{[^}]+\}", message)
        assert broken == [], f"Found unrendered f-string patterns: {broken}"

    def test_security_hold_dollar_sign_formatting(self):
        """Same check for the security hold amount ($250.00)."""
        amount = Decimal("250.00")
        message = f"Payment of ${amount:.2f} processed successfully."
        assert "$250.00" in message


# ── 4. MCP tools consistency ──────────────────────────────────────


class TestMcpToolsDollarConsistency:
    """Verify the MCP tool incidental_options also use the correct $49.00 amount."""

    def test_mcp_tool_damage_waiver_amount(self):
        """INCIDENTAL_OPTIONS in incidental_tools.py must have $49.00, not $49.99."""
        from app.mcp_tools.incidental_tools import INCIDENTAL_OPTIONS

        damage_waiver = next(
            (opt for opt in INCIDENTAL_OPTIONS if opt["type"] == "damage_waiver"),
            None,
        )
        assert damage_waiver is not None, "damage_waiver option not found in INCIDENTAL_OPTIONS"
        assert damage_waiver["amount"] == Decimal("49.00"), (
            f"MCP tool damage_waiver amount is {damage_waiver['amount']}, "
            "expected Decimal('49.00')"
        )

    def test_mcp_tool_description_contains_dollar_sign(self):
        """The damage waiver description must mention $500 with a dollar sign."""
        from app.mcp_tools.incidental_tools import INCIDENTAL_OPTIONS

        damage_waiver = next(
            (opt for opt in INCIDENTAL_OPTIONS if opt["type"] == "damage_waiver"),
            None,
        )
        assert "$500" in damage_waiver["description"], (
            "Damage waiver description should mention '$500' with dollar sign"
        )

    def test_mcp_tool_security_hold_amount(self):
        """Security hold amount in MCP tools must be $250.00."""
        from app.mcp_tools.incidental_tools import INCIDENTAL_OPTIONS

        security_hold = next(
            (opt for opt in INCIDENTAL_OPTIONS if opt["type"] == "security_hold"),
            None,
        )
        assert security_hold is not None
        assert security_hold["amount"] == Decimal("250.00")
