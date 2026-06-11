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


async def answer_question(
    session,
    question: str,
    db: AsyncSession,
) -> str | None:
    """Try to answer a guest question from the knowledge base."""
    result = await db.execute(select(KnowledgeBase).limit(10))
    entries = result.scalars().all()
    if not entries:
        return None

    q_lower = question.lower()
    for entry in entries:
        if any(word in q_lower for word in entry.question.lower().split()):
            return entry.answer

    return None
