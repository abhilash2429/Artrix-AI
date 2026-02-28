# AGENTS.md — Chat Agent System (Phase 1)
## AI Coding Agent Specification Document

> This document is the single source of truth for building the Phase 1 Chat Agent backend and demo frontend.
> Read this entire file before writing any code. Do not deviate from the architecture, stack, or conventions defined here.
> Future phases (Voice, WhatsApp, Sales Automation) will be separate agents.md files that extend this one.

---

## 1. PROJECT OVERVIEW

**Product:** Multi-tenant AI chat agent backend providing customer support automation for Indian enterprises.

**Phase Scope:** Chat agents only. No voice. No WhatsApp. No sales automation.

**Core Principle:** The backend API is the product. The widget and demo frontend are thin clients consuming the same API. Every capability must be API-first.

**Target Verticals (Phase 1):** E-commerce / D2C, Healthcare / Clinics, BFSI (Banking / Insurance / NBFC)

**Automation Target:** 60–75% of inbound support queries resolved without human intervention. Remaining 25–40% escalated cleanly to human agents with full context.

**Language:** English only in Phase 1. The architecture must support Indic language addition (via translation middleware) without modifying agent core logic. See Section 9.

---

## 2. TECH STACK — NON-NEGOTIABLE

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | Strict type hints everywhere |
| API Framework | FastAPI | Async throughout. Auto-generated OpenAPI docs required. |
| Agent Framework | LangChain (pin to 0.2.x) | Do not upgrade mid-build. Pin in requirements.txt |
| LLM | Google Gemini 1.5 Flash | Via `google-generativeai` SDK. Abstracted behind interface. |
| Embeddings | `text-embedding-004` (Google) | English-optimized. Do not switch to multilingual. |
| Vector DB | Qdrant | Self-hosted via Docker. GCP India region in production. |
| Relational DB | PostgreSQL 15 | Via `asyncpg` + `SQLAlchemy 2.0` async |
| Cache / Session | Redis 7 | Session state, rate limiting, short-term memory |
| Document Parsing | `unstructured[pdf,docx]` | Structure-aware parsing. Not PyPDF2. |
| Reranking | Cohere Rerank API | `cohere` Python SDK |
| Auth | API key (tenants) + JWT (frontend) | Keys stored hashed in Postgres |
| Containerization | Docker + Docker Compose | All services must run via `docker-compose up` |
| Environment Config | `pydantic-settings` + `.env` | No hardcoded secrets anywhere |

---

## 3. REPOSITORY STRUCTURE

```
/
├── app/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── api/
│   │   ├── v1/
│   │   │   ├── chat.py          # Chat message endpoints
│   │   │   ├── session.py       # Session management endpoints
│   │   │   ├── knowledge.py     # Document ingestion endpoints
│   │   │   ├── config.py        # Tenant config endpoints
│   │   │   └── health.py        # Health check
│   │   └── deps.py              # Shared FastAPI dependencies (auth, db)
│   ├── core/
│   │   ├── config.py            # Pydantic settings
│   │   ├── security.py          # API key hashing, JWT utils
│   │   └── exceptions.py        # Custom exception classes
│   ├── db/
│   │   ├── postgres.py          # Async SQLAlchemy engine + session
│   │   ├── redis.py             # Redis client
│   │   └── qdrant.py            # Qdrant client
│   ├── models/
│   │   ├── tenant.py            # Tenant ORM model
│   │   ├── session.py           # Conversation session ORM model
│   │   ├── message.py           # Message ORM model
│   │   └── billing.py           # Billing event ORM model
│   ├── schemas/
│   │   ├── chat.py              # Pydantic request/response schemas
│   │   ├── session.py
│   │   ├── knowledge.py
│   │   └── config.py
│   ├── services/
│   │   ├── llm/
│   │   │   ├── base.py          # Abstract LLMProvider interface
│   │   │   └── gemini.py        # Gemini implementation of LLMProvider
│   │   ├── embeddings/
│   │   │   ├── base.py          # Abstract EmbeddingProvider interface
│   │   │   └── google.py        # Google text-embedding-004 implementation
│   │   ├── rag/
│   │   │   ├── ingestion.py     # Document parsing, chunking, metadata gen
│   │   │   ├── retrieval.py     # Hybrid search + reranking
│   │   │   └── validation.py    # Post-retrieval + post-generation validation
│   │   ├── agent/
│   │   │   ├── core.py          # LangChain agent definition
│   │   │   ├── intent_router.py # Intent classification — runs before any tool call
│   │   │   ├── tools.py         # Agent tools (RAG, escalation, webhook lookup)
│   │   │   ├── memory.py        # Conversation memory management
│   │   │   └── escalation.py    # Escalation trigger logic
│   │   ├── language/
│   │   │   └── middleware.py    # Language detection + translation passthrough (Phase 1: passthrough only)
│   │   └── billing.py           # Conversation metering service
├── ingestion/
│   └── pipeline.py              # Standalone ingestion runner (CLI-invokable)
├── widget/
│   ├── index.html               # Embeddable chat widget (vanilla JS)
│   ├── widget.js                # Widget core logic
│   └── widget.css               # Widget styles
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt             # Pinned versions
├── .env.example
└── alembic/                     # DB migrations
```

