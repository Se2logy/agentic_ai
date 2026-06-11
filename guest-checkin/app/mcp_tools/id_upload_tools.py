"""MCP tools: generate ID upload link and record ID upload."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guest import Guest
from app.models.session import Session
from app.services.link_service import link_service

logger = logging.getLogger(__name__)

# ── generate_id_upload_link ─────────────────────────────────────

GENERATE_TOOL_NAME = "generate_id_upload_link"
GENERATE_TOOL_DESCRIPTION = (
    "Generate a secure, time-limited link for the guest to "
    "upload their government-issued ID document. The link "
    "expires in 1 hour. Use this when the guest reaches the "
    "ID verification step and needs an upload URL."
)
GENERATE_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
    },
    "required": ["session_id"],
}


async def generate_id_upload_link(
    db_session: AsyncSession, session_id: str
) -> dict[str, Any]:
    """Generate a secure upload link for ID document.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.

    Returns:
        Dict with upload_url and expires_in, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    # Verify session exists
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    token = link_service.generate_upload_link(session_id)
    upload_url = f"/api/v1/id-upload/{token}"

    logger.info("ID upload link generated: session=%s", session_id)

    return {
        "upload_url": upload_url,
        "expires_in": f"{link_service.expiry_hours} hour(s)",
    }


# ── record_id_upload ────────────────────────────────────────────

RECORD_TOOL_NAME = "record_id_upload"
RECORD_TOOL_DESCRIPTION = (
    "Record that the guest has uploaded their ID document. "
    "Updates the guest record with the file path and marks "
    "ID as verified. Use this after the guest confirms "
    "upload or when the upload endpoint processes the file."
)
RECORD_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
        "file_path": {
            "type": "string",
            "description": "The filesystem path where the ID document was saved.",
        },
    },
    "required": ["session_id", "file_path"],
}


async def record_id_upload(
    db_session: AsyncSession, session_id: str, file_path: str
) -> dict[str, Any]:
    """Record that the guest uploaded their ID document.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        file_path: The filesystem path where the file was saved.

    Returns:
        Dict with uploaded status or error.
    """
    if not session_id:
        return {"error": "session_id is required"}
    if not file_path:
        return {"error": "file_path is required"}

    # Find session
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Find guest
    stmt = select(Guest).where(Guest.id == session.guest_id)
    result = await db_session.execute(stmt)
    guest = result.scalar_one_or_none()

    if guest is None:
        return {"error": f"Guest not found for session: {session_id}"}

    # Update guest record
    guest.id_document_path = file_path
    guest.id_verified = True
    await db_session.flush()

    logger.info(
        "ID upload recorded: session=%s guest=%s file=%s",
        session_id,
        guest.id,
        file_path,
    )

    return {
        "uploaded": True,
        "guest_id": guest.id,
        "id_document_path": file_path,
        "id_verified": True,
    }
