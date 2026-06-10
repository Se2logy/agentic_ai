# Test Coverage Matrix — Conversation-Based Guest Check-In

## 1. Interactive Elements

| ID | Element | Where (mockup / file) | Test ID(s) |
|----|---------|------------------------|------------|
| IE-001 | "I agree to the Privacy Policy" button | mockup-01 · chat-widget.js | UX-A-001, UX-A-002, UX-A-003, E2E-001 |
| IE-002 | Progress bar (6-step indicator) | mockup-01..04 · chat-widget.js | UX-A-001, UX-B-001, UX-C-001, UX-D-001, WIDGET-001 |
| IE-003 | "Upload Your ID" button (secure link) | mockup-02 · chat-widget.js | UX-B-001, UX-B-002, UX-B-003, E2E-001 |
| IE-004 | "Select" button (Damage Waiver card) | mockup-03 · chat-widget.js | UX-C-001, UX-C-002, UX-C-003, E2E-001 |
| IE-005 | "Select" button (Security Hold card) | mockup-03 · chat-widget.js | UX-C-001, UX-C-002, UX-C-003, E2E-001 |
| IE-006 | Chat input field | mockup-02,03 · chat-widget.js | UX-A-003, UX-B-003, WIDGET-002, E2E-001 |
| IE-007 | Send button | mockup-02,03 · chat-widget.js | UX-B-003, WIDGET-002, E2E-001 |
| IE-008 | Close/minimize widget (X button) | mockup-02 · chat-widget.js | WIDGET-003, E2E-008 |
| IE-009 | GuestCheckIn.init() config | widget.js · spec §10.1 | WIDGET-004 |
| IE-010 | WebSocket message send | ws endpoint · chat-widget.js | WS-001, WS-002, WS-003 |
| IE-011 | Session resume endpoint | POST /sessions/{id}/resume · api/sessions.py | SM-008, SM-009, E2E-005 |
| IE-012 | OTP verify input + submit | POST /otp/verify · api/otp.py | SVC-005, INT-003, E2E-001 |

## 2. State Transitions

| ID | From → To | Trigger | Test ID(s) |
|----|-----------|---------|------------|
| ST-001 | INIT → PRIVACY_POLICY_PENDING | POST /sessions (create session) | SM-001, E2E-001 |
| ST-002 | PRIVACY_POLICY_PENDING → HOUSE_RULES_PENDING | record_agreement(privacy_policy, accepted=true) | SM-002, E2E-001 |
| ST-003 | PRIVACY_POLICY_PENDING → REFUSED | record_agreement(privacy_policy, accepted=false) | SM-003, E2E-004 |
| ST-004 | HOUSE_RULES_PENDING → RENTAL_AGREEMENT_PENDING | record_agreement(house_rules, accepted=true) | SM-002, E2E-001 |
| ST-005 | HOUSE_RULES_PENDING → REFUSED | record_agreement(house_rules, accepted=false) | SM-003, E2E-004 |
| ST-006 | RENTAL_AGREEMENT_PENDING → INFO_VERIFY_PENDING | record_agreement(rental_agreement, accepted=true) | SM-002, E2E-001 |
| ST-007 | RENTAL_AGREEMENT_PENDING → REFUSED | record_agreement(rental_agreement, accepted=false) | SM-003, E2E-004 |
| ST-008 | INFO_VERIFY_PENDING → ID_VERIFY_PENDING | update_guest_info + OTP verified | SM-004, E2E-001 |
| ST-009 | ID_VERIFY_PENDING → INCIDENTAL_PROTECTION_PENDING | record_id_upload | SM-005, E2E-001 |
| ST-010 | INCIDENTAL_PROTECTION_PENDING → COMPLETED | record_incidental_selection | SM-006, E2E-001 |
| ST-011 | REFUSED → PRIVACY_POLICY_PENDING | POST /sessions/{id}/resume | SM-008, SM-009, E2E-005 |
| ST-012 | COMPLETED → (terminal) | N/A — arrival instructions generated | SM-007, E2E-001 |
| ST-013 | Any non-terminal → same state | Question / greeting / off-topic message | AGENT-001, AGENT-005, E2E-006 |
| ST-014 | INFO_VERIFY_PENDING → INFO_VERIFY_PENDING | Guest provides corrections | SM-004, E2E-001 |
| ST-015 | * → * (invalid) | Attempt to skip a step | SM-010, E2E-009 |

## 3. Error & Edge Cases