---

## 4. DATABASE SCHEMA

### Table: `tenants`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
name            TEXT NOT NULL
api_key_hash    TEXT NOT NULL UNIQUE        -- SHA-256 hash of raw key
domain_whitelist TEXT[]                     -- allowed origins for widget embed
config          JSONB NOT NULL DEFAULT '{}'  -- agent persona, thresholds, escalation webhook
vertical        TEXT NOT NULL               -- 'ecommerce' | 'healthcare' | 'bfsi'
created_at      TIMESTAMPTZ DEFAULT now()
is_active       BOOLEAN DEFAULT true
```

### Table: `sessions`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(id)
external_user_id TEXT                       -- enterprise's own user identifier (optional)
started_at      TIMESTAMPTZ DEFAULT now()
ended_at        TIMESTAMPTZ                 -- null = active
status          TEXT DEFAULT 'active'       -- 'active' | 'resolved' | 'escalated'
escalation_reason TEXT
metadata        JSONB DEFAULT '{}'
```

### Table: `messages`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
session_id      UUID REFERENCES sessions(id)
tenant_id       UUID REFERENCES tenants(id)
role            TEXT NOT NULL               -- 'user' | 'assistant' | 'system'
content         TEXT NOT NULL
intent_type     TEXT                        -- 'conversational' | 'domain_query' | 'out_of_scope'
source_chunks   JSONB                       -- chunk IDs used for this response. NULL for conversational turns.
confidence_score FLOAT                      -- retrieval confidence 0.0–1.0. NULL for conversational turns.
escalation_flag BOOLEAN DEFAULT false
input_tokens    INT
output_tokens   INT
latency_ms      INT
created_at      TIMESTAMPTZ DEFAULT now()
```

### Table: `billing_events`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(id)
session_id      UUID REFERENCES sessions(id)
event_type      TEXT NOT NULL               -- 'session_start' | 'session_end' | 'escalation'
total_input_tokens  INT DEFAULT 0
total_output_tokens INT DEFAULT 0
total_messages  INT DEFAULT 0
billed_at       TIMESTAMPTZ DEFAULT now()
```

### Table: `knowledge_documents`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(id)
filename        TEXT NOT NULL
file_type       TEXT NOT NULL               -- 'pdf' | 'docx' | 'html' | 'txt' | 'csv'
version         INT DEFAULT 1
is_active       BOOLEAN DEFAULT true        -- soft delete; only latest active version is retrieved
ingested_at     TIMESTAMPTZ DEFAULT now()
chunk_count     INT
status          TEXT DEFAULT 'processing'   -- 'processing' | 'ready' | 'failed'
error_message   TEXT
```

---

## 5. API SPECIFICATION

All routes are prefixed `/v1`. All requests require `X-API-Key` header except `/v1/health`.

### 5.1 Health
```
GET /v1/health
Response 200: { "status": "ok", "version": "1.0.0" }
```

### 5.2 Session Management
```
POST /v1/session/start
Headers: X-API-Key
Body: { "external_user_id": "string (optional)" }
Response 200: { "session_id": "uuid", "created_at": "iso8601" }

POST /v1/session/{session_id}/end
Headers: X-API-Key
Response 200: { "session_id": "uuid", "status": "resolved", "summary": { ... } }

