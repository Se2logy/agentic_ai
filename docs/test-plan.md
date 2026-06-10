# Test Plan: Conversation-Based Guest Check-In via Channel Messaging

## Coverage Summary
8 E2E browser tests · 17 unit (state machine) · 20 unit (MCP tools) · 14 unit (LLM agent) · 17 integration (REST API) · 6 integration (WebSocket) · 8 unit (services) = 90 total covering 7 feature areas.

## Test Areas

### 1. State Machine (SM)
Tests for state transitions, decline paths, resume, and audit trail.

| ID | Class | Description |
|---|---|---|
| SM-001 | unit | Advance from INIT to PRIVACY_POLICY_PENDING when session starts |
| SM-002 | unit | Advance from PRIVACY_POLICY_PENDING to HOUSE_RULES_PENDING on agreement |
| SM-003 | unit | Advance from HOUSE_RULES_PENDING to RENTAL_AGREEMENT_PENDING on agreement |
| SM-004 | unit | Advance from RENTAL_AGREEMENT_PENDING to INFO_VERIFY_PENDING on agreement |
| SM-005 | unit | Advance from INFO_VERIFY_PENDING to ID_VERIFY_PENDING after OTP verified |
| SM-006 | unit | Advance from ID_VERIFY_PENDING to INCIDENTAL_PROTECTION_PENDING after ID uploaded |
| SM-007 | unit | Advance from INCIDENTAL_PROTECTION_PENDING to COMPLETED after selection |
| SM-008 | unit | Decline at PRIVACY_POLICY_PENDING sets state to REFUSED and halts |
| SM-009 | unit | Decline at HOUSE_RULES_PENDING sets state to REFUSED and halts |
| SM-010 | unit | Decline at RENTAL_AGREEMENT_PENDING sets state to REFUSED and halts |
| SM-011 | unit | Resume from REFUSED resets to INIT and restarts flow |
| SM-012 | unit | Cannot advance without completing required action |
| SM-013 | unit | Cannot skip states (e.g., cannot jump from PRIVACY to ID_VERIFY) |
| SM-014 | unit | Audit trail records every state transition with timestamp and actor |
| SM-015 | unit | Audit trail records guest responses (agree/decline) |
| SM-016 | unit | get_current_state returns correct state for active session |
| SM-017 | unit | get_current_state returns required action for current state |

### 2. MCP Tools (TOOL)
Tests for each of the 12 MCP tools.

| ID | Class | Description |
|---|---|---|
| TOOL-001 | unit | get_reservation returns reservation by booking reference |
| TOOL-002 | unit | get_reservation returns None for non-existent reference |
| TOOL-003 | unit | record_agreement saves acceptance with correct agreement_type |
| TOOL-004 | unit | record_agreement saves refusal with guest_response |
| TOOL-005 | unit | update_guest_info updates first_name, last_name, phone |
| TOOL-006 | unit | trigger_otp creates OTP record and sends email |
| TOOL-007 | unit | verify_otp returns True for correct code within expiry |
| TOOL-008 | unit | verify_otp returns False for incorrect code |
| TOOL-009 | unit | verify_otp returns False after 3 failed attempts |
| TOOL-010 | unit | verify_otp returns False for expired code |
| TOOL-011 | unit | generate_id_upload_link creates time-limited secure link |
| TOOL-012 | unit | record_id_upload marks ID as uploaded and verified |
| TOOL-013 | unit | generate_incidental_link creates secure selection link |
| TOOL-014 | unit | record_incidental_selection saves damage_waiver with amount |
| TOOL-015 | unit | record_incidental_selection saves security_hold with amount |
| TOOL-016 | unit | get_arrival_instructions generates instructions from reservation data |
| TOOL-017 | unit | get_faq_answer returns matching FAQ from knowledge base |
| TOOL-018 | unit | get_faq_answer returns default for no match |
| TOOL-019 | unit | get_current_state returns session state and required action |
| TOOL-020 | unit | All tools validate required parameters (missing param raises error) |

### 3. LLM Agent (AGENT)
Tests for intent detection, entity extraction, tool routing, and fallback.

| ID | Class | Description |
|---|---|---|
| AGENT-001 | unit | Intent detection: "I agree" → agree |
| AGENT-002 | unit | Intent detection: "I decline" / "I disagree" → decline |
| AGENT-003 | unit | Intent detection: "What is the Wi-Fi?" → question |
| AGENT-004 | unit | Intent detection: "My name is John Smith" → provide_info |
| AGENT-005 | unit | Intent detection: "I'll take the damage waiver" → select_option |
| AGENT-006 | unit | Intent detection: "Help" / "I don't understand" → request_help |
| AGENT-007 | unit | Intent detection: "Hi" / "Hello" → greeting |
| AGENT-008 | unit | Intent detection: unrecognized input → other |
| AGENT-009 | unit | Entity extraction: extracts name, email, phone from guest message |
| AGENT-010 | unit | Tool routing: agree intent + PRIVACY_POLICY_PENDING → calls record_agreement |
| AGENT-011 | unit | Tool routing: question intent → calls get_faq_answer |
| AGENT-012 | unit | Fallback agent: regex matches work when Ollama is unreachable |
| AGENT-013 | unit | Fallback agent: template responses generated for each state |
| AGENT-014 | unit | Prompt builder: system prompt includes current state and available tools |

