"""RAG pipeline services.

Imports are intentionally NOT eagerly loaded here to avoid pulling in heavy
third-party SDKs (cohere, qdrant_client, rank_bm25) during test collection.
Use explicit imports:
    from app.services.rag.ingestion import IngestionService
    from app.services.rag.retrieval import RetrievalService
"""
