# Artrix AI

Multi-tenant AI agent platform for Indian enterprise customer support.

## Structure

```
backend/     → Python FastAPI core API (chat agents, RAG, billing)
frontend/    → Next.js 14 company site + live demo
widget/      → Embeddable chat widget (vanilla JS)
channels/    → Future channel adapters
  voice/     → Phase 2: Voice agents (STT/TTS gateway)
  whatsapp/  → Phase 3: WhatsApp Business API adapter
  sales/     → Phase 4: Sales automation
infra/       → Docker Compose + deployment configs
docs/        → Specs and documentation
```

## Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env  # fill in API keys
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

### Full Stack (Docker)
```bash
cd infra
docker-compose up
```

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, LangChain, Gemini 1.5 Flash, Qdrant, PostgreSQL, Redis
- **Frontend:** Next.js 14, TypeScript, Tailwind CSS, Framer Motion
- **Widget:** Vanilla JS, no build step
