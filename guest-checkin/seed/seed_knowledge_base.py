"""Seed knowledge base — 12 FAQ entries across categories."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.knowledge_base import KnowledgeBase

FAQS = [
    {
        "property_id": "seaside-cottage",
        "question": "What time is check-in?",
        "answer": "Check-in is from 3:00 PM onwards. If you need early check-in, "
                  "please contact us at least 24 hours in advance and we will do "
                  "our best to accommodate.",
        "category": "check-in",
    },
    {
        "property_id": "seaside-cottage",
        "question": "What time is check-out?",
        "answer": "Check-out is by 11:00 AM. Late check-out may be available on "
                  "request — please message us before your departure day.",
        "category": "check-in",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Is parking available?",
        "answer": "Yes, free off-street parking is available for one vehicle. A "
                  "second vehicle can park on the street.",
        "category": "amenities",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Are pets allowed?",
        "answer": "Small dogs (under 25 lbs) are welcome with prior arrangement and "
                  "a $50 pet fee per stay. Please let us know at booking.",
        "category": "policies",
    },
    {
        "property_id": "seaside-cottage",
        "question": "How do I get the key?",
        "answer": "The lockbox code will be provided in your arrival instructions "
                  "after you complete check-in. The lockbox is mounted next to the "
                  "front door.",
        "category": "check-in",
    },
    {
        "property_id": "seaside-cottage",
        "question": "What is the Wi-Fi password?",
        "answer": "The Wi-Fi network name and password are included in your arrival "
                  "instructions after you complete check-in.",
        "category": "amenities",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Is there a grocery store nearby?",
        "answer": "Yes, Marina Bay Grocery is a 5-minute walk. It's open daily "
                  "7 AM – 10 PM.",
        "category": "local-area",
    },
    {
        "property_id": "seaside-cottage",
        "question": "What happens if I damage something?",
        "answer": "Please report any damage immediately. Minor damage may be covered "
                  "by the damage waiver option. For significant damage, we will "
                  "assess the cost and charge accordingly.",
        "category": "policies",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Can I have a late check-out?",
        "answer": "Late check-out until 1:00 PM may be available if the next guest "
                  "is not arriving the same day. Please request via message at least "
                  "12 hours before your scheduled check-out.",
        "category": "check-in",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Is there an emergency contact?",
        "answer": "For emergencies, call our 24/7 line at +1-555-0911. For "
                  "non-urgent issues, send a message through the chat.",
        "category": "safety",
    },
    {
        "property_id": "seaside-cottage",
        "question": "What is the cancellation policy?",
        "answer": "Free cancellation up to 7 days before check-in. Cancellations "
                  "within 7 days are charged for the first night.",
        "category": "policies",
    },
    {
        "property_id": "seaside-cottage",
        "question": "Are there quiet hours?",
        "answer": "Yes, quiet hours are from 10:00 PM to 8:00 AM. Please be "
                  "respectful of neighbours during these hours.",
        "category": "policies",
    },
]


async def seed(session: AsyncSession | None = None) -> list[KnowledgeBase]:
    """Insert sample FAQ entries. Uses provided session or creates one."""
    close = False
    if session is None:
        session = async_session_factory()
        close = True

    try:
        for data in FAQS:
            entry = KnowledgeBase(**data)
            session.add(entry)
        await session.commit()
        from sqlalchemy import select
        result = await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.property_id == "seaside-cottage"
            )
        )
        return list(result.scalars().all())
    finally:
        if close:
            await session.close()


if __name__ == "__main__":
    asyncio.run(seed())
