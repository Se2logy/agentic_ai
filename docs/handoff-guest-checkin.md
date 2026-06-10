# Handoff — guest-checkin (TASK-004-003: State Machine)

## Files Changed

| File | Change |
|---|---|
| `app/state_machine/__init__.py` | Updated with public exports for all state machine components |
| `app/state_machine/states.py` | **New** — State enum (9 states) + STATE_INFO dict |
| `app/state_machine/transitions.py` | **New** — VALID_TRANSITIONS table, can_transition(), get_next_state(), get_required_action() |
| `app/state_machine/machine.py` | **New** — StateMachine class (advance, decline, resume, get_current_state) |
| `app/state_machine/audit.py` | **New** — log_audit() standalone function |
| `app/state_machine/exceptions.py` | **New** — InvalidTransitionError, SessionNotFoundError, ActionRequiredError |
| `pytest.ini` | **New** — asyncio_mode=auto for async test fixtures |
| `tests/unit/test_state_machine.py` | **New** — 45 unit tests |

## API Contract

### State Enum
- `State.INIT`, `State.PRIVACY_POLICY_PENDING`, `State.HOUSE_RULES_PENDING`, `State.RENTAL_AGREEMENT_PENDING`, `State.INFO_VERIFY_PENDING`, `State.ID_VERIFY_PENDING`, `State.INCIDENTAL_PROTECTION_PENDING`, `State.COMPLETED`, `State.REFUSED`
- `State` inherits from `str` — serializes as plain string (e.g., `"INIT"`)

### StateMachine Class
- `StateMachine(db_session: AsyncSession, session_id: str)`
- `async advance(intent: str, guest_response: str = None) → State` — validates transition, updates DB, logs audit
- `async decline(guest_response: str = None) → State` — sets REFUSED (only valid at agreement states)
- `async resume() → State` — resets REFUSED → INIT
- `async get_current_state() → tuple[State, str]` — returns (state, required_action)

### Transition Intents
- `"start"` (INIT → PRIVACY_POLICY_PENDING)
- `"agree"` / `"decline"` (agreement states)
- `"confirm"` (INFO_VERIFY → ID_VERIFY)
- `"provide_info"` (INFO_VERIFY → INFO_VERIFY, self-loop for corrections)
- `"upload_id"` (ID_VERIFY → INCIDENTAL_PROTECTION_PENDING)
- `"select_option"` (INCIDENTAL_PROTECTION_PENDING → COMPLETED)
- `"resume"` (REFUSED → INIT)

### Exceptions
- `InvalidTransitionError(current_state, intent)` — raised on invalid state transitions
- `SessionNotFoundError(session_id)` — raised when session ID doesn't exist in DB
- `ActionRequiredError(current_state, required_action)` — available for consumers to signal incomplete actions

## Deviations from Plan
- None — implementation matches the spec (§5) and implementation plan exactly.

## Risks / Open Questions
- The StateMachine class does NOT enforce COMPLETED as a terminal state beyond the transition table (no explicit outgoing transitions defined for COMPLETED). This is by design per the spec.
- `pytest.ini` was added (asyncio_mode=auto) because the project's pytest-asyncio version needed configuration for async fixture support in class-based tests.

## Tests
- 45 unit tests, all green
- Tests use in-memory SQLite (aiosqlite) with proper async fixtures
- Coverage: state enum, transitions, invalid transitions, decline paths, resume paths, full happy path, audit trail, exceptions

---

# Handoff — guest-checkin (TASK-004-015: MCP Tools)

## Files Changed

### New Files (app/mcp_tools/)
| File | Description |
|------|-------------|
| `registry.py` | ToolRegistry class: register(), get_tool(), get_tool_descriptions(), get_tool_names(), register_all(). Singleton `tool_registry`. |
| `reservation_tools.py` | `get_reservation(db_session, booking_reference)` → dict or None |
| `agreement_tools.py` | `record_agreement(db_session, session_id, agreement_type, accepted, guest_response)` → dict |
| `guest_tools.py` | `update_guest_info(db_session, session_id, first_name, last_name, phone)` → dict |
| `otp_tools.py` | `trigger_otp(db_session, session_id)` → dict; `verify_otp(db_session, session_id, otp_code)` → dict |
| `id_upload_tools.py` | `generate_id_upload_link(db_session, session_id)` → dict; `record_id_upload(db_session, session_id, file_path)` → dict |
| `incidental_tools.py` | `generate_incidental_link(db_session, session_id)` → dict; `record_incidental_selection(db_session, session_id, selection_type, amount)` → dict |
| `arrival_tools.py` | `get_arrival_instructions(db_session, session_id)` → dict (renders Jinja2 template) |
| `faq_tools.py` | `get_faq_answer(db_session, session_id, question)` → dict; `get_current_state(db_session, session_id)` → dict |

### New Test File
| File | Tests |
|------|-------|
| `tests/unit/test_mcp_tools.py` | 39 tests covering all 12 tools + registry |

## API Contract
All 12 tools registered with name, description, parameters JSON Schema, and async handler.

Tool names: `generate_id_upload_link`, `generate_incidental_link`, `get_arrival_instructions`, `get_current_state`, `get_faq_answer`, `get_reservation`, `record_agreement`, `record_id_upload`, `record_incidental_selection`, `trigger_otp`, `update_guest_info`, `verify_otp`

## Design Decisions
1. Explicit queries over lazy loads for async SQLAlchemy compatibility
2. FAQ stop-word filtering + minimum score threshold of 2
3. OTP: 6-digit, 10-min expiry, 3 max attempts
4. Incidental: calls MockPayment.process_payment(), stores transaction reference
5. Error dicts returned instead of exceptions

## Deviations from Plan
None

## Tests
- 39 new tests: all passing
- Full suite: 130/130 passed