GET /v1/session/{session_id}/transcript
Headers: X-API-Key
Response 200: { "session_id": "uuid", "messages": [ { "role": ..., "content": ..., "created_at": ... } ] }
```

### 5.3 Chat
```
POST /v1/chat/message
Headers: X-API-Key
Body:
{
  "session_id": "uuid",
  "message": "string",
  "stream": false          -- streaming via SSE if true
}
Response 200:
{
  "message_id": "uuid",
  "response": "string",
  "confidence": 0.87,
  "sources": [ { "chunk_id": "...", "document": "...", "section": "..." } ],
  "escalation_required": false,
  "escalation_reason": null,
  "latency_ms": 420
}

GET /v1/chat/message/stream
-- Server-Sent Events endpoint for streaming responses
-- Same auth and session requirements
-- Emits: data: { "delta": "...", "done": false }
-- Final event: data: { "done": true, "metadata": { ... } }
```

### 5.4 Knowledge Ingestion
```
POST /v1/knowledge/ingest
Headers: X-API-Key
Body: multipart/form-data
  file: <binary>
  document_type: "faq" | "policy" | "product_catalog" | "sop"
Response 202:
{
  "document_id": "uuid",
  "status": "processing",
  "message": "Ingestion started. Poll /v1/knowledge/{document_id}/status"
}

GET /v1/knowledge/{document_id}/status
Headers: X-API-Key
Response 200:
{
  "document_id": "uuid",
  "status": "ready" | "processing" | "failed",
  "chunk_count": 47,
  "error_message": null
}

GET /v1/knowledge/list
Headers: X-API-Key
Response 200: { "documents": [ { "id", "filename", "version", "status", "ingested_at" } ] }

DELETE /v1/knowledge/{document_id}
Headers: X-API-Key
-- Soft delete. Sets is_active = false. Does NOT delete Qdrant vectors immediately.
-- Qdrant cleanup runs async via background task.
Response 200: { "deleted": true }
```

### 5.5 Tenant Configuration
```
PUT /v1/config
Headers: X-API-Key
Body:
{
  "persona_name": "Aria",
  "persona_description": "Friendly support agent for MediCare Clinics",
  "escalation_webhook_url": "https://enterprise.com/webhooks/escalation",
  "escalation_threshold": 0.55,        -- retrieval confidence below this = escalate
  "auto_resolve_threshold": 0.80,      -- above this = answer autonomously
  "max_turns_before_escalation": 10,   -- escalate if unresolved after N turns
  "allowed_topics": ["appointments", "billing", "reports"],   -- optional scope limiting
  "blocked_topics": ["competitor_comparison"]
}
Response 200: { "updated": true }
```

---

## 6. INGESTION PIPELINE — DETAILED IMPLEMENTATION

### 6.1 Document Parsing
Use `unstructured` library. Do NOT use PyPDF2 or pdfplumber as primary parsers.

```python
from unstructured.partition.auto import partition

elements = partition(filename=filepath, strategy="hi_res")
# Elements are typed: Title, NarrativeText, Table, ListItem, etc.
# Preserve element type as metadata — do not flatten all to plain text
```

Tables must be converted to markdown format before chunking:
```python
# For Table elements: convert to markdown grid, not raw text extraction
# Raw text from tables loses column alignment and produces garbage retrieval
```

### 6.2 Chunking Rules
- Target chunk size: 400–500 tokens (measured via `tiktoken`, `cl100k_base` encoding)
- Overlap: 50 tokens between consecutive chunks from the same section
- Never split: mid-table, mid-list, mid-code-block
- Always keep: heading + its first paragraph in the same chunk
- Implementation: custom recursive splitter respecting element type boundaries. Do NOT use `CharacterTextSplitter` for production.

### 6.3 Metadata Per Chunk
Every chunk stored in Qdrant must carry this payload:

```json
{
  "chunk_id": "uuid",
  "document_id": "uuid",
  "tenant_id": "uuid",
  "filename": "return_policy_v3.pdf",
  "document_version": 3,
  "is_latest_version": true,
  "section_heading": "Return Eligibility Criteria",
  "element_type": "NarrativeText",
  "char_count": 412,
  "token_count": 98,
  "summary": "This chunk describes which products are eligible for return within 30 days...",
  "hypothetical_questions": [
    "What products can I return?",
    "How many days do I have to return an order?",
    "Are electronics eligible for return?"
  ],
  "ingested_at": "2024-01-15T10:30:00Z"
}
```

The `summary` and `hypothetical_questions` fields are generated via a secondary Gemini Flash call during ingestion. This is a background task — it must not block the ingestion response.

Prompt for hypothetical question generation:
```
Given this document chunk, generate exactly 3 questions that a customer support user might ask that this chunk directly answers. Return only a JSON array of 3 strings. No preamble.

