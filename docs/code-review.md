# Code Review — Guest Check-In System

## Summary

The Guest Check-In system is a well-structured, thoughtfully designed FastAPI application with a clean state machine, solid LLM fallback strategy, and comprehensive MCP tool layer. The codebase follows good patterns: async-first, Pydantic validation, ORM-based queries (no raw SQL), HMAC-signed tokens, and a dual-path (LLM + regex) intent detection system. However, there are several **critical security and correctness issues** that must be addressed before production deployment, alongside important design gaps and a number of minor concerns. The overall architecture is sound; the issues are fixable without rearchitecting.

**Recommendation: ⚠️ Needs fixes before merge — 6 critical, 8 important issues found.**

---

## Critical Issues

### 🔴 C1: OTP codes stored in plaintext — timing attack vulnerability

**Files:** `app/models/otp_verification.py`, `app/mcp_tools/otp_tools.py`, `app/api/otp.py`

OTP codes are stored as plaintext `String(10)` in the database and compared with a simple `==` equality check (`otp_record.otp_code != otp_code`). This is vulnerable to:
1. **Timing attacks** — string equality short-circuits on the first differing character.
2. **Database compromise** — an attacker with DB read access can use any active OTP directly.
3. **Log leakage** — while the code doesn't log OTPs, any future logging change would expose them.

**Fix:** Hash OTP codes with `hashlib.sha256` + a per-record salt before storage. Compare with `hmac.compare_digest` on the hashed values. Only store the hash; the plaintext code is only in the email.

### 🔴 C2: `LINK_SECRET` defaults to "change-me-in-production" — insecure default

**File:** `app/config.py` (line 38)

```python
LINK_SECRET: str = "change-me-in-production"
```

This secret is used for HMAC-signing all secure upload/payment link tokens. If an operator deploys without setting this env var, every token is forgeable by anyone who knows the default. The application should **refuse to start** (or at minimum log a loud warning) when this value is the default in a non-dev environment.

**Fix:** Add a validator to `Settings` that raises an error if `LINK_SECRET == "change-me-in-production"` and `DATABASE_URL` doesn't contain `localhost`. Alternatively, always require the env var in production.

### 🔴 C3: API keys stored as plaintext — no hashing

**File:** `app/models/api_key.py`, `app/auth/api_key.py`

API keys are stored in the database as plaintext strings and compared with direct equality (`APIKey.key == api_key`). If the database is compromised, all API keys are immediately leaked. API keys are long-lived credentials and should be hashed like passwords.

**Fix:** Store `SHA-256(key)` or `bcrypt(key)` in the DB. When validating, hash the incoming key and compare against the stored hash.

### 🔴 C4: Session token expiry is based on `last_message_at` — not `created_at`

**File:** `app/auth/session_token.py` (lines 42–49)

```python
if session.last_message_at is not None:
    last_active = session.last_message_at
    ...
    if now - last_active > timedelta(hours=token_max_age_hours):
        return None
```

A session token never expires as long as the guest keeps sending messages. This is an **infinite session** vulnerability — a token stolen once is valid forever (as long as the attacker sends at least one message per 24 hours). The spec says "24-hour expiry" but there's no absolute expiry.

**Fix:** Add an `expires_at` column to the `Session` model set at creation time, and check both absolute and idle expiry.

### 🔴 C5: No rate limiting on WebSocket endpoint

**File:** `app/api/websocket.py`

The REST API endpoints are rate-limited via `slowapi` (60/min per API key), but the WebSocket endpoint at `/api/v1/ws/{session_id}` has no rate limiting. An attacker could flood the WebSocket with messages, causing excessive LLM calls (if Ollama is up) and database operations. The `WSIncoming.content` max_length of 5000 chars is the only constraint.

**Fix:** Add per-session rate limiting in the WebSocket message loop — e.g., max 20 messages per minute per session, with a `asyncio.sleep` backoff or disconnect on violation.

### 🔴 C6: Duplicate agreement recording — both `SessionManager._advance_state()` and `ToolRouter` can record agreements

**Files:** `app/session_manager.py` (lines 376–410), `app/agent/tool_router.py` (lines 19–49), `app/mcp_tools/agreement_tools.py`

When a guest agrees to an agreement:
1. `SessionManager._advance_state()` checks if the current state is an agreement state and **creates an Agreement record** directly (lines 399–410).
2. `ToolRouter.route()` also maps `("agree", PRIVACY_POLICY_PENDING)` → `record_agreement` tool, which **creates another Agreement record**.

