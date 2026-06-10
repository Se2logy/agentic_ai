# JACKHAMR.md — Guest Check-In System Codebase Map

## Project Overview
- **Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), MySQL 8.0, Ollama (Llama 3.1 8B), MailHog
- **Architecture:** State machine (9 states) + LLM Agent (intent/entity/tools) + 12 MCP Tools + REST API + WebSocket
- **Test framework:** pytest + pytest-asyncio
- **Package manager:** pip (requirements.txt)
- **Docker:** docker-compose.yml (app + MySQL + MailHog)

## Directory Structure
```
guest-checkin/
├── app/
│   ├── main.py                 # FastAPI app factory, lifespan, CORS, exception handlers
│   ├── config.py               # pydantic-settings config (DATABASE_URL, LINK_SECRET, etc.)
│   ├── database.py             # SQLAlchemy async engine + session factory + Base
│   ├── session_manager.py      # Main orchestrator: intent→entity→tool→state→response
│   ├── agent/
│   │   ├── llm_client.py       # Ollama API client (lazy init, timeout, retry)
│   │   ├── intent.py           # Intent detection (LLM-first, regex fallback)
│   │   ├── entity_extractor.py # Entity extraction (LLM-first, regex fallback)
│   │   ├── tool_router.py      # Intent×State → MCP tool dispatch
│   │   ├── prompt_builder.py   # System prompt builder (DEAD CODE — never invoked)
│   │   ├── fallback.py         # FallbackAgent (regex-only when Ollama down)
│   │   └── exceptions.py       # OllamaUnavailableError, IntentDetectionError, EntityExtractionError
│   ├── api/
│   │   ├── router.py           # Aggregate all routers
│   │   ├── sessions.py         # POST/GET sessions, POST/GET messages, GET state, POST resume
│   │   ├── reservations.py     # GET reservation by booking_ref
│   │   ├── otp.py              # POST trigger OTP, POST verify OTP
│   │   ├── id_upload.py        # GET upload page, POST upload file
│   │   ├── incidental.py       # GET selection page, POST select + mock payment
│   │   └── websocket.py        # WS endpoint with auth, rate limiting, ConnectionManager
│   ├── auth/
│   │   ├── api_key.py          # API key validation (SHA-256 hash lookup)
│   │   └── session_token.py    # Session token generation + validation (HMAC-signed)
│   ├── mcp_tools/
│   │   ├── registry.py         # ToolRegistry (description dict for LLM prompt)
│   │   ├── reservation_tools.py # get_reservation
│   │   ├── agreement_tools.py  # record_agreement
│   │   ├── guest_tools.py      # update_guest_info
│   │   ├── otp_tools.py        # trigger_otp, verify_otp (SECURE: hmac.compare_digest, secrets.choice)
│   │   ├── id_upload_tools.py  # generate_id_upload_link, record_id_upload
│   │   ├── incidental_tools.py # generate_incidental_link, record_incidental_selection
│   │   ├── arrival_tools.py    # get_arrival_instructions
│   │   └── faq_tools.py        # get_faq_answer, get_current_state
│   ├── models/
│   │   ├── guest.py            # Guest model
│   │   ├── session.py          # Session model (state, booking_ref, guest_id)
│   │   ├── reservation.py      # Reservation model (property, dates, wifi, lockbox)
│   │   ├── agreement.py        # Agreement model (type, agreed/declined)
│   │   ├── message.py          # Message model (role, content)
│   │   ├── otp_verification.py # OTPVerification model (otp_code, expires, attempts)
│   │   ├── incidental_selection.py # IncidentalSelection model (selection_type, amount Float→DECIMAL needed)
│   │   ├── audit_trail.py      # AuditTrail model (actor, from_state, to_state, details)
│   │   ├── api_key.py          # APIKey model (key hash, name, active)
│   │   └── knowledge_base.py   # KnowledgeBase model (property_id, question, answer, keywords)
│   ├── schemas/
│   │   ├── session.py          # CreateSessionRequest, SessionResponse, SessionStateResponse
│   │   ├── message.py          # SendMessageRequest, MessageResponse, AgentResponse
│   │   ├── otp.py              # OTPVerifyRequest, OTPVerifyResponse
│   │   └── incidental.py       # IncidentalSelectRequest, IncidentalSelectResponse
│   ├── services/
│   │   ├── email_service.py    # SMTP email (aiosmtplib, MailHog for dev)
│   │   ├── payment_service.py  # PaymentGateway ABC + MockPayment
│   │   ├── storage_service.py  # File storage for ID uploads
│   │   └── link_service.py     # HMAC-signed, time-limited link tokens
│   ├── state_machine/
│   │   ├── states.py           # State enum (9 states) + STATE_INFO dict
│   │   ├── transitions.py      # VALID_TRANSITIONS, can_transition(), get_next_state()
│   │   ├── machine.py          # StateMachine class (advance, decline, resume)
│   │   ├── audit.py            # log_audit() function
│   │   └── exceptions.py       # InvalidTransitionError, SessionNotFoundError, ActionRequiredError
│   ├── static/                 # chat-widget.js, chat-widget.css, index.html
│   └── templates/              # Jinja2: otp_email.html, id_upload_page.html, arrival_instructions.html
├── migrations/                  # Alembic migrations
├── seed/                        # seed_reservations.py, seed_knowledge_base.py, seed_api_keys.py
├── tests/
│   ├── unit/                   # test_state_machine.py, test_agent.py, test_mcp_tools.py, test_health.py, test_api_schemas.py
│   ├── integration/            # test_websocket.py
│   └── e2e_happy_path.py       # Standalone E2E test script
├── docs/                        # user_manual.html, user_manual.pdf
├── docker-compose.yml           # app + MySQL 8.0 + MailHog
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── pytest.ini
├── .env.example
└── .gitignore
```

## Key Patterns
- **State Machine:** 9 states (INIT → PRIVACY_POLICY → HOUSE_RULES → RENTAL_AGREEMENT → INFO_VERIFY → ID_VERIFY → INCIDENTAL_PROTECTION → COMPLETED / REFUSED). `advance()` and `decline()` with `can_transition()` validation.
- **Agent Flow:** SessionManager.process_message() → IntentDetector → EntityExtractor → ToolRouter → MCP Tool → _advance_state() → Response
- **Fallback:** When Ollama is down, FallbackAgent (regex) handles everything
- **Auth:** API key (SHA-256 hash) for platform endpoints, HMAC-signed session tokens for guest endpoints
- **DB:** SQLAlchemy async with aiomysql, UUID PKs, `expire_on_commit=False`

## Known Bugs (from code review / product review)
- OTP API endpoint uses `==` comparison (timing attack) + `random.choices` (insecure) — MCP tool path is fixed
- Broken dollar signs in incidental selection HTML page
- ~~Absolute session expiry is 48h instead of 24h~~ **FIXED** — session_token.py now uses token_max_age_hours directly (no *2)
- Missing audit trail API endpoint
- `Float` for monetary amounts instead of `DECIMAL`
- Missing FK indexes
- Duplicate helper functions across files
- DAMAGE_WAIVER_AMOUNT inconsistency ($49 vs $49.99)