Chunk:
{chunk_text}
```

### 6.4 Embedding
Embed three text variants per chunk and store all three vectors:
1. The raw chunk text
2. The LLM-generated summary
3. Concatenated hypothetical questions as a single string

At retrieval time, query all three collections and merge results. This significantly improves recall for colloquial queries.

---

## 7. RETRIEVAL PIPELINE — DETAILED IMPLEMENTATION

### 7.1 Hybrid Search
```python
# Step 1: Dense retrieval via Qdrant
dense_results = qdrant_client.search(
    collection_name=f"tenant_{tenant_id}",
    query_vector=embed(user_query),
    limit=20,
    query_filter=Filter(must=[
        FieldCondition(key="is_latest_version", match=MatchValue(value=True))
    ])
)

# Step 2: Sparse/keyword retrieval via BM25
# Use rank_bm25 library on the in-memory chunk corpus per tenant
# OR use Qdrant's sparse vector support (preferred if Qdrant version supports it)
sparse_results = bm25_search(corpus=tenant_corpus, query=user_query, top_k=20)

# Step 3: Merge and rerank
merged = reciprocal_rank_fusion(dense_results, sparse_results)
reranked = cohere_client.rerank(
    model="rerank-english-v3.0",
    query=user_query,
    documents=[r.payload["chunk_text"] for r in merged],
    top_n=8
)
```

### 7.2 Confidence Scoring
The confidence score returned to the client is derived from:
- Cohere rerank relevance score of the top result (primary signal)
- Number of retrieved chunks above a minimum relevance threshold (secondary signal)

```python
def compute_confidence(rerank_results) -> float:
    if not rerank_results:
        return 0.0
    top_score = rerank_results[0].relevance_score   # 0.0–1.0
    supporting_chunks = sum(1 for r in rerank_results if r.relevance_score > 0.4)
    # Weight top score heavily, supporting chunks as minor boost
    return min(1.0, top_score * 0.85 + (supporting_chunks / 10) * 0.15)
```

### 7.3 Escalation Decision
```python
THRESHOLDS = {
    "auto_resolve": 0.80,    # tenant-configurable via PUT /v1/config
    "low_confidence": 0.55,  # answer but flag for review
    "escalate": 0.55         # below this = do not attempt answer
}

def should_escalate(confidence: float, turn_count: int, max_turns: int) -> tuple[bool, str]:
    if confidence < THRESHOLDS["escalate"]:
        return True, "low_retrieval_confidence"
    if turn_count >= max_turns:
        return True, "max_turns_exceeded"
    return False, None
```

### 7.4 Escalation Webhook
When escalation is triggered, POST to the enterprise's configured webhook URL:

```json
{
  "event": "escalation",
  "session_id": "uuid",
  "tenant_id": "uuid",
  "external_user_id": "string or null",
  "escalation_reason": "low_retrieval_confidence",
  "transcript": [
    { "role": "user", "content": "...", "timestamp": "..." },
    { "role": "assistant", "content": "...", "timestamp": "..." }
  ],
  "last_user_message": "string",
  "escalated_at": "iso8601"
}
```

This POST must be non-blocking. Fire via background task. If webhook fails, log to `billing_events` table with `event_type = 'escalation_webhook_failed'` and retry up to 3 times with exponential backoff.

---

## 8. LANGCHAIN AGENT — CORE IMPLEMENTATION

### 8.1 Intent Router — Runs Before Any Tool Call

Every user message is classified before the agent does anything else. This is a single lightweight Gemini Flash call — no RAG, no rerank, no vector search.

**File:** `app/services/agent/intent_router.py`

```python
from enum import Enum
from app.services.llm.base import LLMProvider

