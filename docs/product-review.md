# Product Review — Conversation-Based Guest Check-In via Channel Messaging

**Date:** 2025-06-10
**Reviewer:** product-reviewer

---

## 1. Spec Compliance Audit

### 1.1 State Machine (7 states + REFUSED)

| # | State | Defined? | Transitions Implemented? | Tests? |
|---|---|---|---|---|
| 1 | INIT | ✅ | ✅ start → PRIVACY_POLICY_PENDING | ✅ |
| 2 | PRIVACY_POLICY_PENDING | ✅ | ✅ agree → HOUSE_RULES, decline → REFUSED | ✅ |
| 3 | HOUSE_RULES_PENDING | ✅ | ✅ agree → RENTAL_AGREEMENT, decline → REFUSED | ✅ |
| 4 | RENTAL_AGREEMENT_PENDING | ✅ | ✅ agree → INFO_VERIFY, decline → REFUSED | ✅ |
| 5 | INFO_VERIFY_PENDING | ✅ | ✅ confirm → ID_VERIFY, provide_info self-loops | ✅ |
| 6 | ID_VERIFY_PENDING | ✅ | ✅ upload_id → INCIDENTAL_PROTECTION | ✅ |
| 7 | INCIDENTAL_PROTECTION_PENDING | ✅ | ✅ select_option → COMPLETED | ✅ |
| 8 | COMPLETED | ✅ | Terminal (no transitions out) | ✅ |
| 9 | REFUSED | ✅ | ✅ resume → INIT | ✅ |

**Total: 9 states (7 onboarding + COMPLETED + REFUSED) — matches spec.** All transitions verified in `transitions.py` and covered by 45 state machine unit tests (all passing).

### 1.2 MCP Tools (12 required)

| # | Tool Name | Registered? | Handler File |
|---|---|---|---|
| 1 | `get_reservation` | ✅ | `reservation_tools.py` |
| 2 | `record_agreement` | ✅ | `agreement_tools.py` |
| 3 | `update_guest_info` | ✅ | `guest_tools.py` |
| 4 | `trigger_otp` | ✅ | `otp_tools.py` |
| 5 | `verify_otp` | ✅ | `otp_tools.py` |
| 6 | `generate_id_upload_link` | ✅ | `id_upload_tools.py` |
| 7 | `record_id_upload` | ✅ | `id_upload_tools.py` |
| 8 | `generate_incidental_link` | ✅ | `incidental_tools.py` |
| 9 | `record_incidental_selection` | ✅ | `incidental_tools.py` |
| 10 | `get_arrival_instructions` | ✅ | `arrival_tools.py` |
| 11 | `get_faq_answer` | ✅ | `faq_tools.py` |
| 12 | `get_current_state` | ✅ | `faq_tools.py` |

**All 12 MCP tools registered and verified at startup.**

### 1.3 LLM Agent with Ollama + Fallback

| Component | Status |
|---|---|
| OllamaClient (llama3.1:8b) | ✅ Implemented with lazy init |
| IntentDetector | ✅ LLM-first, regex fallback |
| EntityExtractor | ✅ LLM-first, regex fallback |
| PromptBuilder | ✅ Built (dead code path — never invoked) |
| FallbackAgent | ✅ Full regex-based fallback |
| Dual-path (LLM + regex) | ✅ Working correctly |

**Note:** The LLM is used only for intent classification and entity extraction. Conversational responses are generated from static templates (`_STATE_RESPONSES`) and the `FallbackAgent`. The `PromptBuilder` is never invoked in the actual message flow. This is a design choice for v1 — the system is a rule-based chatbot with LLM-enhanced intent detection, not a true conversational AI. **This is acceptable for v1 but should be documented.**

### 1.4 REST Endpoints (11 required + 1 WebSocket)

| # | Spec Endpoint | Implemented? | Notes |
|---|---|---|---|
| 1 | `POST /api/v1/sessions` | ✅ | |
| 2 | `GET /api/v1/sessions/{id}` | ✅ | |
| 3 | `POST /api/v1/sessions/{id}/messages` | ✅ | |
| 4 | `GET /api/v1/sessions/{id}/messages` | ✅ | |
| 5 | `GET /api/v1/sessions/{id}/state` | ✅ | |
| 6 | `POST /api/v1/sessions/{id}/resume` | ✅ | |
| 7 | `GET /api/v1/reservations/{booking_ref}` | ✅ | |
| 8 | `POST /api/v1/id-upload` | ✅ | Token-based: `/api/v1/id-upload/{token}` |
| 9 | `POST /api/v1/incidental/select` | ✅ | Token-based: `/api/v1/incidental/{token}` |
| 10 | `POST /api/v1/otp/verify` | ✅ | |
| 11 | `GET /api/v1/guests/{guest_id}/audit-trail` | ❌ **MISSING** | No audit.py router, no endpoint |
| — | `ws://localhost:8000/api/v1/ws/{session_id}` | ✅ | WebSocket with auth, rate limiting |

