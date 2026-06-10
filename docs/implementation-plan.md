# Implementation Plan: Conversation-Based Guest Check-In via Channel Messaging

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                       Client Layer                           │
│  ┌──────────────┐              ┌──────────────────────────┐ │
│  │ Web Chat     │   WebSocket  │ REST API Clients         │ │
│  │ Widget (JS)  │──────────────│ (Booking Platforms)      │ │
│  └──────┬───────┘              └──────────┬───────────────┘ │
└─────────┼─────────────────────────────────┼─────────────────┘
          │                                 │
┌─────────┼─────────────────────────────────┼─────────────────┐
│         ▼         Application Layer       ▼                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              FastAPI Server (Uvicorn)                 │   │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────────────┐  │   │
│  │  │ REST API   │ │ WebSocket  │ │ Auth Middleware   │  │   │
│  │  │ (11 routes)│ │ Handler   │ │ (API Key + Token) │  │   │
│  │  └─────┬──────┘ └─────┬──────┘ └──────────────────┘  │   │
│  │        └────────┬──────┘                              │   │
│  │                 ▼                                      │   │
│  │  ┌──────────────────────────────────────────────────┐ │   │
│  │  │            Session Manager                        │ │   │
│  │  │  (loads/saves state, routes messages to agent)    │ │   │
│  │  └────────────┬─────────────────────┬───────────────┘ │   │
│  │               ▼                     ▼                  │   │
│  │  ┌──────────────────┐  ┌──────────────────────────┐   │   │
│  │  │  State Machine   │  │    LLM Agent Service      │   │   │
│  │  │  (7 states,      │  │  (Ollama + Llama 3.1 8B)  │   │   │
│  │  │   transitions,   │◄─┤  - Intent detection       │   │   │
│  │  │   audit trail)   │  │  - Entity extraction      │   │   │
│  │  └────────┬─────────┘  │  - Tool invocation        │   │   │
│  │           │            │  - FAQ answering          │   │   │
│  │           ▼            └───────────┬──────────────┘   │   │
│  │  ┌──────────────────┐             ▼                   │   │
│  │  │  Audit Logger    │  ┌──────────────────────────┐   │   │
│  │  └──────────────────┘  │    MCP Tools (12)         │   │   │
│  │                        │  - get_reservation         │   │   │
│  │  ┌──────────────────┐  │  - record_agreement       │   │   │
│  │  │  Services        │  │  - update_guest_info      │   │   │
│  │  │  ┌─────────────┐ │  │  - trigger_otp            │   │   │
│  │  │  │ Email (SMTP)│ │  │  - verify_otp             │   │   │
│  │  │  ├─────────────┤ │  │  - generate_id_upload_link│   │   │
│  │  │  │ Payment     │ │  │  - record_id_upload       │   │   │
│  │  │  │ (Mock/Plugg)│ │  │  - generate_incidental_link│  │   │
│  │  │  ├─────────────┤ │  │  - record_incidental_sel  │   │   │
│  │  │  │ File Store  │ │  │  - get_arrival_instructions│  │   │
│  │  │  └─────────────┘ │  │  - get_faq_answer         │   │   │
│  │  └──────────────────┘  │  - get_current_state       │   │   │
│  │                        └───────────┬──────────────┘   │   │
│  └────────────────────────────────────┼──────────────────┘   │
│                                       ▼                      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Data Layer (SQLAlchemy ORM)                │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐ │  │
│  │  │reservations│ │ guests  │ │ sessions│ │ audit_trail │ │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘ │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐ │  │
│  │  │agreements│ │otp_verif│ │incident │ │ messages     │ │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘ │  │
│  │  ┌─────────┐ ┌─────────────────────┐                  │  │
│  │  │knowledge│ │ api_keys            │                  │  │
│  │  └─────────┘ └─────────────────────┘                  │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
                  ┌───────────────┐
                  │   MySQL 8.0   │
                  └───────────────┘