class IntentType(str, Enum):
    CONVERSATIONAL = "conversational"
    DOMAIN_QUERY   = "domain_query"
    OUT_OF_SCOPE   = "out_of_scope"

INTENT_CLASSIFICATION_PROMPT = """
You are a router for a customer support agent in the {vertical} industry.
The agent handles these topics only: {allowed_topics}

Classify the user message into exactly one category:
- "conversational": greetings, thanks, acknowledgements, small talk, vague openers like "I need help", "okay", "can you assist me"
- "domain_query": a specific question requiring knowledge about products, policies, procedures, pricing, or real-time data
- "out_of_scope": asking about anything outside the agent's listed topics

User message: "{message}"

Reply with exactly one word. No explanation. No punctuation.
"""

class IntentRouter:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def classify(
        self,
        message: str,
        vertical: str,
        allowed_topics: list[str]
    ) -> IntentType:
        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            vertical=vertical,
            allowed_topics=", ".join(allowed_topics),
            message=message
        )
        result = await self.llm.generate(
            prompt=prompt,
            system_prompt="You are a precise classifier. Reply with one word only.",
            max_tokens=5
        )
        raw = result.strip().lower()
        try:
            return IntentType(raw)
        except ValueError:
            # If LLM returns unexpected output, default to domain_query
            # so retrieval runs rather than silently dropping a real question
            return IntentType.DOMAIN_QUERY
```

**Cost profile:** ~50 input tokens + 1 output token per turn. Negligible. Do not skip this step as an optimization — the latency savings on conversational turns (no Qdrant + Cohere calls) far outweigh this cost.

---

### 8.2 Agent Turn Flow — Updated

The agent core in `app/services/agent/core.py` must follow this exact decision tree on every user message:

```
User message arrives
        ↓
[IntentRouter.classify(message, vertical, allowed_topics)]
        ↓
   ┌────┴─────────────────────┐─────────────────────────┐
   ↓                          ↓                         ↓
CONVERSATIONAL           DOMAIN_QUERY              OUT_OF_SCOPE
   ↓                          ↓                         ↓
Respond directly         call knowledge_retrieval   Respond with
from system prompt       tool → confidence check    scope redirect
+ conversation memory.   → answer or escalate.      from system prompt.
No tools called.         Full RAG pipeline runs.    No tools called.
~300ms latency           ~900ms–1.5s latency        ~300ms latency
```

**CONVERSATIONAL behavior:**
- No tool calls
- Use `ConversationBufferWindowMemory` (last 10 turns) for context coherence
- Response generated directly from system prompt persona + chat history
- Example inputs: "hello", "thanks", "okay got it", "what can you help me with?", "I have an issue"
- `source_chunks` = NULL, `confidence_score` = NULL in messages table

**DOMAIN_QUERY behavior:**
- Call `knowledge_retrieval` tool
- Run full hybrid search + rerank + confidence scoring pipeline
- Apply escalation thresholds
- Populate `source_chunks` and `confidence_score` in messages table

**OUT_OF_SCOPE behavior:**
- No tool calls
- Do not escalate — this is a boundary condition, not a knowledge gap
- Respond using this template (persona-adapted):
  > "I can only assist with {allowed_topics} for {company_name}. Is there something I can help you with in those areas?"
- `source_chunks` = NULL, `confidence_score` = NULL, `escalation_flag` = false in messages table

---

### 8.3 Agent Tools

Use `create_react_agent` pattern. These tools are only invoked when `IntentRouter` returns `DOMAIN_QUERY`. They are never called for `CONVERSATIONAL` or `OUT_OF_SCOPE` intents.

**Tool 1: `knowledge_retrieval`**
- Input: user query string
- Action: runs hybrid search + rerank pipeline
- Returns: list of relevant chunks with metadata + computed confidence score
- Called only on `DOMAIN_QUERY` turns — not on every user turn

**Tool 2: `escalate_to_human`**
- Input: reason string
- Action: triggers escalation flow — fires webhook, marks session as 'escalated', returns escalation confirmation to user
- The agent must call this tool when: confidence is below threshold, user explicitly requests human
- Out-of-scope queries do NOT trigger this tool — they are handled by the `OUT_OF_SCOPE` branch in the intent router
- This tool ends the agent loop for that session

**Tool 3: `structured_data_lookup`**
- Input: lookup_type ('order_status' | 'appointment' | 'policy_number'), identifier string
- Action: calls the enterprise's configured data webhook to fetch live structured data
- Returns: structured JSON which the agent uses to augment its answer
- Only invoked when the agent detects the query requires real-time data (order tracking, appointment status, etc.)
- If enterprise has not configured a data webhook, this tool returns a "not configured" error and the agent falls back to knowledge base only

### 8.4 System Prompt Template
```
You are {persona_name}, a customer support agent for {company_name}.