**Missing: 1 of 11 REST endpoints** — the audit trail endpoint. The audit trail *data model* and *logging* are fully implemented (`AuditTrail` model, `log_audit()` function), but there's no API to read it.

**Extra endpoints not in spec:**
- `POST /api/v1/otp/trigger` (splits OTP trigger from verify — reasonable)
- `GET /api/v1/id-upload/{token}` (serves upload page HTML — reasonable)
- `GET /api/v1/incidental/{token}` (serves selection page HTML — reasonable)

### 1.5 Web Chat Widget

| Feature | Status |
|---|---|
| `chat-widget.js` | ✅ 16KB, full WebSocket integration |
| `chat-widget.css` | ✅ 11KB, responsive styles |
| `index.html` | ✅ 6KB demo page |
| WebSocket connection | ✅ Auth via query param token |
| Chat bubble UI | ✅ Implemented |
| Progress indicator | ✅ State-based display |

### 1.6 Email OTP via SMTP

| Feature | Status |
|---|---|
| EmailService with aiosmtplib | ✅ |
| Jinja2 OTP email template | ✅ `otp_email.html` |
| MailHog integration in Docker | ✅ |
| 10-minute OTP expiry | ✅ |
| 3 max attempts | ✅ |

### 1.7 Mock Payment with Pluggable Interface

| Feature | Status |
|---|---|
| `PaymentGateway` ABC | ✅ With `process_payment` and `refund` |
| `MockPayment` implementation | ✅ Always succeeds |
| Incidental selection page | ✅ (but with broken dollar signs — see I3) |
| Payment result recording | ✅ `IncidentalSelection` model |

### 1.8 MySQL Persistence, Audit Trail

| Feature | Status |
|---|---|
| SQLAlchemy async engine | ✅ With aiomysql driver |
| All 9 ORM models | ✅ Reservation, Guest, Session, Agreement, OTPVerification, IncidentalSelection, Message, AuditTrail, KnowledgeBase, APIKey |
| Alembic migration | ✅ `001_initial_schema.py` |
| Audit trail logging | ✅ Every state transition logged |
| Audit trail **API endpoint** | ❌ Missing |

### 1.9 User Manual PDF

| Format | Status |
|---|---|
| HTML | ✅ 1,318 lines, full architecture docs with SVG diagrams |
| PDF | ✅ 516KB, rendered from HTML |

---

## 2. Code Review Follow-Up — Critical Issue Status

### C1: OTP timing attack — **PARTIALLY FIXED**

| Code Path | Status | Detail |
|---|---|---|
| MCP tool `otp_tools.verify_otp` | ✅ Fixed | Uses `hmac.compare_digest()` for constant-time comparison |
| MCP tool `otp_tools.trigger_otp` | ✅ Fixed | Uses `secrets.randbelow(10)` for cryptographically secure OTP generation |
| API endpoint `api/otp.py:verify_otp` | ❌ **NOT FIXED** | Still uses `otp_record.otp_code == body.otp_code` (plaintext `==` comparison) |
| API endpoint `api/otp.py:trigger_otp` | ❌ **NOT FIXED** | Still uses `random.choices(string.digits, k=6)` (not cryptographically secure) |
| DB storage | ❌ **NOT FIXED** | OTP codes still stored as plaintext `VARCHAR(10)` in `otp_verifications` table — no hashing |

**Verdict: The MCP tool path is fixed but the API endpoint path is still vulnerable.** Two parallel code paths (`otp_tools.py` and `api/otp.py`) exist with inconsistent security. The API endpoint is the one guests actually use via REST. OTP codes should be hashed before storage (with per-record salt) and compared with `hmac.compare_digest` on the hash — currently neither is done in the API path.

### C2: Forgeable HMAC secret — **FIXED ✅**

