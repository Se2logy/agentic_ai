"""Reservation lookup endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import get_api_key
from app.database import get_db
from app.models.api_key import APIKey
from app.models.reservation import Reservation
from app.schemas.reservation import ReservationResponse

router = APIRouter(tags=["reservations"])


@router.get(
    "/reservations/{booking_reference}",
    response_model=ReservationResponse,
    summary="Get reservation details",
)
async def get_reservation(
    booking_reference: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> ReservationResponse:
    """Look up a reservation by its booking reference.

    Requires a valid API key in the X-API-Key header.
    """
    result = await db.execute(
        select(Reservation).where(
            Reservation.booking_reference == booking_reference
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation not found: {booking_reference}",
        )
    return ReservationResponse.model_validate(reservation)
