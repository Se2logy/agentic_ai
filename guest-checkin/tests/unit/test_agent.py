"""Unit tests for the LLM agent module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.entity_extractor import EntityExtractor
from app.agent.exceptions import (
    EntityExtractionError,
    IntentDetectionError,
    OllamaUnavailableError,
)
from app.agent.fallback import FallbackAgent
from app.agent.intent import IntentDetector
from app.agent.llm_client import OllamaClient
from app.agent.prompt_builder import PromptBuilder
from app.agent.tool_router import ToolRouter
from app.state_machine.states import STATE_INFO, State


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def fallback_agent() -> FallbackAgent:
    return FallbackAgent()


@pytest.fixture
def prompt_builder() -> PromptBuilder:
    return PromptBuilder()


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    client = AsyncMock(spec=OllamaClient)
    return client


@pytest.fixture
def intent_detector(mock_llm_client: AsyncMock) -> IntentDetector:
    return IntentDetector(llm_client=mock_llm_client)


@pytest.fixture
def entity_extractor(mock_llm_client: AsyncMock) -> EntityExtractor:
    return EntityExtractor(llm_client=mock_llm_client)


@pytest.fixture
def mock_tool_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_tool_descriptions.return_value = [
        {
            "name": "record_agreement",
            "description": "Record guest acceptance or refusal.",
            "parameters": {
                "properties": {
                    "session_id": {"type": "string"},
                    "agreement_type": {"type": "string"},
                    "accepted": {"type": "boolean"},
                }
            },
        },
        {
            "name": "trigger_otp",
            "description": "Trigger OTP.",
            "parameters": {"properties": {"session_id": {"type": "string"}}},
        },
    ]
    return registry


@pytest.fixture
def tool_router(mock_tool_registry: MagicMock) -> ToolRouter:
    return ToolRouter(tool_registry=mock_tool_registry)


# ═══════════════════════════════════════════════════════════════════
# Test: Exceptions
# ═══════════════════════════════════════════════════════════════════


class TestExceptions:
    def test_ollama_unavailable_error(self):
        err = OllamaUnavailableError("http://localhost:11434", 2)
        assert err.base_url == "http://localhost:11434"
        assert err.retries == 2
        assert "http://localhost:11434" in str(err)
        assert "2" in str(err)

    def test_intent_detection_error(self):
        err = IntentDetectionError("detection failed")
        assert "detection failed" in str(err)

    def test_entity_extraction_error(self):
        err = EntityExtractionError("extraction failed")
        assert "extraction failed" in str(err)


# ═══════════════════════════════════════════════════════════════════
# Test: OllamaClient
# ═══════════════════════════════════════════════════════════════════


class TestOllamaClient:
    def test_init_defaults(self):
        client = OllamaClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3.1:8b"
        assert client.timeout == 30
        assert client.max_retries == 2

    def test_init_custom(self):
        client = OllamaClient(
            base_url="http://ollama:11434",
            model="mistral",
            timeout=60,
            max_retries=3,
        )
        assert client.base_url == "http://ollama:11434"
        assert client.model == "mistral"
        assert client.timeout == 60
        assert client.max_retries == 3

    def test_base_url_trailing_slash_stripped(self):
        client = OllamaClient(base_url="http://localhost:11434/")
        assert client.base_url == "http://localhost:11434"

    @pytest.mark.asyncio
    async def test_chat_success(self):
        client = OllamaClient(max_retries=0)
        mock_response = {
            "message": {"role": "assistant", "content": "Hello!"},
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post.return_value = MagicMock(
                status_code=200,
                raise_for_status=MagicMock(),
                json=lambda: mock_response,
            )
            mock_http.post.return_value.raise_for_status = MagicMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            result = await client.chat(
                messages=[{"role": "user", "content": "Hi"}]
            )
            assert result["message"]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_unavailable_raises(self):
        import httpx

        client = OllamaClient(max_retries=1)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.post.side_effect = httpx.ConnectError("Connection refused")
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            with pytest.raises(OllamaUnavailableError):
                await client.chat(
                    messages=[{"role": "user", "content": "Hi"}]
                )

    @pytest.mark.asyncio
    async def test_chat_with_tools(self):
        client = OllamaClient(max_retries=0)
        mock_response = {
            "message": {"role": "assistant", "content": ""},
            "tool_calls": [],
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_http.post.return_value = mock_resp
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_http

            tools = [{"name": "test_tool", "description": "A test"}]
            result = await client.chat(
                messages=[{"role": "user", "content": "Use tool"}],
                tools=tools,
            )
            # Verify tools were included in the request payload
            call_kwargs = mock_http.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert "tools" in payload


# ═══════════════════════════════════════════════════════════════════
# Test: FallbackAgent — Intent Detection (regex)
# ═══════════════════════════════════════════════════════════════════


class TestFallbackAgentIntentDetection:
    """Test FallbackAgent.detect_intent_regex for various inputs."""

    @pytest.fixture
    def agent(self):
        return FallbackAgent()

    def test_agree_yes(self, agent):
        assert agent.detect_intent_regex("Yes, I agree", State.PRIVACY_POLICY_PENDING) == "agree"

    def test_agree_accept(self, agent):
        assert agent.detect_intent_regex("I accept the terms", State.HOUSE_RULES_PENDING) == "agree"

    def test_agree_okay(self, agent):
        assert agent.detect_intent_regex("Okay, sounds good", State.RENTAL_AGREEMENT_PENDING) == "agree"

    def test_agree_sure(self, agent):
        assert agent.detect_intent_regex("Sure!", State.PRIVACY_POLICY_PENDING) == "agree"

    def test_decline_no(self, agent):
        assert agent.detect_intent_regex("No, I don't agree", State.PRIVACY_POLICY_PENDING) == "decline"

    def test_decline_disagree(self, agent):
        assert agent.detect_intent_regex("I disagree with this", State.HOUSE_RULES_PENDING) == "decline"

    def test_decline_refuse(self, agent):
        assert agent.detect_intent_regex("I refuse to accept", State.RENTAL_AGREEMENT_PENDING) == "decline"

    def test_question_what(self, agent):
        assert agent.detect_intent_regex("What does this mean?", State.PRIVACY_POLICY_PENDING) == "question"

    def test_question_how(self, agent):
        assert agent.detect_intent_regex("How does the waiver work?", State.INCIDENTAL_PROTECTION_PENDING) == "question"

    def test_provide_info_name(self, agent):
        assert agent.detect_intent_regex("My name is John Smith", State.INFO_VERIFY_PENDING) == "provide_info"

    def test_select_option_damage_waiver(self, agent):
        assert agent.detect_intent_regex("I'll take the damage waiver", State.INCIDENTAL_PROTECTION_PENDING) == "select_option"

    def test_select_option_security_hold(self, agent):
        assert agent.detect_intent_regex("I prefer the security hold", State.INCIDENTAL_PROTECTION_PENDING) == "select_option"

    def test_request_help(self, agent):
        assert agent.detect_intent_regex("I need help, can I speak to someone?", State.PRIVACY_POLICY_PENDING) == "request_help"

    def test_greeting(self, agent):
        assert agent.detect_intent_regex("Hello there!", State.INIT) == "greeting"

    def test_other_unrecognized(self, agent):
        assert agent.detect_intent_regex("blah blah random", State.INIT) == "other"

    # State-aware overrides
    def test_info_verify_correct_means_confirm(self, agent):
        """In INFO_VERIFY_PENDING, 'correct' should map to confirm."""
        assert agent.detect_intent_regex("That's correct", State.INFO_VERIFY_PENDING) == "confirm"

    def test_info_verify_looks_good_means_confirm(self, agent):
        assert agent.detect_intent_regex("Looks good to me", State.INFO_VERIFY_PENDING) == "confirm"

    def test_info_verify_otp_code_detected(self, agent):
        """6-digit numbers in INFO_VERIFY_PENDING should be detected as verify_otp."""
        assert agent.detect_intent_regex("123456", State.INFO_VERIFY_PENDING) == "verify_otp"
        assert agent.detect_intent_regex("My code is 789012", State.INFO_VERIFY_PENDING) == "verify_otp"

    def test_info_verify_non_otp_number_not_verify_otp(self, agent):
        """Numbers that aren't 6 digits should not be detected as verify_otp."""
        result = agent.detect_intent_regex("I have 3 guests", State.INFO_VERIFY_PENDING)
        assert result != "verify_otp"

    def test_incidental_damage_waiver_is_select_option(self, agent):
        assert agent.detect_intent_regex("damage waiver", State.INCIDENTAL_PROTECTION_PENDING) == "select_option"

    def test_incidental_security_hold_is_select_option(self, agent):
        assert agent.detect_intent_regex("security hold", State.INCIDENTAL_PROTECTION_PENDING) == "select_option"

    # ── Inflected agreement / decline forms (Bug 2) ──────────────

    @pytest.mark.parametrize("state", [
        State.PRIVACY_POLICY_PENDING,
        State.HOUSE_RULES_PENDING,
        State.RENTAL_AGREEMENT_PENDING,
    ])
    @pytest.mark.parametrize("message", [
        "accepted",
        "agreed",
        "acknowledged",
        "I accepted",
        "I agreed",
        "acknowledge",
    ])
    def test_fallback_agree_accepts_inflected_forms(self, agent, state, message):
        """Inflected agree inputs (accepted, agreed, acknowledged, …)
        must resolve to 'agree' in every agreement state."""
        assert agent.detect_intent_regex(message, state) == "agree"

    @pytest.mark.parametrize("state", [
        State.PRIVACY_POLICY_PENDING,
        State.HOUSE_RULES_PENDING,
        State.RENTAL_AGREEMENT_PENDING,
    ])
    @pytest.mark.parametrize("message", [
        "declined",
        "refused",
        "rejected",
        "disagreed",
        "I refuse",
        "I decline",
        "no thanks",
        "nah",
    ])
    def test_fallback_decline_accepts_inflected_forms(self, agent, state, message):
        """Inflected decline inputs (declined, refused, rejected, …)
        must resolve to 'decline' in every agreement state."""
        assert agent.detect_intent_regex(message, state) == "decline"

    @pytest.mark.parametrize("message", [
        "agree",
        "accept",
        "yes",
        "ok",
        "sure",
        "confirmed",
    ])
    def test_fallback_still_recognizes_original_forms(self, agent, message):
        """Original base forms (agree, accept, yes, ok, sure, confirmed)
        must still resolve to 'agree'."""
        assert agent.detect_intent_regex(message, State.PRIVACY_POLICY_PENDING) == "agree"

    @pytest.mark.parametrize("message", [
        "acceptable",
        "exception",
        "agreeable",
    ])
    def test_fallback_no_false_positives_on_partial_words(self, agent, message):
        """Words that merely contain agree/accept as a substring
        must NOT be detected as 'agree'."""
        result = agent.detect_intent_regex(message, State.PRIVACY_POLICY_PENDING)
        assert result != "agree"


