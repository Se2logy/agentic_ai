# Testing Guide — Guest Check-In System

## Quick Start

### 1. Start the services

```bash
cd guest-checkin
docker compose up -d --build
```

Wait for all containers to be healthy (~30 seconds):
```bash
docker compose ps
```

All three services (app, mysql, mailhog) should show `Up` / `healthy`.

### 2. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

### 3. Seed the database

```bash
docker compose exec app python -m seed.seed_reservations
docker compose exec app python -m seed.seed_knowledge_base
docker compose exec app python -m seed.seed_api_keys
```

### 4. Verify the system

```bash
# Health check
curl http://localhost:8000/docs

# Test with API key
curl -H "X-API-Key: test-key-1" http://localhost:8000/api/v1/reservations/BK-2024-001
```

---

## Test Credentials

### API Keys (for X-API-Key header)

| Key | Name | Usage |
|-----|------|-------|
| `test-key-1` | Development Key 1 | Primary testing |
| `test-key-2` | Development Key 2 | Secondary testing |

### Sample Reservations

| Booking Reference | Guest | Property |
|-------------------|-------|----------|
| `BK-2024-001` | Alice Johnson | Seaside Cottage |
| `BK-2024-002` | Bob Smith | Mountain Lodge |
| `BK-2024-003` | Carol Davis | City Loft |

### Email (OTP verification)

- **MailHog Web UI:** http://localhost:8025
- All outgoing emails are captured by MailHog — no real email delivery
- OTP codes appear in the MailHog inbox

---

## Step-by-Step UI Testing

### Create a session

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "X-API-Key: test-key-1" \
  -H "Content-Type: application/json" \
  -d '{"booking_reference": "BK-2024-001"}'
```

Response includes `session_token` — save this for subsequent requests.

### Full check-in flow via API

```bash
TOKEN="<session_token from create>"
SESSION_ID="<session_id from create>"

# 1. Start check-in
curl -X POST "http://localhost:8000/api/v1/sessions/$SESSION_ID/messages" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "start"}'
# → Agent presents Privacy Policy text

# 2. Agree to privacy policy
curl -X POST "http://localhost:8000/api/v1/sessions/$SESSION_ID/messages" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "agree"}'
# → Agent presents House Rules text

# 3. Agree to house rules
curl -X POST "http://localhost:8000/api/v1/sessions/$SESSION_ID/messages" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "agree"}'
# → Agent presents Rental Agreement text

# 4. Agree to rental agreement
curl -X POST "http://localhost:8000/api/v1/sessions/$SESSION_ID/messages" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "agree"}'
# → Agent shows guest info for verification

# 5. Confirm personal information
curl -X POST "http://localhost:8000/api/v1/sessions/$SESSION_ID/messages" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "confirm"}'
# → Agent sends OTP, triggers email to guest

# 6. Get OTP from MailHog (http://localhost:8025), then verify
curl -X POST "http://localhost:8000/api/v1/otp/verify" \
  -H "X-API-Key: test-key-1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"otp_code": "123456"}'
# → Agent provides secure ID upload link

# 7. Open the ID upload link in a browser
# Upload a test image (any file)

# 8. Agent provides incidental protection selection link
# Open the link and select Damage Waiver ($49.00) or Security Hold ($250.00)

# 9. Check-in complete — agent provides arrival instructions
```

### WebSocket testing

```bash
# Connect to WebSocket
wscat -c "ws://localhost:8000/ws?token=$TOKEN"

# Send messages in the same format as the REST API
> {"content": "start"}
> {"content": "agree"}
```

### Chat widget testing

Open `http://localhost:8000/static/chat-widget.html` in a browser, or embed the widget:

```html
<script src="http://localhost:8000/static/chat-widget.js"></script>
<script>
  GuestCheckInWidget.init({
    sessionId: '<session_id>',
    token: '<session_token>',
    wsUrl: 'ws://localhost:8000/ws',
    apiUrl: 'http://localhost:8000'
  });
</script>
```

---

## Running the Automated Test Suite

### Unit tests

```bash
docker compose exec app python -m pytest tests/unit/ -v
```

### Integration tests

```bash
docker compose exec app python -m pytest tests/integration/ -v
```

### Full suite

```bash
docker compose exec app python -m pytest tests/ -v --tb=short
```

### Run a specific test

```bash
docker compose exec app python -m pytest tests/unit/test_audit_api.py -v
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| `MissingGreenlet` error | Ensure `expire_on_commit=False` in database.py (already set). The `await db.refresh(obj)` pattern before `model_validate` prevents this. |
| 401 Unauthorized | Check the `X-API-Key` header — use `test-key-1` or `test-key-2` |
| OTP not received | Check MailHog at http://localhost:8025 — emails are captured, not delivered |
| Session not found | Sessions expire after 24 hours. Create a new session with `POST /api/v1/sessions`. |
| WebSocket disconnects | Reconnect with the same token. Check that the session hasn't expired. |
