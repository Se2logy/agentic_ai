"""Incidental protection selection endpoints — serve selection page and process payment."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.incidental_selection import IncidentalSelection
from app.models.session import Session
from app.schemas.incidental import IncidentalSelectRequest, IncidentalSelectResponse
from app.services import link_service, payment_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["incidental"])

# Damage waiver and security hold amounts
DAMAGE_WAVER_AMOUNT = 49.00
SECURITY_HOLD_AMOUNT = 250.00

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@router.get(
    "/incidental/{token}",
    summary="Serve incidental selection page",
    response_class=HTMLResponse,
)
async def get_incidental_page(
    token: str,
) -> HTMLResponse:
    """Render the incidental protection selection page for a secure link token."""
    payload = link_service.verify_link(token)
    if payload is None or payload.get("purpose") != "incidental_protection":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired selection link",
        )

    html_content = _build_selection_page(token)
    return HTMLResponse(content=html_content)


@router.post(
    "/incidental/{token}",
    response_model=IncidentalSelectResponse,
    summary="Submit incidental protection selection + mock payment",
)
async def select_incidental(
    token: str,
    body: IncidentalSelectRequest,
    db: AsyncSession = Depends(get_db),
) -> IncidentalSelectResponse:
    """Process the guest incidental protection selection and mock payment."""
    payload = link_service.verify_link(token)
    if payload is None or payload.get("purpose") != "incidental_protection":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired selection link",
        )

    session_id = payload["session_id"]

    valid_types = {"damage_waiver", "security_hold"}
    if body.selection_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid selection type. Must be one of: {', '.join(valid_types)}",
        )

    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    amount = DAMAGE_WAIVER_AMOUNT if body.selection_type == "damage_waiver" else SECURITY_HOLD_AMOUNT

    description = f"Incidental protection - {body.selection_type}"
    payment_result = await payment_service.process_payment(
        guest_id=session.guest_id,
        amount=amount,
        description=description,
        metadata={"session_id": session_id, "selection_type": body.selection_type},
    )

    incidental = IncidentalSelection(
        session_id=session_id,
        selection_type=body.selection_type,
        amount=amount,
        payment_status="completed" if payment_result.success else "failed",
        payment_reference=payment_result.transaction_id,
    )
    db.add(incidental)
    await db.flush()

    if not payment_result.success:
        logger.warning("Payment failed for session %s: %s", session_id, payment_result.message)
        return IncidentalSelectResponse(
            selection_type=body.selection_type,
            amount=amount,
            payment_status="failed",
            payment_reference=payment_result.transaction_id,
            message=f"Payment failed: {payment_result.message}",
        )

    logger.info("Incidental selection for session %s: %s", session_id, body.selection_type)

    return IncidentalSelectResponse(
        selection_type=body.selection_type,
        amount=amount,
        payment_status="completed",
        payment_reference=payment_result.transaction_id,
        message=f"Payment of ${amount:.2f} processed successfully. {payment_result.message}",
    )


def _build_selection_page(token: str) -> str:
    """Build the HTML selection page for incidental protection."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Select Incidental Protection</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f5f7; margin: 0; padding: 0; }}
    .container {{ max-width: 520px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
    .header {{ background: #1a73e8; padding: 28px 24px; text-align: center; }}
    .header h1 {{ color: #fff; margin: 0; font-size: 22px; }}
    .body {{ padding: 32px 24px; }}
    .option {{ border: 2px solid #e8eaed; border-radius: 8px; padding: 20px; margin-bottom: 16px; cursor: pointer; }}
    .option:hover {{ border-color: #1a73e8; }}
    .option.selected {{ border-color: #1a73e8; background: #e8f0fe; }}
    .option h3 {{ margin: 0 0 8px; font-size: 16px; color: #333; }}
    .option .price {{ font-size: 24px; font-weight: 700; color: #1a73e8; margin: 8px 0; }}
    .option p {{ font-size: 14px; color: #5f6368; margin: 0; }}
    .submit-btn {{ display: block; width: 100%; margin-top: 20px; padding: 14px; font-size: 16px; font-weight: 600; color: #fff; background: #1a73e8; border: none; border-radius: 8px; cursor: pointer; }}
    .submit-btn:disabled {{ background: #9aa0a6; cursor: not-allowed; }}
    .footer {{ padding: 16px 24px 24px; text-align: center; font-size: 12px; color: #9aa0a6; border-top: 1px solid #e8eaed; }}
    .result {{ display: none; text-align: center; padding: 32px 24px; }}
    .result.success {{ color: #1e8e3e; }}
    .result.error {{ color: #d93025; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header"><h1>Incidental Protection</h1></div>
    <div class="body" id="selectionForm">
      <p>Please select your preferred incidental protection option:</p>
      <div class="option" id="damageWaiver" onclick="selectOption('damage_waiver')">
        <h3>Damage Waiver</h3><div class="price">$49.00</div>
        <p>Covers accidental damages during your stay. Non-refundable.</p>
      </div>
      <div class="option" id="securityHold" onclick="selectOption('security_hold')">
        <h3>Security Hold</h3><div class="price">$250.00</div>
        <p>Refundable hold on your card. Released after checkout if no damage.</p>
      </div>
      <button type="button" class="submit-btn" id="submitBtn" disabled onclick="submitSelection()">Confirm &amp; Pay</button>
    </div>
    <div class="result" id="result"></div>
    <div class="footer">Guest Check-In System &mdash; Secure Payment<br>This link expires in 1 hour.</div>
  </div>
  <script>
    let selectedType = null;
    function selectOption(type) {{
      selectedType = type;
      document.getElementById('damageWaiver').classList.toggle('selected', type === 'damage_waiver');
      document.getElementById('securityHold').classList.toggle('selected', type === 'security_hold');
      document.getElementById('submitBtn').disabled = false;
    }}
    function submitSelection() {{
      if (!selectedType) return;
      const btn = document.getElementById('submitBtn');
      btn.disabled = true; btn.textContent = 'Processing...';
      fetch(window.location.href, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{selection_type: selectedType}})
      }})
      .then(r => r.json().then(d => ({{ok: r.ok, data: d}})))
      .then(result => {{
        document.getElementById('selectionForm').style.display = 'none';
        const rd = document.getElementById('result'); rd.style.display = 'block';
        if (result.ok) {{ rd.className = 'result success'; rd.innerHTML = '<h2>Payment Successful!</h2><p>' + result.data.message + '</p>'; }}
        else {{ rd.className = 'result error'; rd.innerHTML = '<h2>Payment Failed</h2><p>' + (result.data.detail||result.data.message||'Error') + '</p>'; }}
      }})
      .catch(err => {{
        document.getElementById('selectionForm').style.display = 'none';
        const rd = document.getElementById('result'); rd.style.display = 'block';
        rd.className = 'result error'; rd.innerHTML = '<h2>Error</h2><p>' + err.message + '</p>';
      }});
    }}
  </script>
</body>
</html>"""
