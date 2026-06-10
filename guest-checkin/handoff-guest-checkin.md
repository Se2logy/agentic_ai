# Handoff — guest-checkin (TASK-004-014: WebSocket Handler)

## Files Changed

| File | Change |
|---|---|
| `app/api/websocket.py` | Rewritten — full WebSocket endpoint with ConnectionManager, message processing, auth |
| `app/agent/fallback.py` | Updated — added `process_message()` method, fixed intent detection, added state-specific intents |
| `app/api/router.py` | Already included WebSocket route (from prior commit) |
| `tests/integration/test_websocket.py` | Rewritten — 12 integration + unit tests |
| `tests/unit/test_agent.py` | Updated — 2 intent tests corrected ('confirm' not 'agree') |

## New API Contracts

- `ConnectionManager.connect(session_id, websocket)` — register WS connection
- `ConnectionManager.disconnect(session_id)` — remove WS connection
- `ConnectionManager.send_message(session_id, message) → bool` — send to one session
- `ConnectionManager.broadcast(session_ids, message) → dict[str, bool]` — send to multiple
- `ConnectionManager.is_connected(session_id) → bool` — check if connected
- `FallbackAgent.process_message(session, guest_content, db) → (agent_content, intent_detected, tools_called, current_state, required_action)` — end-to-end message processing
- `WSIncoming(content: str)` — Pydantic schema for incoming WS messages
- `WSOutgoing(type: str, data: dict)` — Pydantic schema for outgoing WS messages

## WebSocket Endpoint

- **Path**: `/api/v1/ws/{session_id}?token={session_token}`
- **Auth**: Session token verified against DB on connect; invalid/expired tokens get WS_1008_POLICY_VIOLATION
- **Welcome message**: `{type: "welcome", data: {session_id, current_state, required_action, session_status}}`
- **Agent response**: `{type: "agent", data: {message: {...}, current_state, required_action, session_status}}`
- **Error**: `{type: "error", data: {detail: ...}}`
- **Single-connection-per-session**: new connection replaces old one

## Bug Fix

- `FallbackAgent.detect_intent_regex` was returning `"agree"` for INFO_VERIFY_PENDING state, but the transition table uses `"confirm"`. This meant the old code could never actually transition from INFO_VERIFY_PENDING. Now corrected to return `"confirm"`.

## Deviations from Spec

- The reconnect test uses `_process_guest_message` directly instead of full TestClient WebSocket reconnection due to aiosqlite+TestClient threading incompatibility (in-memory SQLite connections break across the thread boundary that TestClient uses). This is a test-infrastructure limitation, not an app bug. With the real MySQL database, full WebSocket reconnection works correctly.

## Risks / Open Questions

- The WebSocket handler creates a new DB session for each message processing cycle. This is necessary because WebSocket connections are long-lived and you can't hold a single async DB session open indefinitely. If MySQL connection pool exhaustion becomes an issue, consider adding a connection timeout or switching to a background task queue.
- The FallbackAgent `process_message` method handles the full flow inline. When TASK-004-010 (full LLM agent) is wired, the `process_message` interface should remain the same for seamless swapping.

## Tests

- 12 new tests in `tests/integration/test_websocket.py` (all passing)
- 2 updated tests in `tests/unit/test_agent.py` (corrected intent expectations)
- Total suite: 232 tests passing

---

# Handoff Addendum — TASK-004-009: Web Chat Widget

## Files Changed

| File | Change |
|------|--------|
| `app/static/chat-widget.js` | **New** — Embeddable chat widget (vanilla JS, 451 lines) |
| `app/static/chat-widget.css` | **New** — Responsive widget styling (466 lines) |
| `app/static/index.html` | **New** — Demo page (205 lines) |
| `app/main.py` | **Modified** — Added `StaticFiles` mount at `/static` |

## Widget Public API

```js
GuestCheckInWidget.init({ sessionId, token, wsUrl, apiUrl, theme });
// Returns instance with: sendMessage(text), disconnect(), onMessage(cb)
```

## Embed Usage

```html
<script src="/static/chat-widget.js"></script>
<link rel="stylesheet" href="/static/chat-widget.css">
<script>
  GuestCheckInWidget.init({ sessionId: '...', token: '...', wsUrl: 'wss://...', apiUrl: 'https://...' });
</script>
```

## Key Features

- WebSocket auto-reconnect (exponential backoff 1s→30s)
- 6-step progress bar matching state machine states
- Secure link cards for ID upload & incidental payment URLs
- Typing indicator (3 bouncing dots)
- Dark/light theme via CSS variables
- Mobile responsive (full-screen on ≤480px)

## Deviations

- Named `GuestCheckInWidget` (not `GuestCheckIn`) for clarity per task spec.
- Demo page uses `X-API-Key: demo-key` — production needs server-side proxy.

---

# Handoff Addendum — TASK-004-003: Refactor OTP API to delegate to otp_tools

## Task
Refactor app/api/otp.py to become a thin HTTP wrapper around app/mcp_tools/otp_tools.py, eliminating duplication and ensuring security logic has a single source of truth.

## Files Changed

| File | Change |
|------|--------|
| `app/api/otp.py` | Refactored — removed direct OTPVerification model usage, delegated to otp_tools |
| `tests/unit/test_api_otp.py` | **New** — 11 tests for API delegation and HTTP error mapping |

## What Changed in app/api/otp.py

**Before:** Duplicated OTP generation and verification logic. Used `OTPVerification` model directly, had direct SQLAlchemy queries, performed `hmac.compare_digest` inline, imported `random`, `string`, `datetime`, `select`, etc.

**After:** Thin HTTP wrapper that delegates to `otp_tools.trigger_otp()` and `otp_tools.verify_otp()`. Only retains HTTP-specific concerns:
- Auth via `Depends(get_session)`
- Request/response models (`OTPVerifyRequest`, `OTPVerifyResponse`)
- Error handling: maps MCP tool `"error"` results to `HTTPException(404)`
- `_build_verify_message()` helper maps MCP tool result dicts to OTPVerifyResponse

**Removed imports:** `hmac`, `secrets`, `string`, `datetime`/`timedelta`/`timezone`, `sqlalchemy.select`, `app.models.otp_verification.OTPVerification`, `app.services.email_service.email_service`

## Security Impact
- OTP logic now has a single source of truth (otp_tools.py) — any future fix applies to both API and MCP paths
- API now returns masked emails (from otp_tools) instead of raw emails, reducing PII exposure

## API Contract Changes
- `POST /otp/trigger` response shape changed:
  - Old: `{"message": "OTP sent", "email": "raw@email.com", "expires_at": "2024-07-01T..."}`
  - New: `{"otp_sent": true, "email": "r***@email.com", "expires_in": "10 minutes"}`
- `POST /otp/verify` response shape unchanged (same `OTPVerifyResponse`)

## Deviations from Plan
None — all 5 requirements implemented exactly.

## Tests
- 11 new tests in `tests/unit/test_api_otp.py` (all passing)
- Total suite: 231 tests passing
