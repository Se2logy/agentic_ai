# Guest Check-In API

Conversation-based guest check-in via channel messaging. An AI-powered state machine guides guests through onboarding (privacy policy, house rules, rental agreement, identity verification, ID upload, incidental protection) using natural conversation.

## Quick Start

### 1. Start the stack

```bash
docker-compose up -d
```

This starts three services:
- **app** — FastAPI server on http://localhost:8000
- **mysql** — MySQL 8.0 on localhost:3306
- **mailhog** — MailHog SMTP on localhost:1025, Web UI on http://localhost:8025

### 2. Pull the Ollama model

If you're running Ollama locally (outside Docker):

```bash
ollama pull llama3.1:8b
```

The app connects to Ollama at `http://localhost:11434` by default (or `http://host.docker.internal:11434` when running inside Docker).

### 3. Seed sample data

```bash
docker-compose exec app python -m seed.seed_reservations
docker-compose exec app python -m seed.seed_knowledge_base
docker-compose exec app python -m seed.seed_api_keys
```

### 4. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

API documentation: http://localhost:8000/docs

## Configuration

Copy `.env.example` to `.env` and adjust values:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://guestcheckin:guestcheckin@localhost:3306/guestcheckin` | SQLAlchemy database URL |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | LLM model name |
| `SMTP_HOST` | `localhost` | SMTP server hostname |
| `SMTP_PORT` | `1025` | SMTP server port |
| `SMTP_USER` | _(empty)_ | SMTP username |
| `SMTP_PASS` | _(empty)_ | SMTP password |
| `SMTP_FROM` | `checkin@guestapp.local` | Sender email address |
| `UPLOAD_DIR` | `/app/uploads` | Directory for ID document uploads |
| `LINK_SECRET` | `change-me-in-production` | Secret for signing secure upload/payment links |
| `LINK_EXPIRY_HOURS` | `1` | Hours before secure links expire |
| `API_KEY_HEADER` | `X-API-Key` | Header name for API key authentication |
| `RATE_LIMIT` | `60/minute` | Rate limit per API key |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8000"]` | Allowed CORS origins |

## Development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Running Tests

```bash
pytest tests/ -v --tb=short
```

## Architecture

See `docs/user_manual.html` for the full architecture diagram and process flow.
