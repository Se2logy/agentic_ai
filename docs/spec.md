# Product Specification: Conversation-Based Guest Check-In via Channel Messaging

## 1. Overview

A fully agent-based private check-in assistant that integrates into any booking application via a REST API endpoint. Guests complete onboarding (privacy policy, house rules, rental agreement, identity verification, ID upload, incidental protection selection) through a natural conversation with an AI agent. A state machine orchestrates the workflow and enforces business rules; the LLM agent handles intent detection, entity extraction, and tool calls — but never advances state directly.

## 2. Problem Statement

Property managers and booking platforms require guests to complete a multi-step onboarding process before arrival. Current approaches (email links, PDF forms, portal logins) suffer from:

- **Low completion rates** — guests abandon fragmented workflows across multiple systems.
- **No real-time assistance** — guests can't ask questions mid-process.
- **No audit trail** — managers lack a verifiable record of what the guest agreed to.
- **Platform lock-in** — each booking channel (Airbnb, VRBO, Booking.com) has its own messaging format, making uniform check-in impossible.

## 3. Solution

A channel-agnostic, API-first guest check-in system where:

1. A **State Machine** enforces the onboarding sequence and records every action.
2. An **LLM Agent** (Ollama + Llama 3.1 8B) converses with the guest, detects intent, extracts information, and invokes tools.
3. **MCP Tools** (internal Python functions) handle data operations — retrieving reservations, recording agreements, triggering OTP, generating secure upload/payment links.
4. A **REST API + WebSocket** layer exposes the system to any booking platform.
5. A **reference web chat widget** demonstrates integration.

## 4. User Personas

### 4.1 Guest
- Receives a booking confirmation with a check-in link or embedded chat widget.
- Converses with the AI agent to complete all onboarding steps.
- Can ask questions about the property, policies, and arrival details at any time.
- Can pause and resume onboarding later.

### 4.2 Property Manager / Platform Integrator
- Integrates the check-in API into their booking application.
- Configures property details, house rules, rental agreements, and incidental protection options.
- Views audit trail and onboarding status per guest.
- Receives completion notifications.

## 5. Onboarding Workflow — State Machine

### 5.1 States and Transitions

```
INIT → PRIVACY_POLICY_PENDING → HOUSE_RULES_PENDING → RENTAL_AGREEMENT_PENDING
     → INFO_VERIFY_PENDING → ID_VERIFY_PENDING → INCIDENTAL_PROTECTION_PENDING
     → COMPLETED
```

Each state has:
- **Required Action**: What the guest must do to advance.
- **Valid Responses**: What the agent accepts as completion.
- **On Enter**: Side effects (send policy text, generate upload link, etc.).
- **On Reject**: Handling when the guest declines (record refusal, halt onboarding).

| State | Required Action | Valid Guest Response | On Enter | On Decline |
|---|---|---|---|---|
| PRIVACY_POLICY_PENDING | Accept or decline Privacy Policy & Data Usage | "I agree" / "I accept" / "I decline" / "I disagree" | Agent presents privacy policy text | Record refusal, set status to REFUSED, halt |
| HOUSE_RULES_PENDING | Accept or decline House Rules | "I agree" / "I accept" / "I decline" / "I disagree" | Agent presents house rules text | Record refusal, set status to REFUSED, halt |
| RENTAL_AGREEMENT_PENDING | Accept Rental Agreement | "I agree" / "I accept" / "I decline" / "I disagree" | Agent presents rental agreement text | Record refusal, set status to REFUSED, halt |
| INFO_VERIFY_PENDING | Confirm personal information (name, email, phone, number of guests) | "Correct" / "That's right" / corrections to specific fields | Agent retrieves and presents reservation info | Guest provides corrections; agent updates and re-verifies |
| ID_VERIFY_PENDING | Upload government-issued ID via secure link | Link clicked + ID uploaded | Agent generates and sends secure upload link | N/A — guest must upload to advance |
| INCIDENTAL_PROTECTION_PENDING | Select Damage Waiver or Security Hold + complete payment | "Damage Waiver" / "Security Hold" / selection via link | Agent generates and sends selection + payment link | N/A — guest must select to advance |
| COMPLETED | None — onboarding finished | N/A | Generate arrival instructions, send to guest | N/A |

### 5.2 State Machine Rules