# ═══════════════════════════════════════════════════════════════════
# Test: FallbackAgent — Response Generation
# ═══════════════════════════════════════════════════════════════════


class TestFallbackAgentResponseGeneration:
    @pytest.fixture
    def agent(self):
        return FallbackAgent()

    def test_privacy_policy_agree_response(self, agent):
        response = agent.generate_response("agree", State.PRIVACY_POLICY_PENDING)
        assert "Privacy Policy" in response
        assert "House Rules" in response

    def test_privacy_policy_decline_response(self, agent):
        response = agent.generate_response("decline", State.PRIVACY_POLICY_PENDING)
        assert "declined" in response.lower()

    def test_house_rules_agree_response(self, agent):
        response = agent.generate_response("agree", State.HOUSE_RULES_PENDING)
        assert "House Rules" in response
        assert "Rental Agreement" in response

    def test_rental_agreement_agree_response(self, agent):
        response = agent.generate_response("agree", State.RENTAL_AGREEMENT_PENDING)
        assert "Rental Agreement" in response

    def test_info_verify_agree_response(self, agent):
        response = agent.generate_response("agree", State.INFO_VERIFY_PENDING)
        assert "confirmed" in response.lower() or "ID" in response

    def test_info_verify_provide_info_response(self, agent):
        response = agent.generate_response("provide_info", State.INFO_VERIFY_PENDING)
        assert "updated" in response.lower() or "information" in response.lower()

    def test_incidental_select_option_response(self, agent):
        response = agent.generate_response("select_option", State.INCIDENTAL_PROTECTION_PENDING)
        assert "selection" in response.lower() or "recorded" in response.lower()

    def test_completed_response(self, agent):
        response = agent.generate_response("other", State.COMPLETED)
        assert "complete" in response.lower() or "check-in" in response.lower()

    def test_refused_response(self, agent):
        response = agent.generate_response("other", State.REFUSED)
        assert "paused" in response.lower() or "declined" in response.lower()

    def test_init_greeting_response(self, agent):
        response = agent.generate_response("greeting", State.INIT)
        assert "Welcome" in response or "check-in" in response.lower()

    def test_response_with_tool_error(self, agent):
        tool_result = {"error": "Session not found"}
        response = agent.generate_response("agree", State.PRIVACY_POLICY_PENDING, tool_result)
        assert "Session not found" in response

    def test_unknown_state_intent_falls_back(self, agent):
        response = agent.generate_response("other", State.ID_VERIFY_PENDING)
        assert len(response) > 0  # Should not crash, returns something