```

## 2. Project Directory Structure

```
guest-checkin/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory, lifespan, CORS
│   ├── config.py                  # Settings via pydantic-settings
│   ├── database.py                # SQLAlchemy engine, session, Base
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── reservation.py
│   │   ├── guest.py
│   │   ├── session.py
│   │   ├── agreement.py
│   │   ├── otp_verification.py
│   │   ├── incidental_selection.py
│   │   ├── message.py
│   │   ├── audit_trail.py
│   │   ├── knowledge_base.py
│   │   └── api_key.py
│   ├── schemas/                   # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── session.py
│   │   ├── message.py
│   │   ├── guest.py
│   │   ├── reservation.py
│   │   ├── agreement.py
│   │   ├── otp.py
│   │   ├── incidental.py
│   │   └── state.py
│   ├── api/                       # API routes
│   │   ├── __init__.py
│   │   ├── router.py              # Main router aggregation
│   │   ├── sessions.py            # Session CRUD + messaging
│   │   ├── reservations.py        # Reservation lookup
│   │   ├── id_upload.py           # Secure ID upload endpoint
│   │   ├── incidental.py          # Incidental selection + payment
│   │   ├── otp.py                 # OTP trigger + verify
│   │   └── websocket.py           # WebSocket handler
│   ├── auth/                      # Authentication
│   │   ├── __init__.py
│   │   ├── api_key.py             # API key validation
│   │   └── session_token.py       # Session token generation/validation
│   ├── state_machine/             # State machine (core business logic)
│   │   ├── __init__.py
│   │   ├── machine.py             # StateMachine class
│   │   ├── states.py              # State enum + definitions
│   │   ├── transitions.py         # Transition rules + validation
│   │   └── audit.py               # Audit trail logging
│   ├── agent/                     # LLM Agent
│   │   ├── __init__.py
│   │   ├── llm_client.py          # Ollama API client
│   │   ├── intent.py              # Intent detection
│   │   ├── entity_extractor.py    # Entity extraction
│   │   ├── prompt_builder.py      # System prompt construction
│   │   ├── tool_router.py         # MCP tool dispatch
│   │   └── fallback.py            # Regex fallback when Ollama is down
│   ├── mcp_tools/                 # MCP Tool implementations
│   │   ├── __init__.py
│   │   ├── registry.py            # Tool registry + descriptions
│   │   ├── reservation_tools.py
│   │   ├── agreement_tools.py
│   │   ├── guest_tools.py
│   │   ├── otp_tools.py
│   │   ├── id_upload_tools.py
│   │   ├── incidental_tools.py
│   │   ├── arrival_tools.py
│   │   └── faq_tools.py
│   ├── services/                  # External service integrations
│   │   ├── __init__.py
│   │   ├── email_service.py       # SMTP email (OTP + notifications)
│   │   ├── payment_service.py     # PaymentGateway interface + MockPayment
│   │   ├── storage_service.py     # File storage for ID uploads
│   │   └── link_service.py        # Secure link generation (ID + incidental)
│   ├── templates/                 # Jinja2 templates
│   │   ├── arrival_instructions.html
│   │   ├── otp_email.html
│   │   └── id_upload_page.html
│   └── static/                    # Web chat widget
│       ├── chat-widget.js
│       ├── chat-widget.css
│       └── index.html             # Demo page for widget
├── migrations/                    # Alembic migrations
│   ├── env.py
│   ├── alembic.ini
│   └── versions/
│       └── 001_initial_schema.py
├── seed/                          # Database seed data
│   ├── seed_reservations.py
│   ├── seed_knowledge_base.py
│   └── seed_api_keys.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (test DB, mock LLM)
│   ├── unit/
│   │   ├── test_state_machine.py
│   │   ├── test_intent.py
│   │   ├── test_entity_extractor.py
│   │   ├── test_mcp_tools.py
│   │   └── test_api_schemas.py
│   ├── integration/
│   │   ├── test_api_sessions.py
│   │   ├── test_api_reservations.py
│   │   ├── test_api_otp.py
│   │   ├── test_api_id_upload.py
│   │   ├── test_api_incidental.py
│   │   ├── test_websocket.py
│   │   └── test_db_persistence.py
│   └── e2e/
│       ├── test_happy_path.py
│       ├── test_decline_path.py
│       ├── test_resume_path.py
│       ├── test_question_path.py
│       ├── test_id_upload_flow.py
│       └── test_incidental_flow.py
├── docs/
│   ├── user_manual.html           # User manual (source)
│   └── user_manual.pdf            # User manual (generated)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── alembic.ini
└── README.md
```

## 3. Build Sequence

### Phase 1: Project Scaffolding + Database
**Task 4-1: Project scaffold, config, Docker Compose**
- Create project directory structure
- `requirements.txt` with all dependencies
- `app/config.py` with pydantic-settings (DB URL, Ollama URL, SMTP, etc.)
- `app/main.py` with FastAPI app factory, lifespan, CORS
- `app/database.py` with SQLAlchemy engine, session factory, Base
- `docker-compose.yml` (app + MySQL 8.0 + MailHog)
- `Dockerfile` for the app
- `.env.example`
- `README.md` with setup instructions

**Task 4-2: Database models + Alembic migrations + seed data**
- All 10 SQLAlchemy models (reservations, guests, sessions, agreements, otp_verifications, incidental_selections, messages, audit_trail, knowledge_base, api_keys)
- Alembic setup + initial migration
- Seed data scripts (sample reservations, knowledge base entries, API keys)
- Verify: `alembic upgrade head` + seed scripts work

### Phase 2: State Machine (Core Business Logic)
**Task 4-3: State machine — states, transitions, audit**
- `state_machine/states.py` — State enum (INIT, PRIVACY_POLICY_PENDING, ..., COMPLETED, REFUSED)
- `state_machine/transitions.py` — Transition rules, validation, required actions per state
- `state_machine/machine.py` — StateMachine class (advance, decline, resume, get_current_state)
- `state_machine/audit.py` — Audit trail logging (every transition, action, guest response)
- Unit tests for all transitions, decline paths, resume paths

### Phase 3: MCP Tools + Services
**Task 4-4: MCP tools — registry + all 12 tools**
- `mcp_tools/registry.py` — Tool registry with descriptions (for LLM system prompt)
- `mcp_tools/reservation_tools.py` — get_reservation
- `mcp_tools/agreement_tools.py` — record_agreement
- `mcp_tools/guest_tools.py` — update_guest_info
- `mcp_tools/otp_tools.py` — trigger_otp, verify_otp
- `mcp_tools/id_upload_tools.py` — generate_id_upload_link, record_id_upload
- `mcp_tools/incidental_tools.py` — generate_incidental_link, record_incidental_selection
- `mcp_tools/arrival_tools.py` — get_arrival_instructions
- `mcp_tools/faq_tools.py` — get_faq_answer, get_current_state
- Unit tests for each tool

**Task 4-5: Services — email, payment, storage, links**
- `services/email_service.py` — SMTP email sending (OTP emails, notifications) with MailHog support
- `services/payment_service.py` — PaymentGateway ABC + MockPayment implementation
- `services/storage_service.py` — File storage for ID uploads (local filesystem)
- `services/link_service.py` — Secure, time-limited link generation (for ID upload + incidental selection)
- Jinja2 templates: `otp_email.html`, `id_upload_page.html`, `arrival_instructions.html`

### Phase 4: LLM Agent
**Task 4-6: LLM agent — client, intent, entities, tools, fallback**
- `agent/llm_client.py` — Ollama API client (http://localhost:11434/api/chat)
- `agent/prompt_builder.py` — System prompt construction (state-aware, includes available tools)
- `agent/intent.py` — Intent detection (agree/decline/question/provide_info/select_option/request_help/greeting/other)
- `agent/entity_extractor.py` — Entity extraction from guest messages
- `agent/tool_router.py` — Dispatch detected intent + entities to MCP tools
- `agent/fallback.py` — Regex-based fallback when Ollama is unreachable
- Unit tests for intent detection, entity extraction, tool routing

### Phase 5: API Layer + Auth
**Task 4-7: REST API — auth + sessions + reservations + OTP + ID upload + incidental**
- `auth/api_key.py` — API key validation middleware
- `auth/session_token.py` — Session token generation (secrets.token_urlsafe) + validation
- `api/sessions.py` — POST/GET sessions, POST/GET messages, GET state, POST resume
- `api/reservations.py` — GET reservation by reference
- `api/otp.py` — POST trigger OTP, POST verify OTP
- `api/id_upload.py` — POST upload ID document
- `api/incidental.py` — POST select incidental + mock payment
- `api/router.py` — Aggregate all routers
- Pydantic schemas for all request/response models
- Integration tests for all endpoints

**Task 4-8: WebSocket handler**
- `api/websocket.py` — WebSocket endpoint for real-time chat
- Connection management (connect, disconnect, message handling)
- Message routing: incoming guest message → session manager → state machine + agent → response
- Integration tests for WebSocket connect/send/receive

### Phase 6: Web Chat Widget
**Task 4-9: Reference web chat widget (vanilla JS)**
- `static/chat-widget.js` — Embeddable chat widget
- `static/chat-widget.css` — Responsive styling
- `static/index.html` — Demo page showing the widget
- Features: message list, input field, progress bar (6 steps), WebSocket connection, auto-reconnect, state indicators

### Phase 7: Integration + Polish
**Task 4-10: End-to-end wiring + session manager**
- `app/main.py` — Wire all routers, middleware, lifespan events
- Session manager: load session → route message through agent → call MCP tools → advance state → save → respond
- Error handling: Ollama down → fallback, DB error → 500, invalid state transition → 422
- Rate limiting (slowapi)
- Docker Compose verification: full stack starts, seed data loads

**Task 4-11: User manual**
- `docs/user_manual.html` — Comprehensive manual with:
  - High-level architecture diagram (SVG/HTML)
  - Process flow diagram (state machine flow)
  - Technical stack table
  - Non-technical stack table
  - Deployment instructions (Docker Compose)
  - Configuration guide (.env variables)
  - API reference (all endpoints)
  - Widget integration guide
  - Troubleshooting
- `docs/user_manual.pdf` — Generated from HTML via Playwright

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Ollama model not installed | High (first run) | High | Fallback agent (regex) + setup docs + Docker healthcheck |
| LLM hallucination (wrong intent) | Medium | High | State machine validates every transition; LLM cannot skip steps |
| MySQL connection failure | Low | High | SQLAlchemy connection pool + retry + clear error messages |
| WebSocket disconnection | Medium | Medium | Auto-reconnect in widget; session state persisted in MySQL |
| Secure link expiry edge case | Low | Medium | Auto-regenerate on next message if expired |
| Concurrent session conflicts | Low | Medium | Row-level locking on session state updates |

## 5. Architecture Decisions

1. **State machine is the source of truth** — LLM agent cannot advance state. It calls MCP tools; the state machine validates the result and transitions. This prevents hallucination from skipping steps.
2. **Ollama as local LLM runtime** — No API keys, no cloud dependency, no cost. Trade-off: requires local GPU/CPU, model must be pulled first.
3. **SQLAlchemy ORM (not raw SQL)** — Parameterized queries by default, migration support, model validation via Pydantic.
4. **Session state in MySQL (not Redis)** — Simpler stack for v1. Trade-off: higher latency per message (DB read/write). Acceptable for 50 concurrent sessions.
5. **Mock payment with ABC interface** — PaymentGateway abstract base class with MockPayment implementation. Swap for StripePayment by implementing the same interface.
6. **Vanilla JS widget** — No React/Vue dependency. Lightweight, embeddable, no build step.
7. **Alembic migrations** — Version-controlled schema changes. Seed data separate from migrations.
8. **Fallback agent** — When Ollama is unreachable, regex-based intent matching + template responses. Guests can still complete onboarding.
9. **File storage for ID uploads** — Local filesystem in v1 (volume-mounted in Docker). Cloud storage (S3) is a future enhancement.

## 6. Developer Tasks (add_tasks)

```json
[
  {"task_id": "TASK-004-001", "title": "Project scaffold + config + Docker Compose", "category": "developer", "order": 1, "depends_on": []},
  {"task_id": "TASK-004-002", "title": "Database models + Alembic migrations + seed data", "category": "developer", "order": 2, "depends_on": ["TASK-004-001"]},
  {"task_id": "TASK-004-003", "title": "State machine — states, transitions, audit trail", "category": "developer", "order": 3, "depends_on": ["TASK-004-002"]},
  {"task_id": "TASK-004-004", "title": "MCP tools — registry + all 12 tool implementations", "category": "developer", "order": 4, "depends_on": ["TASK-004-003"]},
  {"task_id": "TASK-004-005", "title": "Services — email, payment, storage, secure links", "category": "developer", "order": 5, "depends_on": ["TASK-004-002"]},
  {"task_id": "TASK-004-006", "title": "LLM agent — client, intent, entities, tools, fallback", "category": "developer", "order": 6, "depends_on": ["TASK-004-004"]},
  {"task_id": "TASK-004-007", "title": "REST API — auth + all endpoints + Pydantic schemas", "category": "developer", "order": 7, "depends_on": ["TASK-004-003", "TASK-004-005"]},
  {"task_id": "TASK-004-008", "title": "WebSocket handler for real-time chat", "category": "developer", "order": 8, "depends_on": ["TASK-004-007"]},
  {"task_id": "TASK-004-009", "title": "Web chat widget (vanilla JS + CSS + demo page)", "category": "developer", "order": 9, "depends_on": ["TASK-004-008"]},
  {"task_id": "TASK-004-010", "title": "End-to-end wiring + session manager + error handling + rate limiting", "category": "developer", "order": 10, "depends_on": ["TASK-004-006", "TASK-004-008"]},
  {"task_id": "TASK-004-011", "title": "User manual (HTML + PDF with diagrams, flows, tech stack)", "category": "developer", "order": 11, "depends_on": ["TASK-004-010"]}
]
```

## 7. Dependencies Graph

```
TASK-004-001 (scaffold)
  └→ TASK-004-002 (DB models)
       ├→ TASK-004-003 (state machine)
       │    ├→ TASK-004-004 (MCP tools)
       │    │    └→ TASK-004-006 (LLM agent)
       │    └→ TASK-004-007 (REST API) ←── TASK-004-005 (services)
       │         └→ TASK-004-008 (WebSocket)
       │              ├→ TASK-004-009 (chat widget)
       │              └→ TASK-004-010 (E2E wiring) ←── TASK-004-006
       │                   └→ TASK-004-011 (user manual)
```

Critical path: 001 → 002 → 003 → 004 → 006 → 010 → 011 (7 sequential tasks)
Parallel opportunity: 005 (services) can run in parallel with 003+004, merges at 007