`config.py` now uses `secrets.token_hex(32)` as the default, generating a random 64-character hex secret at startup. This eliminates the forgeable default. However, `.env.example` still shows `LINK_SECRET=change-me-in-production` which could mislead operators into using the insecure value. The `.env.example` should be updated to document that the secret is auto-generated but should be explicitly set in production.

### C3: Plaintext API keys — **FIXED ✅**

`auth/api_key.py` now includes `_hash_api_key()` using SHA-256. The `verify_api_key()` function hashes the incoming key before DB lookup. The seed script `seed_api_keys.py` also hashes keys before insertion. The `APIKey.key` column stores hashes, not plaintext.

### C4: No session expiry — **PARTIALLY FIXED**

`session_token.py` now includes both:
- **Absolute expiry**: `created_at + 48 hours` (hard-coded as `token_max_age_hours * 2`)
- **Idle expiry**: `last_message_at + 24 hours`

**Issue:** The absolute expiry is 48 hours (2× `SESSION_TOKEN_EXPIRY_HOURS`), not the 24-hour absolute limit the spec requires. The spec says "Session Token: Time-limited (24 hours)" but the implementation allows 48 hours absolute. The idle timeout is correct at 24 hours, but a stolen token is valid for up to 48 hours regardless of activity. This should be `token_max_age_hours` (not `* 2`).

### C5: No WS rate limiting — **FIXED ✅**

WebSocket endpoint now has per-session rate limiting: 30 messages per 60-second window. Implemented with an in-memory sliding window (`_ws_rate_limits` dict). Rate-limited messages receive an error response without processing.

### C6: Duplicate agreement recording — **FIXED ✅**

`SessionManager._advance_state()` no longer creates `Agreement` records directly. Agreement recording is handled solely by the `ToolRouter` → `record_agreement` MCP tool. The code includes comments confirming this: `"Agreement recording is handled by ToolRouter (record_agreement tool) — No need to create Agreement records here"`.

### Critical Issues Summary

| ID | Issue | Status |
|---|---|---|
| C1 | OTP timing attack | ⚠️ **PARTIAL** — MCP tool fixed, API endpoint still vulnerable |
| C2 | Forgeable HMAC secret | ✅ **FIXED** (auto-generated; .env.example still misleading) |
| C3 | Plaintext API keys | ✅ **FIXED** (SHA-256 hashed) |
| C4 | No session expiry | ⚠️ **PARTIAL** — Absolute expiry is 48h, should be 24h |
| C5 | No WS rate limiting | ✅ **FIXED** (30 msg/60s) |
| C6 | Duplicate agreement recording | ✅ **FIXED** (removed from SessionManager) |

---

## 3. Remaining Important Issues from Code Review

| ID | Issue | Fixed? | Impact |
|---|---|---|---|
| I3 | Dollar signs broken in incidental page | ❌ Not fixed | `\9.99` and `(.00` render instead of `$49.99` and `$250.00` — **guest-facing UI bug** |
| I4 | `Float` for monetary amount | ❌ Not fixed | `IncidentalSelection.amount` still uses `Float` instead of `DECIMAL(10,2)` — precision loss for financial data |
| I5 | Missing indexes on FK columns | ❌ Not fixed | No indexes on `session_id` in Agreement, Message, AuditTrail, OTPVerification, IncidentalSelection — performance issue at scale |
| I7 | No DB pool configuration | ❌ Not fixed | Default pool settings (5 connections, 10 overflow) may be insufficient for 50 concurrent sessions |

---

## 4. Deliverables Check

| Deliverable | Status | Details |
|---|---|---|
| Docker Compose (app + MySQL + MailHog) | ✅ | 3 services, MySQL healthcheck, proper networking |
| User Manual (HTML) | ✅ | 1,318 lines with architecture diagrams, API docs, state machine docs |
| User Manual (PDF) | ✅ | 516KB, rendered from HTML |
| Seed data scripts | ✅ | 3 scripts: `seed_reservations.py`, `seed_knowledge_base.py`, `seed_api_keys.py` (with SHA-256 hashing) |
| `.env.example` | ✅ | Present with all config vars documented |
| `README.md` | ✅ | Quick start, configuration, architecture reference |
| `Dockerfile` | ✅ | Present |
| `requirements.txt` | ✅ | Present |
| `alembic.ini` + migration | ✅ | Initial schema migration |
| `.gitignore` | ✅ | Present |