# ═══════════════════════════════════════════════════════════════════
# Test: IntentDetector (with mocked LLM)
# ═══════════════════════════════════════════════════════════════════


class TestIntentDetector:
    """Test IntentDetector with mocked OllamaClient."""

    @pytest.fixture
    def detector(self, mock_llm_client):
        return IntentDetector(llm_client=mock_llm_client)

    @pytest.mark.asyncio
    async def test_llm_intent_agree(self, detector, mock_llm_client):
        mock_llm_client.chat.return_value = {
            "message": {"content": "agree"}
        }
        result = await detector.detect_intent("I accept", State.PRIVACY_POLICY_PENDING)
        assert result == "agree"

    @pytest.mark.asyncio
    async def test_llm_intent_decline(self, detector, mock_llm_client):
        mock_llm_client.chat.return_value = {
            "message": {"content": "decline"}
        }
        result = await detector.detect_intent("No thanks", State.HOUSE_RULES_PENDING)
        assert result == "decline"

    @pytest.mark.asyncio
    async def test_llm_intent_question(self, detector, mock_llm_client):
        mock_llm_client.chat.return_value = {
            "message": {"content": "question"}
        }
        result = await detector.detect_intent("What is this?", State.PRIVACY_POLICY_PENDING)
        assert result == "question"

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_falls_back_to_regex(self, detector, mock_llm_client):
        """When LLM returns an invalid intent, fall back to regex."""
        mock_llm_client.chat.return_value = {
            "message": {"content": "something_invalid"}
        }
        result = await detector.detect_intent("Yes, I agree", State.PRIVACY_POLICY_PENDING)
        assert result == "agree"  # regex fallback

    @pytest.mark.asyncio
    async def test_llm_unavailable_falls_back_to_regex(self, detector, mock_llm_client):
        """When Ollama is unavailable, fall back to regex."""
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await detector.detect_intent("I accept", State.PRIVACY_POLICY_PENDING)
        assert result == "agree"  # regex fallback

    @pytest.mark.asyncio
    async def test_llm_generic_error_falls_back_to_regex(self, detector, mock_llm_client):
        mock_llm_client.chat.side_effect = RuntimeError("Unexpected error")
        result = await detector.detect_intent("No way", State.HOUSE_RULES_PENDING)
        assert result == "decline"  # regex fallback

    @pytest.mark.asyncio
    async def test_state_aware_info_verify_correct(self, detector, mock_llm_client):
        """In INFO_VERIFY_PENDING, 'correct' should resolve to 'agree' via regex fallback."""
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await detector.detect_intent("That's correct", State.INFO_VERIFY_PENDING)
        assert result == "confirm"