- The state machine is the **single source of truth** for guest onboarding progress.
- The LLM agent **never** advances the state directly. It detects intent and calls MCP tools; the state machine validates and transitions.
- Guests can **resume** from the last completed step if they pause or disconnect.
- Guests who **decline** an agreement are recorded as REFUSED and can restart from the beginning.
- Every state transition is logged to the audit trail with: timestamp, previous state, new state, guest action, agent tool call (if any).

### 5.3 Conversation Behavior per State

When a guest enters a state, the agent:
1. Presents the required content (policy text, agreement, info summary, etc.).
2. Waits for the guest's response.
3. If the guest asks a question, the agent answers from the FAQ/knowledge base and then re-prompts for the required action.
4. If the guest provides a valid response, the agent calls the appropriate MCP tool.
5. The state machine validates the tool result and advances (or rejects).

## 6. LLM Agent Design

### 6.1 Architecture

```
Guest Message → Intent Classifier → Entity Extractor → Tool Router → State Machine → Response Generator → Guest
```

### 6.2 Capabilities

- **Intent Detection**: Classify guest messages as: agree, decline, question, provide_info, select_option, request_help, greeting, other.
- **Entity Extraction**: Extract names, dates, email addresses, phone numbers, guest counts, and selection choices from natural language.
- **Tool Invocation**: Call the appropriate MCP tool based on detected intent and current state.
- **Question Answering**: Answer guest questions from a static knowledge base (property info, policies, local area, check-in details). No RAG in v1.
- **Contextual Prompting**: The agent receives the current state, required action, and conversation history as part of its system prompt.

### 6.3 Prompt Design

The agent's system prompt includes:
- Current state machine state and required action.
- Valid responses for the current state.
- Property details and FAQ for question answering.
- Tool descriptions and usage guidelines.
- Instructions to never advance state directly.

### 6.4 Model Configuration

- **Model**: Llama 3.1 8B Instruct
- **Runtime**: Ollama (local inference)
- **Temperature**: 0.3 (deterministic for compliance workflows)
- **Max tokens**: 1024 per response
- **Context window**: 8192 tokens (conversation history managed with sliding window)

## 7. MCP Tools

Internal Python functions exposed to the LLM agent as callable tools. The agent invokes them; the state machine validates results and transitions.

| Tool Name | Description | Parameters | Returns | State Trigger |
|---|---|---|---|---|
| `get_reservation` | Retrieve reservation details | `booking_reference` | Reservation object (guest name, email, phone, property, dates, guest count) | Any |
| `record_agreement` | Record guest acceptance or refusal of an agreement | `agreement_type`, `accepted: bool`, `guest_id` | Confirmation with timestamp | PRIVACY / HOUSE_RULES / RENTAL_AGREEMENT |
| `update_guest_info` | Update guest personal information | `guest_id`, `fields: dict` | Updated guest info | INFO_VERIFY |
| `trigger_otp` | Send email OTP to guest for info verification | `guest_id`, `email` | OTP sent confirmation | INFO_VERIFY |
| `verify_otp` | Verify OTP code entered by guest | `guest_id`, `code` | Valid/invalid | INFO_VERIFY |
| `generate_id_upload_link` | Generate a secure, time-limited link for ID upload | `guest_id` | URL string | ID_VERIFY |
| `record_id_upload` | Record that guest has uploaded their ID | `guest_id`, `file_reference` | Confirmation | ID_VERIFY |
| `generate_incidental_link` | Generate a link for incidental protection selection + payment | `guest_id` | URL string | INCIDENTAL_PROTECTION |
| `record_incidental_selection` | Record guest's incidental protection choice and payment | `guest_id`, `option: str`, `payment_ref: str` | Confirmation | INCIDENTAL_PROTECTION |
| `get_arrival_instructions` | Generate arrival instructions from template | `guest_id` | Formatted instructions text | COMPLETED |
| `get_faq_answer` | Retrieve answer from property FAQ/knowledge base | `question: str` | Answer text | Any |
| `get_current_state` | Get guest's current onboarding state | `guest_id` | State name + required action | Any |

## 8. REST API Design