---

## 5. Smoke Session Findings

### 5.1 App loads and routes register correctly

- ✅ `create_app()` runs without errors
- ✅ All 16 REST routes + 1 WebSocket registered
- ✅ All 9 ORM models import successfully
- ✅ All 6 agent components import successfully
- ✅ All 4 services import successfully
- ✅ All 12 MCP tools register at startup
- ✅ 220 unit tests pass

### 5.2 Surprising issues found

1. **Two parallel OTP code paths** — `app/mcp_tools/otp_tools.py` and `app/api/otp.py` are completely independent implementations of the same OTP functionality. The MCP tool path is secure; the API path is not. This is a maintenance hazard and a security gap.

2. **Missing audit trail endpoint** — The spec explicitly requires `GET /api/v1/guests/{guest_id}/audit-trail` but there's no `audit.py` router file and no route registered. The audit data is being logged but is inaccessible via API.

3. **Broken dollar signs on guest-facing page** — The incidental selection HTML page renders `\9.99` and `(.00` instead of `$49.99` and `$250.00`. This is a visible, guest-facing UI bug from Python f-string escaping.

4. **Dead code: `PromptBuilder`** — The `PromptBuilder` class is fully implemented but never invoked in the actual message processing pipeline. The LLM is only used for intent detection and entity extraction, not for response generation.

5. **`_enrich_response()` is a no-op** — The method returns its input unchanged, with a comment saying "the endpoint can append instructions after calling process_message." This means the enrichment logic is duplicated between `sessions.py` and `websocket.py`.

6. **Session resume resets to INIT** — The spec says "Guests can resume from the last completed step if they pause or disconnect." The implementation resets to `INIT` on resume, meaning guests must redo all steps. This is a design deviation.

---

## 6. Requirements Coverage

| User Story / Requirement | Status | Notes |
|---|---|---|
| US-1: Guest completes full onboarding via chat | ✅ | State machine + agent flow working |
| US-2: Guest can decline agreements → REFUSED | ✅ | Implemented with audit trail |
| US-3: Guest can resume from REFUSED | ⚠️ | Works but resets to INIT, not last completed step |
| US-4: Guest can ask questions mid-flow | ✅ | FAQ lookup + re-prompt |
| US-5: Guest receives secure ID upload link | ✅ | HMAC-signed, time-limited, one-time |
| US-6: Guest selects incidental protection via link | ⚠️ | Works but dollar signs broken on selection page |
| US-7: Guest receives arrival instructions on completion | ✅ | Via `get_arrival_instructions` MCP tool |
| US-8: Platform integrator creates sessions via API | ✅ | API key auth, session creation endpoint |
| US-9: WebSocket real-time chat | ✅ | With auth, rate limiting, state updates |
| US-10: Audit trail per guest | ⚠️ | Data is logged but no API endpoint to retrieve it |
| US-11: Email OTP verification | ⚠️ | Works but API path has security issues (C1) |
| US-12: LLM agent with fallback | ✅ | Ollama + regex fallback working |

---

## 7. UI/UX Findings

### Broken Dollar Signs on Incidental Selection Page
- Severity: 🔴 Blocker
- What: The incidental selection page displays `\9.99` and `(.00` instead of `$49.99` and `$250.00`. The `$` character in Python f-strings is being consumed by the string escaping.
- Location: `app/api/incidental.py` line 160 (`_build_selection_page()`)
- Recommendation: Change `\\9.99` → `$49.99` and `(.00` → `$250.00` in the f-string. The `$` has no special meaning in Python f-strings.

### Payment Message Also Broken
- Severity: 🟡 Should fix
- What: Line 122 in `incidental.py`: `f"Payment of \ processed successfully."` — the dollar amount is completely missing due to escaping.
- Recommendation: Fix the f-string to include the actual amount.

---

## 8. Edge Cases & Recovery

| Scenario | Status | Notes |
|---|---|---|
| Empty state (no sessions) | ✅ | API returns 404 for non-existent sessions |
| Decline at any agreement state | ✅ | Transitions to REFUSED, guest can resume |
| Resume from REFUSED | ✅ | Transitions back to INIT (note: spec says "last completed step") |
| Invalid state transition | ✅ | `InvalidTransitionError` handled with user-friendly message |
| Ollama unavailable | ✅ | Falls back to regex-based `FallbackAgent` |
| Expired secure link | ✅ | `LinkService.verify_link()` returns None |
| Max OTP attempts exceeded | ✅ | Returns error after 3 attempts |
| WebSocket rate limiting | ✅ | 30 messages/60s per session |
| Session token expiry | ⚠️ | Absolute expiry is 48h instead of spec's 24h |
| Duplicate ID upload | ✅ | Updates guest record with latest path |
| Failed payment | ✅ | Records `payment_status="failed"`, guest can retry |

