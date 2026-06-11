"""Audit trail endpoint — paginated state-transition history for a guest session."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import get_api_key
from app.database import get_db
from app.models.api_key import APIKey
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.session import Session
from app.schemas.audit import AuditTrailEntry, AuditTrailResponse

router = APIRouter(tags=["audit"])


@router.get(
    "/guests/{guest_id}/audit-trail",
    response_model=AuditTrailResponse,
    summary="Get paginated audit trail for a guest",
)
async def get_guest_audit_trail(
    guest_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Entries per page (max 200)"),
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> AuditTrailResponse:
    """Return paginated audit trail entries for all sessions belonging to a guest.

    Looks up the guest, finds their sessions, and returns AuditTrail rows
    ordered by created_at descending with offset/limit pagination.
    """
    # Verify guest exists
    result = await db.execute(
        select(Guest).where(Guest.id == guest_id)
    )
    guest = result.scalar_one_or_none()
    if guest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guest not found: {guest_id}",
        )

    # Get all session IDs for this guest
    session_result = await db.execute(
        select(Session.id).where(Session.guest_id == guest_id)
    )
    session_ids = [row[0] for row in session_result.all()]
    if not session_ids:
        return AuditTrailResponse(
            entries=[], total=0, page=page, page_size=page_size
        )

    # Total count
    count_result = await db.execute(
        select(func.count()).where(AuditTrail.session_id.in_(session_ids))
    )
    total = count_result.scalar() or 0

    # Paginated query — newest first
    offset = (page - 1) * page_size
    entries_result = await db.execute(
        select(AuditTrail)
        .where(AuditTrail.session_id.in_(session_ids))
        .order_by(AuditTrail.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = entries_result.scalars().all()

    entries = [
        AuditTrailEntry(
            id=entry.id,
            session_id=entry.session_id,
            action=entry.action,
            from_state=entry.from_state or "",
            to_state=entry.to_state or "",
            details=entry.details,
            timestamp=entry.created_at,
            actor=entry.actor,
        )
        for entry in rows
    ]

    return AuditTrailResponse(
        entries=entries,
        total=total,
        page=page,
        page_size=page_size,
    )
