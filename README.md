# Agentic AI — Conversation-Based Guest Check-In via Channel Messaging

A fully agent-based private check-in assistant that integrates into any booking application via a REST API endpoint. Guests complete a multi-step onboarding process (Privacy Policy, House Rules, Rental Agreement, Information Verification, ID Verification, Incidental Protection Selection) through natural conversation with an AI agent, orchestrated by a deterministic state machine.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Client Layer: Web Chat Widget (JS) + REST API Clients  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  Application Layer                                       │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ FastAPI     │  │ WebSocket  │  │ Auth Middleware   │  │
│  │ (14 routes) │  │ Handler    │  │ (API Key + Token) │  │
│  └──────┬──────┘  └─────┬──────┘  └──────────────────┘  │
│         └───────┬────────┘                               │
│                 ▼                                         │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Session Manager (message → agent → tool → state) │   │
│  └────────┬─────────────────────┬──────────────────┘    │
│           ▼                     ▼                        │
│  ┌──────────────────┐  ┌──────────────────────────┐    │
│  │  State Machine   │  │    LLM Agent Service      │    │
│  │  (9 states)      │◄─┤  (Ollama + Llama 3.1 8B)  │   │
│  └────────┬─────────┘  │  + Regex Fallback          │   │
│           │            └───────────┬──────────────┘    │
│           ▼                        ▼                    │
│  ┌──────────────┐  ┌──────────────────────────────┐    │
│  │  Audit Trail │  │    MCP Tools (12)             │   │
│  └──────────────┘  └──────────┬───────────────────┘    │
│                              ▼                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Services: Email (SMTP) | Payment (Mock) |       │   │
│  │  Storage (File) | Secure Links                    │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────┘
                           ▼
                  ┌───────────────┐
                  │   MySQL 8.0   │
                  └───────────────┘
```

## Tech Stack (All Open-Source)

| Component | Technology | License |
|---|---|---|
| Web Framework | FastAPI 0.110+ | MIT |
| ASGI Server | Uvicorn | BSD |
| ORM | SQLAlchemy 2.0+ | MIT |
| Migrations | Alembic | MIT |
| Database | MySQL 8.0 | GPL |
| LLM Runtime | Ollama + Llama 3.1 8B | MIT / Llama 3.1 |
| Email (Dev) | MailHog | MIT |
| Template Engine | Jinja2 | BSD |
| Validation | Pydantic v2 | MIT |
| Testing | pytest + Playwright | MIT / Apache 2.0 |
| Containers | Docker + Docker Compose | Apache 2.0 |

## Quick Start

```bash
cd guest-checkin
cp .env.example .env                    # Configure environment
docker-compose up -d                    # Start MySQL + MailHog
ollama pull llama3.1:8b                # Pull the LLM model
alembic upgrade head                   # Run database migrations
python seed/seed_api_keys.py           # Seed API keys
python seed/seed_reservations.py       # Seed sample reservations
python seed/seed_knowledge_base.py     # Seed FAQ entries
uvicorn app.main:app --reload          # Start the app
```

Open `http://localhost:8000/static/index.html` for the demo chat widget.

## State Machine Flow

```
INIT → PRIVACY_POLICY_PENDING → HOUSE_RULES_PENDING → RENTAL_AGREEMENT_PENDING
  → INFO_VERIFY_PENDING → ID_VERIFY_PENDING → INCIDENTAL_PROTECTION_PENDING → COMPLETED
                                                                          ↗
  Any agreement state ── decline ──→ REFUSED ── resume ──→ INIT (restart)
```

## API Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/sessions` | API Key | Create check-in session |
| GET | `/api/v1/sessions/{id}` | API Key | Get session status |
| POST | `/api/v1/sessions/{id}/messages` | Session Token | Send guest message |
| GET | `/api/v1/sessions/{id}/messages` | Session Token | Get message history |
| GET | `/api/v1/sessions/{id}/state` | Session Token | Get current state |
| GET | `/api/v1/sessions/{id}/audit-trail` | API Key | Get audit trail |
| POST | `/api/v1/sessions/{id}/resume` | Session Token | Restart refused session |
| GET | `/api/v1/reservations/{ref}` | API Key | Get reservation details |
| POST | `/api/v1/otp/trigger` | Session Token | Trigger email OTP |
| POST | `/api/v1/otp/verify` | Session Token | Verify OTP code |
| POST | `/api/v1/id-upload/{token}` | Secure Link | Upload ID document |
| GET | `/api/v1/id-upload/{token}` | Secure Link | ID upload form |
| POST | `/api/v1/incidental/{token}` | Secure Link | Select incidental + payment |
| GET | `/api/v1/incidental/{token}` | Secure Link | Incidental selection page |
| WS | `/api/v1/ws/{id}?token=...` | Session Token | Real-time chat |

## Project Structure

```
guest-checkin/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # SQLAlchemy async engine
│   ├── session_manager.py   # Message → agent → tool → state orchestrator
│   ├── state_machine/       # State machine (9 states, transitions, audit)
│   ├── agent/               # LLM agent (Ollama, intent, entities, fallback)
│   ├── mcp_tools/           # 12 MCP tool implementations + registry
│   ├── api/                 # REST endpoints + WebSocket handler
│   ├── auth/                # API key + session token authentication
│   ├── models/              # 10 SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # Email, payment, storage, secure links
│   ├── static/              # Web chat widget (vanilla JS + CSS)
│   └── templates/           # Jinja2 templates (OTP email, ID upload, arrival)
├── migrations/              # Alembic database migrations
├── seed/                    # Database seed scripts
├── tests/                   # 232 unit + integration + E2E tests
├── docs/                    # User manual (HTML + PDF)
├── docker-compose.yml       # App + MySQL 8.0 + MailHog
├── Dockerfile               # Python 3.11-slim
└── requirements.txt         # All dependencies
```

## Documentation

All project documentation is in the `docs/` folder at the repository root:

| File | Description |
|---|---|
| `docs/spec.md` | Full product specification |
| `docs/spec.pdf` | Spec as PDF |
| `docs/implementation-plan.md` | Implementation plan with build sequence |
| `docs/test-plan.md` | Test plan (90 tests across 7 areas) |
| `docs/test-coverage.md` | Test coverage analysis |
| `docs/code-review.md` | Code review findings |
| `docs/product-review.md` | Product review |
| `docs/clarifications.md` | Gate 0 Q&A from user |
| `docs/handoff-guest-checkin.md` | Developer handoff notes |
| `docs/user_manual.pdf` | User manual with architecture diagrams |
| `docs/user_manual.html` | User manual source (HTML) |
| `docs/mockups/` | 5 UI mockup images |

## Testing

```bash
cd guest-checkin
pip install -r requirements.txt
python -m pytest tests/ -v    # 232 tests
```

## Security

- OTP verification uses `hmac.compare_digest` (constant-time comparison)
- API keys stored as SHA-256 hashes (never plaintext)
- Secure link tokens use HMAC-SHA256 with auto-generated secrets
- Session tokens expire after 24h (absolute + idle timeout)
- WebSocket rate limiting (30 messages/60s per session)
- Monetary amounts use `DECIMAL(10,2)` (not Float)
- All SQL uses SQLAlchemy ORM (parameterized queries)
- Input validation via Pydantic v2

## License

All libraries used are open-source and free. See individual package licenses for details.
