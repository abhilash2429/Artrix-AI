# Artrix AI — Local Testing Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Docker Desktop | Any recent | `docker --version` |
| Python | 3.11+ | `python --version` |
| Node.js | 18+ | `node --version` |
| Gemini API Key | Free | https://aistudio.google.com/apikey |
| Cohere API Key | Free trial | https://dashboard.cohere.com/api-keys |

---

## Step 1 — Start Infrastructure

Open a terminal at the project root:

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\infra"
docker-compose up postgres redis qdrant -d
```

Verify all three are running:

```powershell
docker-compose ps
```

Expected: `postgres`, `redis`, `qdrant` all show status `running`.

**Ports used:**
- PostgreSQL: 5432
- Redis: 6379
- Qdrant: 6333, 6334

---

## Step 2 — Create .env File

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI"
Copy-Item .env.example .env
```

Open `.env` in your editor and fill in:

```env
GEMINI_API_KEY=your_gemini_api_key_here
COHERE_API_KEY=your_cohere_api_key_here
JWT_SECRET_KEY=replace-with-any-random-string-at-least-32-chars-long
POSTGRES_URL=postgresql+asyncpg://user:password@localhost:5432/agentdb
REDIS_URL=redis://localhost:6379/0
QDRANT_HOST=localhost
QDRANT_PORT=6333
APP_ENV=development
LOG_LEVEL=INFO
```

---

## Step 3 — Activate Backend Virtual Environment

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\backend"
.\.venv\Scripts\Activate.ps1
```

You should see `(.venv)` in your terminal prompt. All `python`, `pip`, `alembic`,
`uvicorn` commands below assume the venv is active.

---

## Step 4 — Run Database Migrations

```powershell
alembic upgrade head
```

Expected output: `INFO [alembic.runtime.migration] Running upgrade -> 001, initial schema`

This creates 5 tables: `tenants`, `sessions`, `messages`, `billing_events`, `knowledge_documents`.

---

## Step 5 — Create a Test Tenant

### 5a. Generate an API key

```powershell
python -c "from app.core.security import generate_api_key; raw, hashed = generate_api_key(); print(f'API_KEY={raw}'); print(f'HASH={hashed}')"
```

**Save both values.** You'll need:
- `API_KEY` → for all HTTP requests and the frontend `.env.local`
- `HASH` → for the database insert below

### 5b. Insert the tenant into Postgres

Replace `YOUR_HASH_HERE` with the HASH value from step 5a:

```powershell
docker exec -it infra-postgres-1 psql -U user -d agentdb -c "INSERT INTO tenants (name, api_key_hash, vertical, config, domain_whitelist, is_active) VALUES ('StyleCart Demo', 'YOUR_HASH_HERE', 'ecommerce', '{\"persona_name\": \"Aria\", \"persona_description\": \"Friendly support agent for StyleCart e-commerce\", \"escalation_threshold\": 0.55, \"auto_resolve_threshold\": 0.80, \"max_turns_before_escalation\": 10, \"allowed_topics\": [\"orders\", \"returns\", \"refunds\", \"delivery\", \"products\"]}', ARRAY['http://localhost:3000'], true);"
```

> **Note:** If the container name is different, check with `docker ps` and use the actual postgres container name.

Verify it was inserted:

```powershell
docker exec -it infra-postgres-1 psql -U user -d agentdb -c "SELECT id, name, vertical, is_active FROM tenants;"
```

---

## Step 6 — Start the Backend API

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Verify it's running

Open in browser: http://localhost:8000/v1/health

Expected response:
```json
{"status": "ok", "version": "1.0.0"}
```

Swagger docs: http://localhost:8000/docs

---

## Step 7 — Test the API with curl

Replace `YOUR_API_KEY` with the API_KEY from Step 5a in all commands below.

### 7a. Start a session

```powershell
curl -X POST http://localhost:8000/v1/session/start `
  -H "Content-Type: application/json" `
  -H "X-API-Key: YOUR_API_KEY" `
  -d "{}"
```

Response:
```json
{
  "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "created_at": "2026-02-28T..."
}
```

**Copy the `session_id`.**

### 7b. Send a chat message

Replace `SESSION_ID` with the value from 7a:

```powershell
curl -X POST http://localhost:8000/v1/chat/message `
  -H "Content-Type: application/json" `
  -H "X-API-Key: YOUR_API_KEY" `
  -d "{\"session_id\": \"SESSION_ID\", \"message\": \"What is your return policy?\", \"stream\": false}"
```

Response:
```json
{
  "message_id": "...",
  "response": "...",
  "confidence": 0.72,
  "sources": [],
  "escalation_required": false,
  "escalation_reason": null,
  "latency_ms": 1200
}
```

### 7c. End the session

```powershell
curl -X POST http://localhost:8000/v1/session/SESSION_ID/end `
  -H "Content-Type: application/json" `
  -H "X-API-Key: YOUR_API_KEY"
```

### 7d. Update tenant config

```powershell
curl -X PUT http://localhost:8000/v1/config `
  -H "Content-Type: application/json" `
  -H "X-API-Key: YOUR_API_KEY" `
  -d "{\"persona_name\": \"Medi\", \"persona_description\": \"Healthcare support agent\"}"
```

---

## Step 8 — Start the Frontend

Open a **new terminal** (keep the backend running):

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\frontend"
Copy-Item .env.local.example .env.local
```

Edit `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_DEMO_API_KEY=YOUR_API_KEY
```

Then start the dev server:

```powershell
npm run dev
```

### Verify

| Page | URL |
|------|-----|
| Homepage | http://localhost:3000 |
| Demo (auto-redirect) | http://localhost:3000/demo |
| E-commerce demo | http://localhost:3000/demo/ecommerce |
| Healthcare demo | http://localhost:3000/demo/healthcare |
| BFSI demo | http://localhost:3000/demo/bfsi |

### What to test on the demo page

1. Type a message and press Enter — should get a response from Gemini
2. Check the right panel shows confidence score, intent type, and latency
3. Switch verticals using the pills at the top — session resets automatically
4. Click a suggested query chip — it fills the input (doesn't auto-send)
5. If the agent escalates, an amber banner appears and input is disabled

---

## Step 9 — (Optional) Ingest a Document for RAG

Create a test FAQ file (e.g., `faq.txt` or `faq.pdf`) then:

```powershell
curl -X POST http://localhost:8000/v1/knowledge/ingest `
  -H "X-API-Key: YOUR_API_KEY" `
  -F "file=@C:\path\to\faq.pdf" `
  -F "document_type=faq"
```

After ingestion, domain queries will retrieve chunks from the knowledge base
and return them in the `sources` field of the chat response.

---

## Step 10 — Run Backend Tests

```powershell
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\backend"
python -m pytest tests/ -x -v --tb=short
```

For coverage:

```powershell
python -m pytest tests/ --cov=app/services --cov-report=term-missing
```

---

## Quick Reference

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| Frontend | http://localhost:3000 |
| E-commerce Demo | http://localhost:3000/demo/ecommerce |
| Healthcare Demo | http://localhost:3000/demo/healthcare |
| BFSI Demo | http://localhost:3000/demo/bfsi |
| Qdrant Dashboard | http://localhost:6333/dashboard |

## Stopping Everything

```powershell
# Stop frontend: Ctrl+C in the frontend terminal
# Stop backend: Ctrl+C in the backend terminal
# Stop infrastructure:
cd "C:\Users\abhii\Desktop\Projects\Artrix AI\infra"
docker-compose down
```

To also delete all data (fresh start):

```powershell
docker-compose down -v
```