# ═══════════════════════════════════════════════════════════════════
# Test: EntityExtractor
# ═══════════════════════════════════════════════════════════════════


class TestEntityExtractor:
    """Test EntityExtractor with mocked LLM and regex fallback."""

    @pytest.fixture
    def extractor(self, mock_llm_client):
        return EntityExtractor(llm_client=mock_llm_client)

    @pytest.mark.asyncio
    async def test_llm_extract_info_verify(self, extractor, mock_llm_client):
        mock_llm_client.chat.return_value = {
            "message": {
                "content": json.dumps({
                    "first_name": "John",
                    "last_name": "Doe",
                    "phone": "+1234567890",
                    "otp_code": None,
                })
            }
        }
        result = await extractor.extract_entities(
            "My name is John Doe, phone +1234567890",
            State.INFO_VERIFY_PENDING,
        )
        assert result.get("first_name") == "John"
        assert result.get("last_name") == "Doe"
        assert result.get("phone") == "+1234567890"

    @pytest.mark.asyncio
    async def test_llm_extract_incidental_selection(self, extractor, mock_llm_client):
        mock_llm_client.chat.return_value = {
            "message": {
                "content": json.dumps({"selection_type": "damage_waiver"})
            }
        }
        result = await extractor.extract_entities(
            "I'll take the damage waiver",
            State.INCIDENTAL_PROTECTION_PENDING,
        )
        assert result.get("selection_type") == "damage_waiver"

    @pytest.mark.asyncio
    async def test_llm_unavailable_regex_fallback_phone(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "My phone is 555-123-4567",
            State.INFO_VERIFY_PENDING,
        )
        assert "phone" in result
        assert "555" in result["phone"]

    @pytest.mark.asyncio
    async def test_llm_unavailable_regex_fallback_name(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "My name is Jane Smith",
            State.INFO_VERIFY_PENDING,
        )
        assert result.get("first_name") == "Jane"
        assert result.get("last_name") == "Smith"

    @pytest.mark.asyncio
    async def test_regex_fallback_otp_code(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "My code is 123456",
            State.INFO_VERIFY_PENDING,
        )
        assert result.get("otp_code") == "123456"

    @pytest.mark.asyncio
    async def test_regex_fallback_damage_waiver(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "I want the damage waiver",
            State.INCIDENTAL_PROTECTION_PENDING,
        )
        assert result.get("selection_type") == "damage_waiver"

    @pytest.mark.asyncio
    async def test_regex_fallback_security_hold(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "I prefer the security hold option",
            State.INCIDENTAL_PROTECTION_PENDING,
        )
        assert result.get("selection_type") == "security_hold"

    @pytest.mark.asyncio
    async def test_no_extraction_for_unrelated_state(self, extractor, mock_llm_client):
        result = await extractor.extract_entities(
            "Hello there",
            State.PRIVACY_POLICY_PENDING,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_regex_fallback_option_one(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "I'll go with option 1",
            State.INCIDENTAL_PROTECTION_PENDING,
        )
        assert result.get("selection_type") == "damage_waiver"

    @pytest.mark.asyncio
    async def test_regex_fallback_option_two(self, extractor, mock_llm_client):
        mock_llm_client.chat.side_effect = OllamaUnavailableError(
            "http://localhost:11434", 2
        )
        result = await extractor.extract_entities(
            "I'll choose the second option",
            State.INCIDENTAL_PROTECTION_PENDING,
        )
        assert result.get("selection_type") == "security_hold"


# ═══════════════════════════════════════════════════════════════════
# Test: PromptBuilder
# ═══════════════════════════════════════════════════════════════════


class TestPromptBuilder:
    """Test PromptBuilder produces state-specific prompts."""

    @pytest.fixture
    def builder(self):
        return PromptBuilder()

    def test_includes_persona(self, builder):
        prompt = builder.build_system_prompt(State.INIT, {})
        assert "check-in assistant" in prompt

    def test_includes_current_state(self, builder):
        prompt = builder.build_system_prompt(State.PRIVACY_POLICY_PENDING, {})
        assert "PRIVACY_POLICY_PENDING" in prompt

    def test_privacy_policy_instructions(self, builder):
        prompt = builder.build_system_prompt(State.PRIVACY_POLICY_PENDING, {})
        assert "Privacy Policy" in prompt
        assert "accept" in prompt.lower()

    def test_house_rules_instructions(self, builder):
        prompt = builder.build_system_prompt(State.HOUSE_RULES_PENDING, {})
        assert "House Rules" in prompt

    def test_rental_agreement_instructions(self, builder):
        prompt = builder.build_system_prompt(State.RENTAL_AGREEMENT_PENDING, {})
        assert "Rental Agreement" in prompt

    def test_info_verify_instructions(self, builder):
        prompt = builder.build_system_prompt(State.INFO_VERIFY_PENDING, {})
        assert "verify" in prompt.lower() or "personal information" in prompt.lower()

    def test_id_verify_instructions(self, builder):
        prompt = builder.build_system_prompt(State.ID_VERIFY_PENDING, {})
        assert "ID" in prompt or "upload" in prompt.lower()

    def test_incidental_instructions(self, builder):
        prompt = builder.build_system_prompt(State.INCIDENTAL_PROTECTION_PENDING, {})
        assert "Damage Waiver" in prompt
        assert "Security Hold" in prompt

    def test_completed_instructions(self, builder):
        prompt = builder.build_system_prompt(State.COMPLETED, {})
        assert "completed" in prompt.lower() or "arrival" in prompt.lower()

    def test_refused_instructions(self, builder):
        prompt = builder.build_system_prompt(State.REFUSED, {})
        assert "declined" in prompt.lower() or "halted" in prompt.lower()

    def test_includes_session_context(self, builder):
        prompt = builder.build_system_prompt(
            State.PRIVACY_POLICY_PENDING,
            {"guest_name": "John Doe", "booking_reference": "BK-001"},
        )
        assert "John Doe" in prompt
        assert "BK-001" in prompt

    def test_includes_property_name(self, builder):
        prompt = builder.build_system_prompt(
            State.INIT,
            {"property_name": "Seaside Cottage"},
        )
        assert "Seaside Cottage" in prompt

    def test_includes_faq_section(self, builder):
        prompt = builder.build_system_prompt(State.INIT, {})
        assert "damage waiver" in prompt.lower()

    def test_includes_conversation_guidelines(self, builder):
        prompt = builder.build_system_prompt(State.INIT, {})
        assert "warm" in prompt.lower() or "professional" in prompt.lower()

    def test_different_states_produce_different_prompts(self, builder):
        prompt_pp = builder.build_system_prompt(State.PRIVACY_POLICY_PENDING, {})
        prompt_hr = builder.build_system_prompt(State.HOUSE_RULES_PENDING, {})
        # They should differ in the state-specific instructions
        assert prompt_pp != prompt_hr

    def test_build_tool_descriptions_section(self, builder):
        tool_descs = [
            {"name": "record_agreement", "description": "Record agreement", "parameters": {"properties": {"session_id": {"type": "string"}}}},
            {"name": "trigger_otp", "description": "Trigger OTP", "parameters": {"properties": {"session_id": {"type": "string"}}}},
        ]
        section = builder.build_tool_descriptions_section(tool_descs)
        assert "record_agreement" in section
        assert "trigger_otp" in section

    def test_build_tool_descriptions_empty(self, builder):
        section = builder.build_tool_descriptions_section([])
        assert "none" in section.lower()


# ═══════════════════════════════════════════════════════════════════
# Test: ToolRouter
# ═══════════════════════════════════════════════════════════════════


class TestToolRouter:
    """Test ToolRouter maps intent+state to correct tool calls."""

    @pytest.fixture
    def router_with_tools(self):
        """Router with mock tool handlers."""
        registry = MagicMock()

        record_agreement = AsyncMock(return_value={"recorded": True})
        trigger_otp = AsyncMock(return_value={"otp_sent": True, "email": "t***@test.com"})
        verify_otp = AsyncMock(return_value={"verified": True})
        update_guest_info = AsyncMock(return_value={"updated": True})
        generate_id_upload_link = AsyncMock(return_value={"upload_url": "/upload?token=abc"})
        record_incidental = AsyncMock(return_value={"selected": True, "selection_type": "damage_waiver"})
        get_faq = AsyncMock(return_value={"answer": "WiFi password is guest123"})

        registry.get_tool = lambda name: {
            "record_agreement": record_agreement,
            "trigger_otp": trigger_otp,
            "verify_otp": verify_otp,
            "update_guest_info": update_guest_info,
            "generate_id_upload_link": generate_id_upload_link,
            "record_incidental_selection": record_incidental,
            "get_faq_answer": get_faq,
        }.get(name)

        return ToolRouter(tool_registry=registry), {
            "record_agreement": record_agreement,
            "trigger_otp": trigger_otp,
            "verify_otp": verify_otp,
            "update_guest_info": update_guest_info,
            "generate_id_upload_link": generate_id_upload_link,
            "record_incidental_selection": record_incidental,
            "get_faq_answer": get_faq,
        }

    @pytest.mark.asyncio
    async def test_agree_privacy_policy_calls_record_agreement(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-1",
            db_session=db,
        )
        tools["record_agreement"].assert_called_once()
        call_kwargs = tools["record_agreement"].call_args
        assert call_kwargs.kwargs["agreement_type"] == "privacy_policy"
        assert call_kwargs.kwargs["accepted"] is True
        assert call_kwargs.kwargs["session_id"] == "s-1"

    @pytest.mark.asyncio
    async def test_agree_house_rules_calls_record_agreement(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.HOUSE_RULES_PENDING,
            session_id="s-2",
            db_session=db,
        )
        tools["record_agreement"].assert_called_once()
        call_kwargs = tools["record_agreement"].call_args
        assert call_kwargs.kwargs["agreement_type"] == "house_rules"
        assert call_kwargs.kwargs["accepted"] is True

    @pytest.mark.asyncio
    async def test_agree_rental_agreement_calls_record_agreement(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.RENTAL_AGREEMENT_PENDING,
            session_id="s-3",
            db_session=db,
        )
        tools["record_agreement"].assert_called_once()
        call_kwargs = tools["record_agreement"].call_args
        assert call_kwargs.kwargs["agreement_type"] == "rental_agreement"

    @pytest.mark.asyncio
    async def test_decline_privacy_policy_calls_record_agreement_false(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="decline",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-4",
            db_session=db,
        )
        tools["record_agreement"].assert_called_once()
        call_kwargs = tools["record_agreement"].call_args
        assert call_kwargs.kwargs["accepted"] is False

    @pytest.mark.asyncio
    async def test_confirm_info_verify_calls_trigger_otp(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="confirm",
            entities={},
            state=State.INFO_VERIFY_PENDING,
            session_id="s-5",
            db_session=db,
        )
        tools["trigger_otp"].assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_otp_intent_calls_verify_otp(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="verify_otp",
            entities={"otp_code": "123456"},
            state=State.INFO_VERIFY_PENDING,
            session_id="s-5",
            db_session=db,
        )
        tools["verify_otp"].assert_called_once()
        call_kwargs = tools["verify_otp"].call_args
        assert call_kwargs.kwargs["otp_code"] == "123456"

    @pytest.mark.asyncio
    async def test_provide_info_calls_update_guest_info(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="provide_info",
            entities={"first_name": "Jane", "last_name": "Doe", "phone": "555-1234"},
            state=State.INFO_VERIFY_PENDING,
            session_id="s-6",
            db_session=db,
        )
        tools["update_guest_info"].assert_called_once()
        call_kwargs = tools["update_guest_info"].call_args
        assert call_kwargs.kwargs["first_name"] == "Jane"
        assert call_kwargs.kwargs["last_name"] == "Doe"
        assert call_kwargs.kwargs["phone"] == "555-1234"

    @pytest.mark.asyncio
    async def test_agree_id_verify_calls_generate_upload_link(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.ID_VERIFY_PENDING,
            session_id="s-7",
            db_session=db,
        )
        tools["generate_id_upload_link"].assert_called_once()

    @pytest.mark.asyncio
    async def test_select_option_incidental_calls_record_incidental(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="select_option",
            entities={"selection_type": "damage_waiver"},
            state=State.INCIDENTAL_PROTECTION_PENDING,
            session_id="s-8",
            db_session=db,
        )
        tools["record_incidental_selection"].assert_called_once()
        call_kwargs = tools["record_incidental_selection"].call_args
        assert call_kwargs.kwargs["selection_type"] == "damage_waiver"

    @pytest.mark.asyncio
    async def test_question_calls_get_faq(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="question",
            entities={"question": "What is the WiFi password?"},
            state=State.INCIDENTAL_PROTECTION_PENDING,
            session_id="s-9",
            db_session=db,
        )
        tools["get_faq_answer"].assert_called_once()

    @pytest.mark.asyncio
    async def test_request_help_no_tool(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="request_help",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-10",
            db_session=db,
        )
        assert result.get("no_tool") is True
        assert "human" in result.get("message", "").lower() or "agent" in result.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_greeting_init_no_tool(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="greeting",
            entities={},
            state=State.INIT,
            session_id="s-11",
            db_session=db,
        )
        assert result.get("no_tool") is True

    @pytest.mark.asyncio
    async def test_other_intent_no_tool(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="other",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-12",
            db_session=db,
        )
        assert result.get("no_tool") is True

    @pytest.mark.asyncio
    async def test_unknown_mapping_no_tool(self, router_with_tools):
        router, tools = router_with_tools
        db = AsyncMock()
        result = await router.route(
            intent="unknown_intent",
            entities={},
            state=State.INIT,
            session_id="s-13",
            db_session=db,
        )
        assert result.get("no_tool") is True or "error" in result

    @pytest.mark.asyncio
    async def test_tool_not_found_returns_error(self):
        registry = MagicMock()
        registry.get_tool.return_value = None  # Tool doesn't exist
        router = ToolRouter(tool_registry=registry)
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-14",
            db_session=db,
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_exception_returns_error(self):
        registry = MagicMock()
        failing_handler = AsyncMock(side_effect=RuntimeError("DB error"))
        registry.get_tool.return_value = failing_handler
        router = ToolRouter(tool_registry=registry)
        db = AsyncMock()
        result = await router.route(
            intent="agree",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="s-15",
            db_session=db,
        )
        assert "error" in result