Your role: {persona_description}

Rules you must follow without exception:
1. Answer only from the context provided by the knowledge_retrieval tool. Never invent information.
2. If the retrieved context does not contain enough information to answer confidently, call escalate_to_human immediately. Do not guess.
3. If the user asks about: {blocked_topics}, politely decline and offer to help with something else.
4. Keep responses concise: 2–4 sentences for simple questions, structured lists for multi-part answers.
5. Never mention that you are an AI unless directly asked.
6. If you are unsure, say so and escalate. A wrong answer is worse than an escalation.
7. Always cite which part of the knowledge base your answer comes from (document name + section).

Current date: {current_date}
Tenant vertical: {vertical}
```

### 8.5 Memory Configuration
```python
from langchain.memory import ConversationBufferWindowMemory

memory = ConversationBufferWindowMemory(
    k=10,                    # last 10 turns in context
    return_messages=True,
    memory_key="chat_history"
)
# Persist to Redis keyed by session_id
# On session load, hydrate memory from Redis
# On session end, persist final state to Postgres messages table
```

---

## 9. LANGUAGE MIDDLEWARE — PHASE 1 PASSTHROUGH

This layer exists now as a passthrough. It will be populated in Phase 3 (Indic language support).

```python
# app/services/language/middleware.py

class LanguageMiddleware:
    async def detect_language(self, text: str) -> str:
        """Returns ISO 639-1 language code. Phase 1: always returns 'en'"""
        return "en"

    async def translate_to_english(self, text: str, source_lang: str) -> str:
        """Phase 1: passthrough. Phase 3: Sarvam Translate API call."""
        return text

    async def translate_from_english(self, text: str, target_lang: str) -> str:
        """Phase 1: passthrough. Phase 3: Sarvam Translate API call."""
        return text
```

**DO NOT** skip building this class. Every user message MUST pass through `translate_to_english` before reaching the agent. Every agent response MUST pass through `translate_from_english` before being returned to the user. The Phase 1 logic is trivial — but the interface contract is mandatory.

When Sarvam AI integration is added in Phase 3, only the internals of these three methods change. The calling code in the API layer does not change.

---

## 10. LLM PROVIDER ABSTRACTION — MANDATORY PATTERN

```python
# app/services/llm/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str, max_tokens: int = 1000) -> str:
        pass

    @abstractmethod
    async def stream(self, prompt: str, system_prompt: str) -> AsyncIterator[str]:
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        pass
```

```python
# app/services/llm/gemini.py

import google.generativeai as genai
from .base import LLMProvider

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        # ...implement all abstract methods
```

The `GeminiProvider` is instantiated once via dependency injection in `app/api/deps.py`. It is never imported directly into business logic. Future switch to Claude or a fine-tuned model = new class implementing `LLMProvider`, one config line change.

---

## 11. BILLING METERING

Every conversation is billed as one unit from `session_start` to `session_end` or `escalation`.

```python
# app/services/billing.py

class BillingService:
    async def record_message(self, session_id, tenant_id, input_tokens, output_tokens):
        """Append to in-memory session counter in Redis."""
        pass

    async def close_session(self, session_id, tenant_id, event_type: str):
        """
        Flush session counters from Redis to billing_events table in Postgres.
        event_type: 'resolved' | 'escalated' | 'timeout'
        This is the billable event.
        """
        pass
```

Sessions that are idle for more than 30 minutes must be auto-closed via a background scheduled task (use APScheduler or FastAPI lifespan tasks). Idle sessions count as resolved for billing purposes.

---

## 12. EMBEDDABLE WIDGET

Single JS file. No framework. No build step required. Enterprises add one `<script>` tag.

```html
<script
  src="https://cdn.yourdomain.com/widget.js"
  data-api-key="ent_live_xxxx"
  data-persona="Aria"
  data-primary-color="#0066FF"
  data-position="bottom-right"
