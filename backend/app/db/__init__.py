"""Database clients and connections.

Imports are intentionally NOT eagerly loaded here to avoid pulling in heavy
third-party SDKs (qdrant_client, redis) during test collection.
Use explicit imports: ``from app.db.qdrant import QdrantService``, etc.
"""