This results in **duplicate agreement records** for every acceptance. The `record_agreement` MCP tool and the `SessionManager` are both creating agreements independently. Either the MCP tool should be the single source, or the `SessionManager` should be, but not both.

**Fix:** Remove the direct `Agreement` creation from `SessionManager._advance_state()` and rely solely on the MCP tool via `ToolRouter`, OR remove `record_agreement` from the `_INTENT_STATE_TOOL_MAP` for agree intents and let the `SessionManager` handle it.

---

## Important Issues

### 🟡 I1: Knowledge base FAQ matching is naïve — loads all entries per property

**Files:** `app/session_manager.py` (`_answer_question`, lines 52–62), `app/mcp_tools/faq_tools.py` (`get_faq_answer`)

`_answer_question()` loads up to 10 KB entries and does word-overlap matching. The FAQ tool loads all entries for a property and computes a keyword score. Both approaches:
- Have no relevance threshold tuning (the score of `2` is arbitrary).
- Don't handle multi-word phrases ("check-in" ≠ "check" + "in").
- Will degrade as the KB grows — loading all entries is O(n) per query.
- `_answer_question()` in `session_manager.py` is a **duplicate** of the FAQ tool logic.

**Fix:** Consolidate to use the MCP `get_faq_answer` tool exclusively. Consider adding a `keywords` column or full-text search for the KB.

### 🟡 I2: `_enrich_response()` in `SessionManager` is a no-op

**File:** `app/session_manager.py` (lines 455–472)

The `_enrich_response()` method does nothing — it just returns `agent_content` unchanged. The comments say "the endpoint can append instructions after calling process_message" but this is confusing design. The enrichment (ID upload link, incidental link, arrival instructions) is done at the endpoint level, duplicating logic between `sessions.py` and `websocket.py`.

**Fix:** Remove `_enrich_response()` and refactor so enrichment happens in one place — either inside `SessionManager.process_message()` or in a shared helper function.

### 🟡 I3: Incidental selection page has broken HTML — dollar signs not escaped

**File:** `app/api/incidental.py` (lines 128–202)

The `_build_selection_page()` function uses Python f-strings with `{{` and `}}` for JS/CSS, but the dollar amounts use `\` (backslash) incorrectly:

```python
"<div class=\"price\">\\9.99</div>"    # Should be $49.99
"<div class=\"price\">(.00</div>"       # Should be $250.00
```

These render as broken text, not currency amounts. The `\` is being consumed by Python's string escaping.

**Fix:** Use `$49.99` and `$250.00` directly in the f-string (the `$` has no special meaning in Python f-strings; it's only special in shell/format strings).

### 🟡 I4: `IncidentalSelection.amount` uses `Float` column — precision loss

**File:** `app/models/incidental_selection.py` (line 21)

```python
amount = Column(Float, nullable=False)
```

Float columns in MySQL/SQLAlchemy lose precision for monetary values (e.g., `49.99` may store as `49.9899999...`). This is a well-known anti-pattern for financial data.

**Fix:** Use `Numeric(10, 2)` or `DECIMAL(10, 2)` instead of `Float`.

### 🟡 I5: Missing `index` on `agreements.session_id` and `messages.session_id`

**Files:** `app/models/agreement.py`, `app/models/message.py`

Foreign key columns used in WHERE clauses (`session_id`) lack indexes. The `messages` table in particular will be queried per-session for message history, and without an index this is a full table scan.

**Fix:** Add `index=True` to the `session_id` columns on `Agreement`, `Message`, `AuditTrail`, `OTPVerification`, and `IncidentalSelection` models.

### 🟡 I6: Ollama exception handler returns HTTP 200 for an error

**File:** `app/main.py` (lines 102–117)

```python
@app.exception_handler(OllamaUnavailableError)
async def ollama_unavailable_handler(...) -> JSONResponse:
    return JSONResponse(status_code=200, ...)
