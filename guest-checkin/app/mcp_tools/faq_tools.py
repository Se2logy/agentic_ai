"""MCP tools: FAQ answer lookup and current state retrieval."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase
from app.models.session import Session
from app.state_machine.states import STATE_INFO, State

logger = logging.getLogger(__name__)

DEFAULT_ANSWER = "I don't have information about that."

# Common English stop words to exclude from keyword matching
_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all",
    "can", "had", "her", "was", "one", "our", "out", "has",
    "his", "how", "its", "let", "may", "new", "now", "old",
    "see", "way", "who", "did", "get", "has", "him", "how",
    "ive", "thats", "with", "this", "that", "from", "they",
    "been", "have", "will", "what", "when", "where", "does",
    "about", "which", "their", "there", "would", "could",
    "should", "some", "than", "into", "also", "just",
})

# ── get_faq_answer ──────────────────────────────────────────────

FAQ_TOOL_NAME = "get_faq_answer"
FAQ_TOOL_DESCRIPTION = (
    "Search the property knowledge base for an answer to the "
    "guest's question. Uses keyword matching against stored "
    "FAQ entries. Returns the best matching answer and its "
    "category, or a default message if no match is found. "
    "Use this when the guest asks a question about the "
    "property, amenities, policies, or local area."
)
FAQ_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID (used to determine property).",
        },
        "question": {
            "type": "string",
            "description": "The guest's question to search for in the knowledge base.",
        },
    },
    "required": ["session_id", "question"],
}


async def get_faq_answer(
    db_session: AsyncSession, session_id: str, question: str
) -> dict[str, Any]:
    """Search the knowledge base for an answer to the guest's question.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        question: The guest's question text.

    Returns:
        Dict with answer and category, or default message.
    """
    if not session_id:
        return {"error": "session_id is required"}
    if not question or not question.strip():
        return {"error": "question is required"}

    # Find session to determine property
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Determine property_id from reservation (explicit query)
    from app.models.reservation import Reservation

    stmt = select(Reservation).where(
        Reservation.id == session.reservation_id
    )
    result = await db_session.execute(stmt)
    reservation = result.scalar_one_or_none()

    # Use property name as property_id fallback, or search all
    property_id = None
    if reservation is not None:
        # Convert property name to property_id format
        # e.g. "Seaside Cottage" -> "seaside-cottage"
        property_id = reservation.property_name.lower().replace(
            " ", "-"
        )

    # Search knowledge base with keyword matching
    keywords = question.strip().lower().split()
    keywords = [kw for kw in keywords if len(kw) >= 3 and kw not in _STOP_WORDS]
    stmt = select(KnowledgeBase)
    if property_id:
        stmt = stmt.where(KnowledgeBase.property_id == property_id)
    result = await db_session.execute(stmt)
    entries = list(result.scalars().all())

    best_match = None
    best_score = 0

    for entry in entries:
        score = _compute_match_score(
            keywords, entry.question.lower(), entry.answer.lower()
        )
        if score > best_score:
            best_score = score
            best_match = entry

    # Require minimum score to return a result
    if best_match is None or best_score < 2:
        logger.info(
            "No FAQ match: session=%s question='%s'", session_id, question
        )
        return {"answer": DEFAULT_ANSWER, "category": None}

    logger.info(
        "FAQ match: session=%s question='%s' category=%s score=%d",
        session_id,
        question,
        best_match.category,
        best_score,
    )

    return {
        "answer": best_match.answer,
        "category": best_match.category,
    }


def _compute_match_score(
    keywords: list[str], question_text: str, answer_text: str
) -> int:
    """Compute a simple keyword match score.

    One point per keyword that appears in either question or answer.
    Bonus point if keyword appears in the question text.
    """
    score = 0
    combined = question_text + " " + answer_text
    for kw in keywords:
        if len(kw) < 3:
            continue  # Skip very short words
        if kw in combined:
            score += 1
            if kw in question_text:
                score += 1  # Bonus for question match
    return score


# ── get_current_state ───────────────────────────────────────────

STATE_TOOL_NAME = "get_current_state"
STATE_TOOL_DESCRIPTION = (
    "Get the guest's current onboarding state and the "
    "required action for that state. Returns the state name "
    "(e.g. PRIVACY_POLICY_PENDING, INFO_VERIFY_PENDING) "
    "and a human-readable description of what the guest "
    "needs to do next. Use this to understand where the "
    "guest is in the check-in flow."
)
STATE_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
    },
    "required": ["session_id"],
}


async def get_current_state(
    db_session: AsyncSession, session_id: str
) -> dict[str, Any]:
    """Get the current onboarding state for a session.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.

    Returns:
        Dict with state and required_action, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    try:
        state = State(session.current_state)
    except ValueError:
        return {
            "state": session.current_state,
            "required_action": "Unknown state",
        }

    info = STATE_INFO.get(state, {})
    required_action = str(info.get("required_action", "Unknown"))
    description = str(info.get("description", ""))

    return {
        "state": state.value,
        "required_action": required_action,
        "description": description,
    }