| ID | Case | Trigger | Recovery | Test ID(s) |
|----|------|---------|----------|------------|
| EC-001 | Decline privacy policy | "I decline" at PRIVACY_POLICY_PENDING | Resume from beginning | SM-003, E2E-004 |
| EC-002 | Decline house rules | "I decline" at HOUSE_RULES_PENDING | Resume from beginning | SM-003, E2E-004 |
| EC-003 | Decline rental agreement | "I decline" at RENTAL_AGREEMENT_PENDING | Resume from beginning | SM-003, E2E-004 |
| EC-004 | Invalid state transition | Skip from PRIVACY_POLICY_PENDING to ID_VERIFY_PENDING | SM raises InvalidTransitionError, agent responds with clarification | SM-010, E2E-009 |
| EC-005 | Ollama unreachable | Network failure to Ollama | Fallback to regex intent matcher | AGENT-007, INT-006 |
| EC-006 | LLM hallucination (wrong intent) | Agent misclassifies "I agree" as question | State machine rejects invalid tool call | SM-010, AGENT-006, E2E-009 |
| EC-007 | MySQL connection failure | DB down during session create | Retry 3x → 503 Service Unavailable | API-012, INT-007 |
| EC-008 | OTP expiry | Verify OTP after 10 minutes | Re-trigger OTP | SVC-005, SVC-006, INT-003 |
| EC-009 | OTP max attempts exceeded | 3 wrong OTP codes | OTP invalidated, must re-trigger | SVC-006, INT-003 |
| EC-010 | Expired secure upload link | Click link after 1 hour | Auto-regenerate on next message | SVC-008, INT-004 |
| EC-011 | Invalid API key | Request with wrong X-API-Key | HTTP 401 | API-009, INT-005 |
| EC-012 | Missing API key | Request without X-API-Key | HTTP 401 | API-010, INT-005 |
| EC-013 | Expired session token | Guest-facing request with expired token | HTTP 401 | API-011, INT-005 |
| EC-014 | Missing reservation | get_reservation with unknown booking_ref | Tool returns not found | MCP-001, MCP-013 |
| EC-015 | Duplicate session for same booking | POST /sessions with existing active session | HTTP 409 or return existing | API-002 |
| EC-016 | WebSocket disconnect | Network drop | Auto-reconnect, session persists in MySQL | WS-004, WS-005, E2E-008 |
| EC-017 | Concurrent session updates | Two requests update same session | Row-level locking prevents corruption | INT-008 |
| EC-018 | Invalid entity extraction | Guest says "4 people" in wrong state | Agent ignores or re-prompts | AGENT-004 |
| EC-019 | Upload wrong file type | Upload .exe instead of image | Upload page rejects file | SVC-007, INT-004 |
| EC-020 | Payment failure | Mock payment returns failed | Guest can retry selection | SVC-003, INT-004 |
| EC-021 | Rate limiting | >60 req/min per API key | HTTP 429 | API-013 |
| EC-022 | Empty guest message | Send blank message | Agent re-prompts or ignores | AGENT-001, API-005 |

## 4. Mockup States Reachable by User Action

| Mockup | State | Reachable via | Test ID(s) |
|--------|-------|---------------|------------|
| 01 (Privacy Policy) | PRIVACY_POLICY_PENDING — step 1/6 | New session created, agent presents policy | UX-A-001, UX-A-002, UX-A-003, E2E-001 |
| 02 (ID Verification) | ID_VERIFY_PENDING — step 5/6 | Accept 3 agreements + verify info → agent generates upload link | UX-B-001, UX-B-002, UX-B-003, E2E-001 |
| 03 (Incidental Protection) | INCIDENTAL_PROTECTION_PENDING — step 6/6 | Upload ID → agent presents selection cards | UX-C-001, UX-C-002, UX-C-003, E2E-001 |
| 04 (Completion) | COMPLETED — 6/6 steps done | Select incidental option → arrival instructions shown | UX-D-001, UX-D-002, UX-D-003, E2E-001 |

## 5. Cross-State Recovery Flows

| ID | Scenario | Test ID(s) |
|----|----------|------------|
| CSR-001 | Decline policy → resume → re-start from PRIVACY_POLICY_PENDING | SM-009, E2E-005 |
| CSR-002 | Pause after HOUSE_RULES_PENDING → disconnect → reconnect → resume at RENTAL_AGREEMENT_PENDING | WS-005, E2E-008 |
| CSR-003 | OTP expired → re-trigger → verify with new code | SVC-006, INT-003 |
| CSR-004 | Upload link expired → agent auto-regenerates | SVC-008, INT-004 |
| CSR-005 | Payment failed → retry incidental selection | SVC-003, INT-004 |
| CSR-006 | Ollama down → regex fallback completes step → Ollama recovers for next step | AGENT-007, INT-006 |
| CSR-007 | Guest asks question mid-agreement → agent answers → re-prompts for agreement | AGENT-005, E2E-006 |
| CSR-008 | Invalid transition attempted → error message → guest stays in current state | SM-010, E2E-009 |