```

Returning HTTP 200 with an error body violates REST conventions. Clients may not check the body for errors. If Ollama is down, the response should be a 503 or at minimum a 200 with a very explicit error structure. The current `"fallback": True` flag could be easily missed.

**Fix:** Return `status_code=503` or at least include a non-2xx status. Alternatively, if the intent is to still serve the guest, return 200 but with a much more prominent error indicator in the response schema.

### 🟡 I7: WebSocket creates a new DB session per message — no connection pool limits configured

**File:** `app/api/websocket.py` (line 297)

```python
async with async_session_factory() as db:
```

Every WebSocket message creates a new database session. Under high load with 50 concurrent sessions, this could exhaust the MySQL connection pool. The `create_async_engine()` call in `database.py` uses default pool settings (5 connections, 10 max overflow).

**Fix:** Configure explicit pool settings: `pool_size=20, max_overflow=30, pool_timeout=30`. Consider using a shared DB session per WebSocket connection instead of per-message.

### 🟡 I8: No CSRF protection on ID upload and incidental selection POST endpoints

**Files:** `app/api/id_upload.py`, `app/api/incidental.py`

These endpoints are authenticated with HMAC-signed link tokens in the URL path, but there's no CSRF protection. A malicious site could trick a user's browser into submitting a POST to `/api/v1/incidental/{token}` (the browser would include any cookies if added later). While the HMAC token provides some protection (the attacker would need to know the token), the GET endpoint leaks the upload page HTML, and the token is in the URL.

**Fix:** Add a CSRF token or at minimum verify the `Origin`/`Referer` header on POST requests.

---

## Minor Issues

### 🟢 N1: `_answer_question()` is duplicated between `session_manager.py` and `fallback.py`

Both files define the same `_answer_question()` function with identical logic. This is a maintenance hazard.

**Fix:** Move to a shared module (e.g., `app/services/faq_service.py`) and import from both.

### 🟢 N2: `_agreement_type_for_state()` is duplicated between `session_manager.py` and `fallback.py`

Same issue — identical function in two files.

**Fix:** Move to `app/state_machine/states.py` or a shared utility.

### 🟢 N3: `SessionManager` is a module-level singleton but has mutable `_llm_client` state

**File:** `app/api/sessions.py` (line 29)

```python
_session_manager = SessionManager()
```

The `SessionManager` is created once and shared across all requests. The `_ensure_llm()` method lazily initializes the `OllamaClient`, but if Ollama becomes unreachable after initialization, the client remains set and retries will fail. There's no mechanism to reset the client.

**Fix:** Add a health check or circuit breaker pattern for the OllamaClient.

### 🟢 N4: `FallbackAgent.process_message()` duplicates `SessionManager.process_message()` logic

**File:** `app/agent/fallback.py` (lines 274–367)

The `process_message()` method on `FallbackAgent` is a near-copy of `SessionManager.process_message()`. Any bug fix in one must be applied to the other. This is used by the WebSocket handler as a simpler path.

**Fix:** Refactor so `FallbackAgent` is only responsible for intent detection and response generation, not the full message processing flow. The `SessionManager` should always be the orchestrator.

### 🟢 N5: `E2E test` leaves `test_e2e.db` file on disk

**File:** `tests/e2e_happy_path.py` (line 23)

Uses a file-based SQLite (`./test_e2e.db`) and tries to clean up with `os.unlink`, but if the test crashes, the file remains. Also, the monkey-patching of `app.database` globals is fragile.

**Fix:** Use `:memory:` SQLite for E2E tests, or use a temp file from `tempfile.mkstemp()`.

### 🟢 N6: WebSocket integration tests use `asyncio.get_event_loop().run_until_complete()` 

**File:** `tests/integration/test_websocket.py` (lines 136, 159, etc.)

`get_event_loop()` is deprecated in Python 3.10+. These should use `pytest-asyncio` markers consistently.

### 🟢 N7: `IncidentalSelectRequest` doesn't validate `selection_type` values

**File:** `app/schemas/incidental.py`

```python
selection_type: str = Field(..., description="Type of incidental protection: damage_waiver or security_hold")
```

The description says it should be `damage_waiver` or `security_hold`, but any string is accepted. The validation happens in the endpoint handler instead.

**Fix:** Use `Literal["damage_waiver", "security_hold"]` or add a Pydantic validator.

### 🟢 N8: `ReservationResponse` exposes sensitive data — `wifi_password` and `lockbox_code`

**File:** `app/schemas/reservation.py` (lines 23–24)

The reservation endpoint returns Wi-Fi password and lockbox code to any API key holder. These should only be available after check-in is complete.

**Fix:** Add a `include_sensitive: bool` parameter or split into `ReservationSummary` and `ReservationDetail` schemas.

### 🟢 N9: Alembic migration environment doesn't handle async engine

**File:** `migrations/env.py`

The `run_migrations_online()` function creates a sync engine from config, but the application uses an async engine (`aiomysql`). Running `alembic upgrade head` may fail or use the wrong driver.

**Fix:** Configure `alembic.ini` with the sync `pymysql` URL and ensure the migration env uses that. Or use `alembic` with async support.

### 🟢 N10: Session `status` field is a free-form string with no enum validation

**File:** `app/models/session.py` (line 23)

```python
status = Column(String(20), default="active")
```

Only `"active"` and potentially `"completed"` / `"refused"` are meaningful, but nothing enforces this. Any string can be written.

**Fix:** Add a `SessionStatus` enum (like `State`) and use it for validation.

### 🟢 N11: `otp_tools.py` uses `random.randint` instead of `secrets.choice`

**File:** `app/mcp_tools/otp_tools.py` (line 77)

```python
otp_code = "".join([str(random.randint(0, 9)) for _ in range(OTP_CODE_LENGTH)])
```

`random.randint` is not cryptographically secure. OTP codes should use `secrets.randbelow(10)` or `secrets.choice(string.digits)`.

**Fix:** Replace with `secrets.choice(string.digits)` in a list comprehension.

### 🟢 N12: `otp.py` API endpoint also generates OTPs with `random.choices`

**File:** `app/api/otp.py` (line 48)

Same issue — uses `random.choices` instead of `secrets.choice`.

### 🟢 N13: No database connection retry / exponential backoff

The spec (§14) says "Database connection failures trigger retry with exponential backoff (3 attempts)." This is not implemented — `database.py` uses default SQLAlchemy pool settings without retry logic.

**Fix:** Add retry logic around `get_db()` or use `tenacity` for automatic retries on `OperationalError`.

### 🟢 N14: `json.loads` on LLM entity extraction output can be fragile

**File:** `app/agent/entity_extractor.py` (lines 127–133)

The regex `r"\{[^}]+\}"` won't match nested JSON objects. If the LLM returns a JSON object with nested values, the extraction will fail silently.

**Fix:** Use a more robust JSON extraction approach (e.g., find the first `{` and last `}`, or use `json5`).

---

## State Machine Correctness

The state machine is **well-designed and correct**. Key observations:

- ✅ All transitions in the spec are implemented and tested
- ✅ Decline paths correctly transition to `REFUSED` from all three agreement states
- ✅ Resume from `REFUSED` correctly resets to `INIT`
- ✅ `provide_info` correctly self-loops in `INFO_VERIFY_PENDING`
- ✅ Audit trail captures every transition with actor, from/to state, and details
- ✅ `can_transition()` and `get_next_state()` are consistent with `VALID_TRANSITIONS`

**One gap:** The spec says "Guests can resume from the last completed step if they pause or disconnect." The current implementation resets to `INIT` on resume, not to the last completed step. This is a design deviation that should be documented or fixed.

---

## LLM Agent Assessment

The dual-path (LLM + regex fallback) design is solid:

- ✅ LLM intent detection with regex fallback when Ollama is down
- ✅ Entity extraction with regex fallback
- ✅ State-aware intent detection (e.g., "correct" → `confirm` in INFO_VERIFY)
- ✅ Tool routing with clear `intent × state → tool` mapping
- ✅ Lazy LLM initialization so app starts without Ollama

**Concerns:**

1. The LLM is used only for intent classification and entity extraction — the **conversational response** is never generated by the LLM. All agent responses come from `_STATE_RESPONSES` templates or the `FallbackAgent`. The `PromptBuilder` is never invoked in the actual message flow. This means the system is effectively a **rule-based chatbot with LLM-enhanced intent detection**, not a true conversational AI agent. This may be intentional for v1 but limits the quality of responses.

2. The `PromptBuilder` and its tool descriptions section are built but never used in the message processing pipeline. Dead code path.

3. No conversation history is passed to the LLM — each intent detection call is stateless. This could cause inconsistent intent classification for multi-turn conversations.

---

## API Design Assessment

- ✅ RESTful endpoints with consistent `/api/v1/` prefix
- ✅ API key auth for platform endpoints, session token auth for guest endpoints
- ✅ WebSocket with proper auth validation on connect
- ✅ Pydantic schema validation on all inputs
- ✅ Proper HTTP status codes (404, 422, 503)

**Gaps:**

1. No pagination on `GET /sessions/{id}/messages` — could return thousands of messages for long sessions.
2. No `DELETE` endpoint for sessions — no way to clean up test/expired sessions.
3. The `POST /sessions/{id}/resume` endpoint only works for `REFUSED` sessions, but the spec mentions "pause and resume" — there's no `PAUSED` state or pause mechanism.
4. The health check at `/health` doesn't verify DB or Ollama connectivity — it just returns `{"status": "ok"}`.

---

## Database Assessment

- ✅ SQLAlchemy async with proper session management
- ✅ All models use UUID primary keys
- ✅ Foreign key relationships are properly defined
- ✅ Alembic migration is present and matches model definitions
- ✅ `expire_on_commit=False` avoids lazy-load issues in async context

**Gaps:**

1. Missing indexes on foreign keys (I5 above)
2. `Float` for monetary amount (I4 above)
3. No database-level `CHECK` constraints or `ENUM` types for status fields
4. `Session.updated_at` uses `onupdate=func.now()` but this may not work reliably with async SQLAlchemy — explicit timestamp updates (as done in `session_manager.py` line 214) are preferred

---

## Test Coverage Assessment

### What's tested well:
- ✅ State machine transitions (14+ unit tests covering happy path, decline, resume, edge cases)
- ✅ FallbackAgent intent detection (12+ regex pattern tests)
- ✅ Entity extraction with LLM + regex fallback (8+ tests)
- ✅ MCP tools (12+ tests covering all tools with DB fixtures)
- ✅ ToolRouter mapping (12+ tests)
- ✅ Link service token generation/verification (7+ tests)
- ✅ Storage service validation (6+ tests)
- ✅ WebSocket connection lifecycle (4+ tests)
- ✅ Pydantic schema validation (10+ tests)
- ✅ E2E happy path script

### Missing test coverage:
- ❌ **No test for duplicate agreement recording** (C6)
- ❌ **No test for concurrent session access** (race conditions on state transitions)
- ❌ **No test for OTP timing attack** (C1)
- ❌ **No API endpoint integration tests** (no tests for `POST /sessions`, `POST /messages`, `GET /state`, `POST /resume`)
- ❌ **No test for session token expiry** (absolute or idle)
- ❌ **No test for WebSocket rate limiting** (C5)
- ❌ **No test for the incidental selection HTML page rendering**
- ❌ **No test for the `SessionManager.process_message()` full flow** (only E2E script, not pytest)
- ❌ **No negative test for ID upload** (e.g., expired token, wrong purpose)
- ❌ **No load/concurrency test** for 50 simultaneous sessions

---

## Configuration Assessment

- ✅ `pydantic-settings` with `.env` file support
- ✅ Sensitive defaults are documented in `.env.example`
- ✅ Docker Compose properly configures env vars
- ❌ `LINK_SECRET` default is insecure (C2)
- ❌ No `LOG_LEVEL` or `LOG_FORMAT` configuration
- ❌ No `SENTRY_DSN` or error monitoring config
- ❌ `CORS_ORIGINS` is a list with hardcoded defaults — no wildcard option for dev
- ❌ `RATE_LIMIT` config is defined but not actually applied to endpoints (slowapi limiter is created but not used as a decorator on any route)

---

## Overall Assessment

⚠️ **Needs fixes before merge.**

The architecture is sound and the implementation is largely well-done. The state machine is correctly implemented with full audit trail. The dual-path intent detection (LLM + regex) provides excellent resilience. The MCP tool registry pattern is clean and extensible.

**Must fix before production:**
1. 🔴 C1 — Hash OTP codes before storage
2. 🔴 C2 — Force `LINK_SECRET` configuration in production
3. 🔴 C3 — Hash API keys before storage
4. 🔴 C4 — Add absolute session token expiry
5. 🔴 C5 — Add WebSocket rate limiting
6. 🔴 C6 — Fix duplicate agreement recording

**Should fix before production:**
7. 🟡 I3 — Fix broken dollar signs in incidental selection page
8. 🟡 I4 — Use `DECIMAL` for monetary amounts
9. 🟡 I5 — Add indexes on foreign key columns
10. 🟡 I7 — Configure DB connection pool limits
11. 🟢 N11/N12 — Use `secrets` module for OTP generation
