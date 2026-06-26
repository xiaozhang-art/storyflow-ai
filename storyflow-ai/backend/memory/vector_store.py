"""Qdrant vector store for story and character memory."""

import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from configs.settings import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """Wrapper around Qdrant for story memory operations."""

    def __init__(self, url: str | None = None, collection_name: str | None = None):
        self.url = url or settings.QDRANT_URL
        self.collection_name = collection_name or settings.QDRANT_COLLECTION
        self.client = QdrantClient(url=self.url)

    def init_collection(self, vector_size: int = 1024):
        """Create collection if it does not exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in existing:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {self.collection_name}")

    def store_memory(self, story_id: str, content: str, metadata: dict):
        """Store a story memory entry."""
        # Use a simple hash-based ID (in production, use real embeddings)
        import hashlib
        point_id = int(hashlib.md5(content.encode()).hexdigest()[:16], 16) % (2**63)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.0] * 1024,  # placeholder - use real embeddings
                    payload={
                        "story_id": story_id,
                        "content": content,
                        **metadata,
                    },
                )
            ],
        )

    def search_memory(self, query: str, limit: int = 5) -> list[dict]:
        """Search for relevant memories (placeholder implementation)."""
        results = self.client.scroll(
            collection_name=self.collection_name,
            limit=limit,
        )
        memories = []
        for point in results[0]:
            memories.append(point.payload)
        return memories

    def store_character(self, character: dict):
        """Store a character card."""
        import hashlib
        name = character.get("name", "unknown")
        point_id = int(hashlib.md5(f"char:{name}".encode()).hexdigest()[:16], 16) % (2**63)
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.0] * 1024,
                    payload={"type": "character", **character},
                )
            ],
        )
        logger.info(f"Stored character: {name}")

    def search_character(self, name: str) -> dict | None:
        """Search for a character by name (exact match in payload)."""
        from qdrant_client.models import FieldCondition, MatchValue, Filter
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="name", match=MatchValue(value=name))
                ]
            ),
            limit=1,
        )
        if results[0]:
            return results[0][0].payload
        return None


# Singleton instance
vector_store = VectorStore()