></script>
```

Widget responsibilities:
- Initialize session on first user message (POST /v1/session/start)
- Send messages (POST /v1/chat/message)
- Render agent responses with markdown support (use marked.js CDN)
- Show typing indicator during response fetch
- Show escalation state when `escalation_required: true` (display: "Connecting you to a human agent...")
- End session on widget close (POST /v1/session/{id}/end)
- Store session_id in sessionStorage (not localStorage — sessions are per-tab, not persistent)
- Respect `data-primary-color` for theming

Widget must work on any domain. CORS is handled at the API level using the tenant's `domain_whitelist` config.

---

## 13. ENVIRONMENT VARIABLES

```env
# .env.example

# LLM
GEMINI_API_KEY=

# Database
POSTGRES_URL=postgresql+asyncpg://user:password@localhost:5432/agentdb
REDIS_URL=redis://localhost:6379/0

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=                  # empty for local dev

# Cohere (reranking)
COHERE_API_KEY=

# Auth
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
API_KEY_PREFIX=ent_live_         # prefix for issued API keys

# App
APP_ENV=development              # development | production
LOG_LEVEL=INFO
MAX_SESSIONS_PER_TENANT=1000    # rate limit
IDLE_SESSION_TIMEOUT_MINUTES=30
```

---

## 14. DOCKER COMPOSE

```yaml
version: '3.9'
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, redis, qdrant]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: agentdb
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: [qdrantdata:/qdrant/storage]

volumes:
  pgdata:
  qdrantdata:
```

---

## 15. CODING STANDARDS

- All service methods must be `async`. No synchronous blocking calls in the request path.
- All database operations use SQLAlchemy 2.0 async session pattern.
- All external API calls (Gemini, Cohere, Sarvam in future) must have a 10-second timeout and be wrapped in try/except with explicit error logging.
- Log every agent turn with: tenant_id, session_id, latency_ms, confidence_score, escalation_flag, token counts. Use structured logging (JSON format via `structlog`).
- Never log raw user message content in production (`APP_ENV=production`). Log only message_id and token count.
- Every endpoint must return structured error responses:
  ```json
  { "error": { "code": "INVALID_SESSION", "message": "Session not found or expired" } }
  ```
- All Pydantic schemas must have `model_config = ConfigDict(from_attributes=True)`.
- Database migrations via Alembic only. Never `create_all()` in production.

---

## 16. TESTING REQUIREMENTS

- Unit tests for: intent classification (all three branches), chunking logic, confidence scoring, escalation decision, language middleware, billing metering
- Integration tests for: full ingestion pipeline with a sample PDF, full chat turn with mocked Gemini + Qdrant, escalation webhook firing
- Use `pytest` + `pytest-asyncio`
- Mock all external API calls in unit tests (`pytest-mock`)
- Minimum coverage target: 70% on `app/services/`

---

## 17. WHAT THIS SYSTEM DOES NOT DO (PHASE 1 SCOPE BOUNDARY)

The following are explicitly out of scope. Do not build these. They belong to later phases.

- Voice input or output (Phase 2)
- WhatsApp integration (Phase 3)
- Sales automation or outbound messaging (Phase 4)
- Live agent dashboard UI (future)
- Indic language translation (Phase 3 — middleware interface exists, implementation deferred)
- Fine-tuned models (post-seed)
- Multi-agent coordination (future — current agent is single-agent)
- Analytics dashboard for enterprises (future)
- Stripe billing integration (structure is built, Stripe SDK not integrated yet)

---

## 18. HANDOFF TO FUTURE PHASES

When Phase 1 is complete and Phase 2 (Voice Agents) begins, the following interfaces will be consumed:

- `POST /v1/chat/message` — Voice agent will call this same endpoint with STT-transcribed text
- `LanguageMiddleware` — Will be populated with Sarvam STT/TTS calls
- `LLMProvider` — Will remain unchanged
- `EscalationService` — Voice escalation will extend, not replace, this service
- All tenant config, billing, and session infrastructure carries forward unchanged

The voice agent is a new input/output layer on top of the same agent core. Do not architect Phase 1 in a way that assumes text-only at the core level.
