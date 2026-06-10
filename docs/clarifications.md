# Clarifications — Conversation-Based Guest Check-In via Channel Messaging

## Q&A from Gate 0

1. **Channel surface?** → API-first, with a reference web chat widget. The REST API is the product; the widget proves it works. Platforms integrate via API calls.
2. **LLM model?** → Llama 3.1 8B via Ollama. Local, open-source, good balance of quality and speed.
3. **OTP delivery?** → Email OTP only (via SMTP). MailHog for local dev. No SMS — it requires paid providers.
4. **Incidental Protection payment?** → Mock payment with a pluggable PaymentGateway interface. Guest selects Damage Waiver or Security Hold, system records selection + simulated payment. Architecture supports real gateway integration later.
5. **Persistence & tenancy?** → MySQL-only, single-tenant. No Redis. Session state, audit trail, reservations, guest data all in MySQL. Simple stack for local dev.

## Assumptions (confirmed unless told otherwise)

- **State machine states**: PRIVACY_PENDING → HOUSE_RULES_PENDING → RENTAL_AGREEMENT_PENDING → INFO_VERIFY_PENDING → ID_VERIFY_PENDING → INCIDENTAL_PROTECTION_PENDING → COMPLETED. Each state has required actions and valid transitions.
- **State machine is the source of truth** — the LLM agent never advances state directly. It detects intent and calls MCP tools; the state machine validates and transitions.
- **MCP tools** are internal Python functions (not external MCP servers) exposed to the LLM agent as callable tools. The agent calls them; the state machine validates the result.
- **ID verification** is a secure upload link — the guest clicks, uploads a photo of their ID, and the system stores it. No automated ID validation service (those are paid). Manual review workflow is out of scope for v1.
- **Web framework**: FastAPI (async, open-source, good for chat APIs).
- **Database ORM**: SQLAlchemy with Alembic for migrations.
- **Chat API**: WebSocket for real-time messaging + REST for message history and management.
- **RAG**: Not in v1. The agent answers guest questions from a static FAQ/knowledge base (property info, house rules text, rental agreement text). Full vector-search RAG is a future enhancement.
- **Authentication**: API key for platform integrations. Guest sessions are identified by a booking reference + session token.
- **No i18n** — English-only labels and prompts in v1.
- **Audit trail**: Every state transition, guest message, agent response, and tool call is logged to a MySQL table with timestamp and actor.
- **Error handling**: Guest can say "I disagree" at any agreement step; the system records the refusal and halts onboarding. Guest can resume later from the last completed step.
- **Arrival instructions**: Generated from a template with guest name, property address, check-in time, Wi-Fi info, and lockbox code. Stored in the database.
- **User manual**: Delivered as a PDF with architecture diagrams, process flows, tech stack, deployment instructions, and usage guide.
- **All libraries open-source and free**: Ollama, FastAPI, SQLAlchemy, Alembic, PyMySQL, WebSockets, Jinja2 (for templates), MailHog (for dev SMTP), Playwright (for E2E testing).
