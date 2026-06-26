"""Memory Manager - Central manager for the 4-layer memory system."""
from __future__ import annotations
import logging
import time
import uuid
from typing import Any, Optional
from runtime.memory.models import MemoryEntry, MemoryQuery, MemoryType

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages the 4-layer memory hierarchy:
    
    1. Working Memory: Current step context (1 turn)
    2. Session Memory: Within-session facts (24h TTL)
    3. Conversation Memory: Story-level state (persistent)
    4. Long-term Memory: Cross-story knowledge (indefinite)
    
    Memory flow:
    - Agent Output -> Memory Extractor -> Embedding -> Store
    - Query -> Embedding -> Vector Search -> Rerank -> Inject into Prompt
    """
    
    # TTL in seconds
    TTL_WORKING = 300        # 5 minutes
    TTL_SESSION = 86400      # 24 hours
    TTL_CONVERSATION = 0     # Persistent
    TTL_LONG_TERM = 0        # Persistent
    
    def __init__(self, qdrant_client=None, embedder=None):
        self._store: dict[str, MemoryEntry] = {}
        self._qdrant = qdrant_client
        self._embedder = embedder
        self._collection_name = "story_memory"
    
    def _ttl_for_type(self, mem_type: MemoryType) -> float:
        """Get TTL in seconds for a memory type."""
        ttl_map = {
            MemoryType.WORKING: self.TTL_WORKING,
            MemoryType.SESSION: self.TTL_SESSION,
            MemoryType.CONVERSATION: self.TTL_CONVERSATION,
            MemoryType.LONG_TERM: self.TTL_LONG_TERM,
        }
        return ttl_map.get(mem_type, 0)
    
    async def store(self, entry: MemoryEntry):
        """Store a memory entry."""
        now = time.time()
        entry.created_at = now
        ttl = self._ttl_for_type(entry.type)
        entry.expires_at = now + ttl if ttl > 0 else 0
        
        if not entry.id:
            entry.id = uuid.uuid4().hex
        
        # In-memory store
        self._store[entry.id] = entry
        
        # Vector store (if available)
        if self._qdrant and entry.embedding:
            try:
                await self._upsert_to_qdrant(entry)
            except Exception as e:
                logger.warning("Qdrant upsert failed: %s", e)
        
        logger.debug("Memory stored: type=%s, entity=%s, text=%s[:50]",
                      entry.type.value, entry.entity, entry.text[:50])
    
    async def store_fact(
        self,
        text: str,
        memory_type: MemoryType = MemoryType.CONVERSATION,
        entity: str = "",
        conversation_id: str = "",
        session_id: str = "",
        agent_id: str = "",
        tags: list[str] | None = None,
        confidence: float = 1.0,
    ):
        """Convenience method to store a simple fact."""
        # Validate fact before storing (prevent hallucination pollution)
        if confidence < 0.7:
            logger.debug("Memory rejected (low confidence %.2f): %s", confidence, text)
            return
        
        entry = MemoryEntry(
            id=uuid.uuid4().hex,
            type=memory_type,
            text=text,
            entity=entity,
            conversation_id=conversation_id or None,
            session_id=session_id or None,
            agent_id=agent_id or None,
            confidence=confidence,
            tags=tags or [],
        )
        await self.store(entry)
    
    async def retrieve(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Retrieve memories matching a query."""
        now = time.time()
        results: list[MemoryEntry] = []
        
        for entry in self._store.values():
            # Check expiration
            if entry.expires_at > 0 and now > entry.expires_at:
                continue
            
            # Check type filter
            if entry.type not in query.memory_types:
                continue
            
            # Check confidence
            if entry.confidence < query.min_confidence:
                continue
            
            # Check scoping
            if query.conversation_id and entry.conversation_id and entry.conversation_id != query.conversation_id:
                continue
            if query.session_id and entry.session_id and entry.session_id != query.session_id:
                continue
            if query.agent_id and entry.agent_id and entry.agent_id != query.agent_id:
                continue
            
            # Check tags
            if query.tags:
                if not any(t in entry.tags for t in query.tags):
                    continue
            
            # Simple text matching (keyword-based, upgrade to vector search)
            if query.query:
                query_words = set(query.query.lower().split())
                entry_words = set(entry.text.lower().split())
                if not query_words & entry_words:
                    # Also check entity
                    if query.query.lower() not in entry.entity.lower():
                        continue
            
            results.append(entry)
        
        # Sort by confidence and recency
        results.sort(key=lambda e: (e.confidence, e.created_at), reverse=True)
        return results[:query.limit]
    
    async def load_for_agent(
        self,
        agent_id: str,
        conversation_id: str = "",
        query: str = "",
    ) -> str:
        """Load and format memories for injection into an agent's prompt."""
        memory_query = MemoryQuery(
            query=query,
            agent_id=agent_id,
            conversation_id=conversation_id or None,
            memory_types=[MemoryType.CONVERSATION, MemoryType.SESSION],
            limit=15,
        )
        
        memories = await self.retrieve(memory_query)
        
        if not memories:
            return ""
        
        lines = []
        for mem in memories:
            prefix = ""
            if mem.entity:
                prefix = f"[{mem.entity}] "
            lines.append(f"- {prefix}{mem.text}")
        
        return "\n".join(lines)
    
    async def extract_and_store(
        self,
        text: str,
        conversation_id: str = "",
        agent_id: str = "",
    ):
        """Extract structured facts from agent output and store them.
        
        This is a simple keyword-based extractor. Production systems
        should use an LLM-based extractor for better quality.
        """
        import re
        
        # Extract character mentions (simple pattern)
        # In production, use LLM-based extraction
        facts = []
        
        # Look for patterns like "X是Y" or "X有Z"
        patterns = [
            r"(\S+?)(?:是|为|有|叫|担任)(.{2,20})",
            r"(\S+?)(?:的外貌|的性格|的特征)(?:为|是|：)(.{2,30})",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for entity, description in matches:
                facts.append({
                    "text": f"{entity}{description}",
                    "entity": entity,
                    "type": MemoryType.CONVERSATION,
                })
        
        for fact in facts:
            await self.store_fact(
                text=fact["text"],
                memory_type=fact["type"],
                entity=fact["entity"],
                conversation_id=conversation_id,
                agent_id=agent_id,
                confidence=0.8,
            )
        
        if facts:
            logger.info("Extracted %d facts from agent output", len(facts))
    
    async def _upsert_to_qdrant(self, entry: MemoryEntry):
        """Upsert a memory entry to Qdrant vector store."""
        if not self._qdrant or not entry.embedding:
            return
        
        from qdrant_client.models import PointStruct
        point = PointStruct(
            id=entry.id,
            vector=entry.embedding,
            payload={
                "type": entry.type.value,
                "text": entry.text,
                "entity": entry.entity,
                "session_id": entry.session_id or "",
                "conversation_id": entry.conversation_id or "",
                "agent_id": entry.agent_id or "",
                "confidence": entry.confidence,
                "tags": entry.tags,
            },
        )
        await self._qdrant.upsert(
            collection_name=self._collection_name,
            points=[point],
        )
    
    async def search_qdrant(
        self,
        query_vector: list[float],
        limit: int = 10,
        conversation_id: str = "",
    ) -> list[MemoryEntry]:
        """Search Qdrant for similar memories using vector similarity."""
        if not self._qdrant:
            return []
        
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        query_filter = None
        if conversation_id:
            query_filter = Filter(
                must=[FieldCondition(key="conversation_id", match=MatchValue(value=conversation_id))]
            )
        
        try:
            results = await self._qdrant.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
            )
            
            entries = []
            for hit in results:
                payload = hit.payload or {}
                entry = MemoryEntry(
                    id=hit.id,
                    type=MemoryType(payload.get("type", "conversation")),
                    text=payload.get("text", ""),
                    entity=payload.get("entity", ""),
                    confidence=payload.get("confidence", 1.0) * hit.score,
                    tags=payload.get("tags", []),
                )
                entries.append(entry)
            return entries
        except Exception as e:
            logger.warning("Qdrant search failed: %s", e)
            return []
    
    def cleanup_expired(self):
        """Remove expired memories from the in-memory store."""
        now = time.time()
        expired = [
            mid for mid, entry in self._store.items()
            if entry.expires_at > 0 and now > entry.expires_at
        ]
        for mid in expired:
            del self._store[mid]
        if expired:
            logger.info("Cleaned up %d expired memories", len(expired))
    
    def get_stats(self) -> dict:
        type_counts = {}
        for entry in self._store.values():
            type_counts[entry.type.value] = type_counts.get(entry.type.value, 0) + 1
        return {
            "total_memories": len(self._store),
            "by_type": type_counts,
        }