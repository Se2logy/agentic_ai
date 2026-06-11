# Production Configuration Guide — Guest Check-In System

This document covers what must change when moving from development to production.

## Critical Configuration Changes

### 1. Environment Variables (.env)

Copy `.env.example` to `.env` and update ALL values for production:

| Variable | Development Default | Production Action |
|----------|-------------------|-------------------|
| `DATABASE_URL` | `mysql+pymysql://guestcheckin:guestcheckin@localhost:3306/guestcheckin` | **Change:** Use strong database credentials, point to production MySQL host |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | **Change:** Point to production Ollama server or GPU-enabled host |
| `OLLAMA_MODEL` | `llama3.1:8b` | Review: Ensure the model is suitable for your production hardware |
| `SMTP_HOST` | `mailhog` | **Change:** Use your real SMTP relay (e.g., SendGrid, Amazon SES, Mailgun) |
| `SMTP_PORT` | `1025` | **Change:** Use port 587 (TLS) or 465 (SSL) for production SMTP |
| `SMTP_USER` | *(empty)* | **Change:** Set your SMTP authentication username |
| `SMTP_PASS` | *(empty)* | **Change:** Set your SMTP authentication password |
| `SMTP_FROM` | `checkin@guestapp.local` | **Change:** Use your verified sender domain |
| `UPLOAD_DIR` | `/app/uploads` | Review: Ensure this is a persistent volume in production |
| `LINK_SECRET` | `change-me-in-production` | **⚠️ MANDATORY:** Generate a strong random string (32+ chars). `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LINK_EXPIRY_HOURS` | `1` | Review: Adjust based on guest flow (1-4 hours typical) |
| `API_KEY_HEADER` | `X-API-Key` | Keep: Standard header name, no change needed |
| `RATE_LIMIT` | `60/minute` | Review: Adjust based on expected traffic |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8000"]` | **Change:** Set to your production frontend domain(s) only |
| `SESSION_TOKEN_EXPIRY_HOURS` | `24` | Review: 24h is typical for check-in; adjust if needed |

### 2. Database Configuration

The engine is configured with production-safe pool settings:

```python
# app/database.py
pool_size=20        # Permanent connections in the pool
max_overflow=30     # Additional connections beyond pool_size
pool_timeout=30     # Seconds to wait for a connection
pool_pre_ping=True  # Verify connections before use
```

**For production MySQL:**
- Use a managed MySQL service (RDS, Cloud SQL, etc.)
- Enable SSL/TLS for the connection
- Set up read replicas if needed
- Configure `DATABASE_URL` with the production host:
  ```
  mysql+pymysql://produser:STRONG_PASSWORD@prod-db-host:3306/guestcheckin
  ```
- The async driver (`aiomysql`) is auto-substituted at runtime

### 3. Security Checklist

- [ ] **LINK_SECRET** — Changed from default. Use a cryptographically random string.
- [ ] **SMTP credentials** — Real SMTP service configured, not MailHog.
- [ ] **CORS_ORIGINS** — Restricted to production frontend domains only.
- [ ] **API keys** — Generate new production API keys (not `test-key-1`/`test-key-2`).
- [ ] **Session tokens** — Token expiry is 24h. Verify this meets your security requirements.
- [ ] **Upload directory** — Persistent volume mounted, not ephemeral container storage.
- [ ] **HTTPS** — Terminate TLS at the load balancer or reverse proxy level.
- [ ] **Ollama** — Not exposed to the internet; accessible only from the app container.

### 4. Docker Compose Production Overrides

Create `docker-compose.prod.yml`:

```yaml
services:
  app:
    environment:
      - DATABASE_URL=mysql+pymysql://produser:${DB_PASSWORD}@prod-db:3306/guestcheckin
      - LINK_SECRET=${LINK_SECRET}
      - SMTP_HOST=smtp.sendgrid.net
      - SMTP_PORT=587
      - SMTP_USER=apikey
      - SMTP_PASS=${SMTP_PASSWORD}
    volumes:
      - uploads:/app/uploads  # Persistent upload storage

volumes:
  uploads:
    driver: local
```

Deploy with:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 5. Reverse Proxy (nginx recommended)

```nginx
server {
    listen 443 ssl http2;
    server_name checkin.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/checkin.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/checkin.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 6. Monitoring

- **Health endpoint:** `GET /docs` returns 200 if the app is running
- **MailHog:** Remove from production compose; use real SMTP with delivery tracking
- **Logs:** `docker compose logs -f app` for application logs
- **Database:** Monitor MySQL connections against `pool_size` + `max_overflow` limits

### 7. Backup & Recovery

- **Database:** Set up automated MySQL backups (mysqldump or managed service snapshots)
- **Uploads:** Ensure the uploads volume is backed up
- **API keys:** Stored as SHA-256 hashes — cannot be recovered. Rotate by creating new keys.

---

## File Reference

| Configuration | File | Notes |
|--------------|------|-------|
| Environment variables | `.env` | All runtime settings |
| Database engine config | `app/database.py` | Pool size, overflow, timeout |
| Session token expiry | `app/auth/session_token.py` | Uses `settings.SESSION_TOKEN_EXPIRY_HOURS` |
| Link token expiry | `app/services/link_service.py` | Uses `settings.LINK_EXPIRY_HOURS` |
| API key auth | `app/auth/api_key.py` | SHA-256 hashed keys |
| CORS origins | `app/main.py` | `settings.CORS_ORIGINS` |
| Rate limiting | `app/main.py` | `settings.RATE_LIMIT` |
| SMTP config | `app/config.py` | All SMTP settings |