### 4. REST API (API)
Integration tests for all 11 endpoints.

| ID | Class | Description |
|---|---|---|
| API-001 | integration | POST /api/v1/sessions creates session with valid booking reference |
| API-002 | integration | POST /api/v1/sessions returns 404 for non-existent booking reference |
| API-003 | integration | GET /api/v1/sessions/{id} returns session status |
| API-004 | integration | POST /api/v1/sessions/{id}/messages sends guest message and returns agent response |
| API-005 | integration | GET /api/v1/sessions/{id}/messages returns message history |
| API-006 | integration | GET /api/v1/sessions/{id}/state returns current state and required action |
| API-007 | integration | POST /api/v1/sessions/{id}/resume restarts a REFUSED session |
| API-008 | integration | GET /api/v1/reservations/{ref} returns reservation details |
| API-009 | integration | POST /api/v1/otp/verify validates correct OTP |
| API-010 | integration | POST /api/v1/otp/verify rejects incorrect OTP |
| API-011 | integration | POST /api/v1/id-upload accepts ID document and records upload |
| API-012 | integration | POST /api/v1/incidental/select records selection and mock payment |
| API-013 | integration | API key auth: valid key returns 200, invalid key returns 401 |
| API-014 | integration | API key auth: missing key returns 401 |
| API-015 | integration | Session token auth: expired token returns 401 |
| API-016 | integration | Rate limiting: >60 req/min returns 429 |
| API-017 | integration | Invalid request body returns 422 with validation errors |

### 5. WebSocket (WS)
Integration tests for real-time chat.

| ID | Class | Description |
|---|---|---|
| WS-001 | integration | WebSocket connects with valid session token |
| WS-002 | integration | WebSocket rejects connection with invalid token |
| WS-003 | integration | Send guest message → receive agent response |
| WS-004 | integration | Multiple messages in sequence advance through states |
| WS-005 | integration | WebSocket disconnect and reconnect resumes session |
| WS-006 | integration | Concurrent sessions don't interfere with each other |

### 6. Services (SVC)
Unit tests for email, payment, storage, and link services.

| ID | Class | Description |
|---|---|---|
| SVC-001 | unit | Email service sends OTP email via SMTP |
| SVC-002 | unit | Payment service (mock) records damage_waiver payment |
| SVC-003 | unit | Payment service (mock) records security_hold payment |
| SVC-004 | unit | Payment service interface validates amount > 0 |
| SVC-005 | unit | Storage service saves uploaded file and returns path |
| SVC-006 | unit | Link service generates secure link with token |
| SVC-007 | unit | Link service link expires after configured hours |
| SVC-008 | unit | Link service rejects invalid/expired token |

### 7. E2E / Browser (E2E)
End-to-end tests for complete user flows.

| ID | Class | Description |
|---|---|---|
| E2E-001 | e2e | Happy path: guest completes all 6 onboarding steps and receives arrival instructions |
| E2E-002 | e2e | Decline path: guest declines at house rules, session halted as REFUSED |
| E2E-003 | e2e | Resume path: guest declines, then resumes and completes all steps |
| E2E-004 | e2e | Question path: guest asks FAQ questions mid-onboarding, then continues |
| E2E-005 | e2e | ID upload flow: guest receives secure link, uploads ID, continues |
| E2E-006 | e2e | Incidental selection flow: guest selects damage waiver, mock payment processed |
| E2E-007 | e2e | OTP flow: guest requests OTP, receives email, enters code, verified |
| E2E-008 | e2e | Fallback path: Ollama down, guest still completes onboarding via regex fallback |

## Test Build Sequence

1. **Unit tests** (SM, TOOL, AGENT, SVC) — no external dependencies, run with pytest
2. **Integration tests** (API, WS) — require running app + MySQL test DB
3. **E2E tests** (E2E) — require full stack (app + MySQL + MailHog) + Playwright

## Test Infrastructure

- **Framework**: pytest + pytest-asyncio (async API tests)
- **E2E**: Playwright (Chromium) for browser-based flows
- **Test DB**: MySQL test database with seed data, created per test session
- **Mock LLM**: MockOllamaClient that returns predefined intents for unit tests
- **Test client**: httpx.AsyncClient for FastAPI integration tests
- **CI**: All tests run via `pytest` command, no manual steps
