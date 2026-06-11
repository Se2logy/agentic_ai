"""Shared utility functions extracted from session_manager and fallback.

These are leaf-level helpers with no circular-import risk — they only
import from standard library, models, and schemas.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase
from app.state_machine.states import State


def agreement_type_for_state(state: State) -> str | None:
    """Return the agreement type string for a state that has one."""
    mapping = {
        State.PRIVACY_POLICY_PENDING: "privacy_policy",
        State.HOUSE_RULES_PENDING: "house_rules",
        State.RENTAL_AGREEMENT_PENDING: "rental_agreement",
    }
    return mapping.get(state)


# Stop words for keyword matching
_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all",
    "can", "had", "her", "was", "one", "our", "out", "has",
    "his", "how", "its", "let", "may", "new", "now", "old",
    "see", "way", "who", "did", "get", "has", "him", "how",
    "ive", "thats", "with", "this", "that", "from", "they",
    "been", "have", "will", "what", "when", "where", "does",
    "about", "which", "their", "there", "would", "could",
    "should", "some", "than", "into", "also", "just", "tell",
    "know", "want", "like",
})


async def answer_question(
    session,
    question: str,
    db: AsyncSession,
) -> str | None:
    """Try to answer a guest question from the knowledge base.

    Uses keyword matching with stop-word filtering and scoring.
    Returns the best matching answer or None.
    """
    result = await db.execute(select(KnowledgeBase).limit(50))
    entries = result.scalars().all()
    if not entries:
        return None

    q_lower = question.lower().rstrip("?!.,")

    # Tokenise, filter stop words and short tokens
    keywords = [
        w for w in q_lower.split()
        if len(w) >= 3 and w not in _STOP_WORDS
    ]

    best_match = None
    best_score = 0

    for entry in entries:
        entry_q = entry.question.lower()
        entry_a = entry.answer.lower()
        score = 0

        # Exact substring match of the whole question
        if q_lower in entry_q or entry_q in q_lower:
            score += 10

        # Keyword overlap
        combined = entry_q + " " + entry_a
        for kw in keywords:
            if kw in combined:
                score += 1
            if kw in entry_q:
                score += 2  # bonus for appearing in the question field

        if score > best_score:
            best_score = score
            best_match = entry

    # Require minimum score
    if best_match is None or best_score < 2:
        return None

    return best_match.answer