---

## 9. Test Coverage Assessment

**Unit tests: 220 passed** covering:
- ✅ State machine transitions (45 tests)
- ✅ Agent intent detection (regex patterns)
- ✅ Entity extraction
- ✅ MCP tools
- ✅ ToolRouter mapping
- ✅ Link service token generation/verification
- ✅ Storage service validation
- ✅ Pydantic schema validation
- ✅ API health check

**Missing test coverage:**
- ❌ No API endpoint integration tests (sessions CRUD, message processing, state retrieval)
- ❌ No test for OTP timing attack prevention (C1)
- ❌ No test for the broken dollar signs on incidental page (I3)
- ❌ No test for duplicate agreement recording (C6 — now fixed, but no regression test)
- ❌ No test for session token expiry (absolute or idle)
- ❌ No test for WebSocket rate limiting
- ❌ No test for the `SessionManager.process_message()` full flow
- ❌ No negative test for ID upload (expired token, wrong purpose)
- ❌ No concurrency test for 50 simultaneous sessions

---

## 10. Overall Verdict

### ⚠️ NEEDS WORK

The Guest Check-In system has a solid architecture, a correctly implemented state machine, a clean MCP tool registry, and good test coverage for core logic. The code review's 6 critical issues have been **partially addressed** — 3 fully fixed, 2 partially fixed, 1 fully fixed. However, several issues remain that block a production-ready ship:

**Must Fix Before Ship:**

1. **🔴 C1 (partial): OTP API endpoint still vulnerable** — `app/api/otp.py` uses `==` comparison (timing attack) and `random.choices` (not cryptographically secure). Must use `hmac.compare_digest` and `secrets.choice` like the MCP tool does. Additionally, OTP codes should be hashed before database storage per the original code review fix request.

2. **🔴 I3: Broken dollar signs on guest-facing incidental page** — `\9.99` and `(.00` render instead of `$49.99` and `$250.00`. This is a guest-visible UI bug that makes the payment page look broken and unprofessional.

3. **🟡 C4 (partial): Absolute session expiry is 48h, should be 24h** — Change `token_max_age_hours * 2` to `token_max_age_hours` in `session_token.py` line 51.

4. **🟡 Missing audit trail API endpoint** — The spec requires `GET /api/v1/guests/{guest_id}/audit-trail`. The audit data model and logging work perfectly but there's no way to retrieve the data via API. Create `app/api/audit.py` and register it in the router.

5. **🟡 I4: Float for monetary amount** — `IncidentalSelection.amount` uses `Float` which loses precision for financial values. Change to `Numeric(10, 2)`.

**Should Fix Before Ship:**

6. **🟢 `.env.example` still shows `LINK_SECRET=change-me-in-production`** — Update to show auto-generated default or add a comment that the secret is auto-generated.

7. **🟢 Two parallel OTP implementations** — `app/mcp_tools/otp_tools.py` and `app/api/otp.py` duplicate OTP logic with inconsistent security. The API endpoint should delegate to the MCP tools or share a common service.

8. **🟢 I5: Missing indexes on FK columns** — Add `index=True` to `session_id` on Agreement, Message, AuditTrail, OTPVerification, and IncidentalSelection models.

---

## Must Fix Before Ship

| # | Issue | File(s) | Effort |
|---|---|---|---|
| 1 | OTP API endpoint: use `hmac.compare_digest` + `secrets.choice`, hash OTP codes before DB storage | `app/api/otp.py`, `app/models/otp_verification.py` | Small |
| 2 | Fix dollar sign escaping on incidental page | `app/api/incidental.py` line 160-164, line 122 | Trivial |
| 3 | Fix absolute session expiry to 24h | `app/auth/session_token.py` line 51 | Trivial |
| 4 | Add audit trail API endpoint | New `app/api/audit.py` + router registration | Small |
| 5 | Change `Float` to `Numeric(10,2)` for monetary amount | `app/models/incidental_selection.py` line 23 | Trivial |