### 8.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/sessions` | Create a new check-in session | API Key |
| `GET` | `/api/v1/sessions/{session_id}` | Get session status and current state | API Key |
| `POST` | `/api/v1/sessions/{session_id}/messages` | Send a guest message | API Key |
| `GET` | `/api/v1/sessions/{session_id}/messages` | Get message history | API Key |
| `GET` | `/api/v1/sessions/{session_id}/state` | Get current state machine state | API Key |
| `POST` | `/api/v1/sessions/{session_id}/resume` | Resume a paused/refused session | API Key |
| `GET` | `/api/v1/reservations/{booking_ref}` | Get reservation details | API Key |
| `POST` | `/api/v1/id-upload` | Upload ID document (from secure link) | Token |
| `POST` | `/api/v1/incidental/select` | Select incidental protection + payment (from secure link) | Token |
| `POST` | `/api/v1/otp/verify` | Verify OTP code | Token |
| `GET` | `/api/v1/guests/{guest_id}/audit-trail` | Get audit trail | API Key |

### 8.2 WebSocket

- Endpoint: `ws://localhost:8000/api/v1/ws/{session_id}`
- Protocol: JSON messages with `type` field (`guest_message`, `agent_response`, `state_change`, `error`)
- Guest messages sent via WebSocket are processed identically to REST messages.
- Agent responses and state changes are pushed to connected WebSocket clients in real time.

### 8.3 Authentication

- **Platform API Key**: Passed in `X-API-Key` header. Used by booking platforms to create sessions and retrieve data.
- **Session Token**: Generated per session. Used for guest-facing endpoints (ID upload, OTP verify, incidental selection). Time-limited (24 hours).

## 9. Database Schema

### 9.1 Core Tables

```sql
-- Reservations
CREATE TABLE reservations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_reference VARCHAR(50) UNIQUE NOT NULL,
    guest_name VARCHAR(255) NOT NULL,
    guest_email VARCHAR(255) NOT NULL,
    guest_phone VARCHAR(50),
    property_name VARCHAR(255) NOT NULL,
    property_address TEXT,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    num_guests INT DEFAULT 1,
    wifi_ssid VARCHAR(255),
    wifi_password VARCHAR(255),
    lockbox_code VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Guests
CREATE TABLE guests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    reservation_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    num_guests INT DEFAULT 1,
    id_document_ref VARCHAR(255),
    id_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id)
);

-- Sessions
CREATE TABLE sessions (
    id VARCHAR(36) PRIMARY KEY,  -- UUID
    guest_id INT NOT NULL,
    booking_reference VARCHAR(50) NOT NULL,
    current_state VARCHAR(50) NOT NULL DEFAULT 'PRIVACY_POLICY_PENDING',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE, PAUSED, REFUSED, COMPLETED
    api_key_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (guest_id) REFERENCES guests(id)
);

-- Agreements
CREATE TABLE agreements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    guest_id INT NOT NULL,
    agreement_type ENUM('privacy_policy', 'house_rules', 'rental_agreement') NOT NULL,
    accepted BOOLEAN NOT NULL,
    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (guest_id) REFERENCES guests(id)
);

-- OTP Verifications
CREATE TABLE otp_verifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    guest_id INT NOT NULL,
    code VARCHAR(6) NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Incidental Protection
CREATE TABLE incidental_selections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    guest_id INT NOT NULL,
    option_type ENUM('damage_waiver', 'security_hold') NOT NULL,
    amount DECIMAL(10,2),
    payment_ref VARCHAR(255),
    payment_status ENUM('pending', 'completed', 'failed') DEFAULT 'pending',
    selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (guest_id) REFERENCES guests(id)
);

-- Messages
CREATE TABLE messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    role ENUM('guest', 'agent', 'system') NOT NULL,
    content TEXT NOT NULL,
    intent VARCHAR(50),  -- Detected intent
    tool_call VARCHAR(100),  -- Tool name if agent called one
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Audit Trail
CREATE TABLE audit_trail (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    guest_id INT NOT NULL,
    action VARCHAR(100) NOT NULL,
    previous_state VARCHAR(50),
    new_state VARCHAR(50),
    details JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (guest_id) REFERENCES guests(id)
);

-- Knowledge Base (FAQ)
CREATE TABLE knowledge_base (
    id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API Keys
CREATE TABLE api_keys (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10. Reference Web Chat Widget

A lightweight JavaScript widget that property managers embed on their website. The widget:
- Connects to the WebSocket endpoint for real-time messaging.
- Displays the conversation in a chat bubble UI.
- Shows the current onboarding step and progress indicator.
- Handles secure link clicks (ID upload, incidental selection) in new browser tabs.
- Is responsive and works on mobile and desktop.

### 10.1 Widget Integration

```html
<script src="https://localhost:8000/static/widget.js"></script>
<script>
  GuestCheckIn.init({
    sessionId: 'SESSION_ID_FROM_API',
    wsUrl: 'ws://localhost:8000/api/v1/ws/SESSION_ID'
  });
</script>
```

## 11. Project Directory Structure

```
guest-checkin/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Configuration (DB, Ollama, SMTP, etc.)
│   ├── database.py              # SQLAlchemy engine, session, base
│   ├── models/
│   │   ├── __init__.py
│   │   ├── reservation.py
│   │   ├── guest.py
│   │   ├── session.py
│   │   ├── agreement.py
│   │   ├── otp.py
│   │   ├── incidental.py
│   │   ├── message.py
│   │   ├── audit.py
│   │   └── knowledge_base.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── session.py           # Pydantic request/response schemas
│   │   ├── message.py
│   │   ├── guest.py
│   │   └── incidental.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── sessions.py          # Session CRUD + message endpoints
│   │   ├── reservations.py
│   │   ├── upload.py            # ID upload endpoint
│   │   ├── incidental.py        # Incidental selection + payment endpoint
│   │   ├── otp.py               # OTP verify endpoint
│   │   ├── websocket.py         # WebSocket handler
│   │   └── audit.py
│   ├── state_machine/
│   │   ├── __init__.py
│   │   ├── machine.py           # State machine core logic
│   │   ├── states.py            # State definitions, transitions, validators
│   │   └── exceptions.py        # Invalid transition, validation errors
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── llm_client.py        # Ollama API client
│   │   ├── intent.py            # Intent classification
│   │   ├── entity.py            # Entity extraction
│   │   ├── prompt_builder.py    # System prompt construction
│   │   └── conversation.py      # Conversation history management
│   ├── mcp_tools/
│   │   ├── __init__.py
│   │   ├── registry.py          # Tool registry (name → function mapping)
│   │   ├── reservation_tools.py
│   │   ├── agreement_tools.py
│   │   ├── guest_tools.py
│   │   ├── otp_tools.py
│   │   ├── id_tools.py
│   │   ├── incidental_tools.py
│   │   ├── instructions_tools.py
│   │   └── faq_tools.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── checkin_service.py   # Orchestrates agent + state machine + tools
│   │   ├── email_service.py     # SMTP email sending + OTP
│   │   ├── payment_service.py   # Mock payment gateway
│   │   └── storage_service.py   # File storage for ID documents
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py              # API key + session token validation
│   │   └── audit.py             # Auto-audit-logging middleware
│   └── static/
│       ├── widget.js            # Chat widget JavaScript
│       ├── widget.css           # Chat widget styles
│       └── upload.html          # ID upload page template
├── migrations/
│   ├── env.py                   # Alembic env
│   ├── versions/                # Alembic migration scripts
│   └── alembic.ini
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_state_machine.py
│   ├── test_agent.py
│   ├── test_mcp_tools.py
│   ├── test_api_sessions.py
│   ├── test_api_upload.py
│   ├── test_api_websocket.py
│   └── test_e2e_checkin.py
├── docs/
│   └── user_manual.html         # Source for user manual PDF
├── seed_data/
│   └── sample_reservations.json # Sample data for local dev
├── requirements.txt
├── Dockerfile
├── docker-compose.yml           # App + MySQL + MailHog
├── .env.example
├── alembic.ini
└── README.md
```

## 12. Technical Stack

### 12.1 Backend
| Component | Technology | License |
|---|---|---|
| Web Framework | FastAPI 0.110+ | MIT |
| ASGI Server | Uvicorn | BSD |
| ORM | SQLAlchemy 2.0+ | MIT |
| Migrations | Alembic | MIT |
| Database | MySQL 8.0 | GPL |
| MySQL Driver | PyMySQL | MIT |
| WebSocket | FastAPI WebSocket (Starlette) | BSD |
| LLM Runtime | Ollama | MIT |
| LLM Model | Llama 3.1 8B Instruct | Llama 3.1 License |
| Email (Dev) | MailHog | MIT |
| Email (SMTP) | Python stdlib `smtplib` + `email` | PSF |
| Template Engine | Jinja2 | BSD |
| Validation | Pydantic v2 | MIT |
| Testing | pytest + pytest-asyncio | MIT |
| E2E Testing | Playwright (Python) | Apache 2.0 |

### 12.2 Frontend (Reference Widget)
| Component | Technology | License |
|---|---|---|
| Chat Widget | Vanilla JavaScript | N/A |
| Styling | CSS (no framework) | N/A |
| WebSocket Client | Native WebSocket API | N/A |

### 12.3 Infrastructure
| Component | Technology | License |
|---|---|---|
| Containerization | Docker + Docker Compose | Apache 2.0 |
| Database | MySQL 8.0 (Docker) | GPL |
| Mail (Dev) | MailHog (Docker) | MIT |

## 13. Security Considerations

- **API Key Authentication**: All platform-facing endpoints require a valid API key in the `X-API-Key` header.
- **Session Tokens**: Guest-facing endpoints (ID upload, OTP verify, incidental selection) use time-limited session tokens (24-hour expiry).
- **Secure Upload Links**: ID upload links are one-time-use, time-limited (1 hour), and token-authenticated.
- **OTP Expiry**: Email OTP codes expire after 10 minutes. Maximum 3 attempts per code.
- **SQL Injection Protection**: All database queries use SQLAlchemy ORM (parameterized by default).
- **Input Validation**: All API inputs validated via Pydantic schemas.
- **HTTPS**: Enforced in production via reverse proxy (nginx). Local dev uses HTTP.
- **CORS**: Configurable allowed origins for the chat widget.
- **Rate Limiting**: API endpoints rate-limited to 60 requests/minute per API key.

## 14. Error Handling

- **State Machine Errors**: Invalid transitions raise `InvalidTransitionError` — agent responds with clarification message.
- **LLM Errors**: If Ollama is unreachable, the system falls back to a rule-based intent matcher (regex patterns for agree/disagree/question intents) and a pre-configured response template.
- **Database Errors**: Connection failures trigger retry with exponential backoff (3 attempts). Persistent failures return 503 Service Unavailable.
- **Email Errors**: SMTP failures are logged; OTP delivery retries 3 times before notifying the guest.
- **Upload Errors**: Failed ID uploads return a user-friendly error with a retry link.
- **Payment Errors**: Failed mock payments are logged; guest can retry selection.

## 15. Testing Requirements

### 15.1 Unit Tests
- State machine: all valid transitions, invalid transitions, decline handling, resume behavior.
- Agent: intent detection for agree/disagree/question/provide_info, entity extraction for names/emails/phones/counts.
- MCP tools: each tool returns correct data, handles missing records, validates inputs.
- API endpoints: request validation, authentication, response schemas.

### 15.2 E2E Browser Tests
- Full happy path: guest completes all onboarding steps end-to-end via the chat widget.
- Decline path: guest declines privacy policy, sees refusal confirmation.
- Resume path: guest pauses after step 3, resumes and completes remaining steps.
- Question path: guest asks questions mid-onboarding, agent answers and re-prompts.
- ID upload: guest clicks upload link, uploads document, agent confirms receipt.
- Incidental selection: guest clicks selection link, chooses option, agent confirms.

### 15.3 Integration Tests
- WebSocket connection: connect, send message, receive agent response.
- OTP flow: trigger OTP, verify with correct code, verify with wrong code, verify expired code.
- API key auth: valid key accepted, invalid key rejected, missing key rejected.
- Database: session persistence across server restart.

### 15.4 Test Infrastructure
- Framework: pytest + pytest-asyncio for async tests
- E2E: Playwright (Python) with Chromium
- Database: MySQL test database with seed data, reset between tests
- CI: pytest command (`pytest tests/ -v --tb=short`)
- Mock LLM: For tests that don't need real Ollama, a mock LLM client returns canned responses.

## 16. Non-Functional Requirements

- **Response Time**: Agent responses within 5 seconds (with Ollama running locally).
- **Concurrent Sessions**: Support 50 simultaneous check-in sessions on a single server.
- **Availability**: 99.5% uptime target (single instance, no HA in v1).
- **Data Retention**: Audit trail retained for 12 months. Guest data retained per reservation lifecycle.
- **Scalability**: Stateless API layer allows horizontal scaling behind a load balancer. State machine state is in MySQL, not in memory.

## 17. Future Enhancements (Out of Scope for v1)

- Multi-channel support: SMS (Twilio), WhatsApp (Meta Business API).
- RAG-powered question answering with vector search.
- Real payment gateway integration (Stripe, Braintree).
- Automated ID validation (Jumio, Onfido).
- Multi-tenancy with row-level isolation.
- Redis session cache for high-throughput scenarios.
- i18n / multi-language support.
- Admin dashboard for property managers.
