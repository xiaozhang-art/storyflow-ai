"""Session Manager - Creates, binds, and manages agent sessions."""
from __future__ import annotations
import logging
import uuid
from typing import Optional
from runtime.session.models import Session, SessionPair
from runtime.mcp.protocol import SESSION_ACTIVE, SESSION_IDLE, SESSION_SUSPENDED, SESSION_EXPIRED

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages agent sessions including creation, pairing, and lifecycle.
    
    Key responsibilities:
    - Auto-create sessions on first agent communication
    - Bidirectional session pairing (A <-> B)
    - Session state persistence
    - Session restore for crash recovery
    """
    
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._pairs: dict[str, SessionPair] = {}
        # Index: (agent_id, conversation_id) -> session_id
        self._agent_conv_index: dict[tuple[str, str], str] = {}
    
    def create_session(
        self,
        agent_id: str,
        conversation_id: str,
    ) -> Session:
        """Create a new session for an agent in a conversation."""
        session_id = uuid.uuid4().hex[:16]
        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
        self._sessions[session_id] = session
        self._agent_conv_index[(agent_id, conversation_id)] = session_id
        logger.info("Session created: %s (agent=%s, conv=%s)", session_id, agent_id, conversation_id)
        return session
    
    def get_or_create_session(
        self,
        agent_id: str,
        conversation_id: str,
    ) -> Session:
        """Get existing session or create a new one."""
        existing = self.find_session(agent_id, conversation_id)
        if existing:
            return existing
        return self.create_session(agent_id, conversation_id)
    
    def find_session(self, agent_id: str, conversation_id: str) -> Optional[Session]:
        """Find a session by agent and conversation."""
        session_id = self._agent_conv_index.get((agent_id, conversation_id))
        if session_id:
            return self._sessions.get(session_id)
        return None
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def pair_sessions(
        self,
        session_a: str,
        target_agent_id: str,
        conversation_id: str,
    ) -> Session:
        """Create a bidirectional session pair.
        
        If A(Sa) wants to talk to B, and B has no session:
        1. Create Sb for B
        2. Bind Sa <-> Sb
        """
        session_a_obj = self._sessions.get(session_a)
        if not session_a_obj:
            raise ValueError(f"Source session not found: {session_a}")
        
        # Check if pair already exists
        existing_pair = self._find_pair(session_a)
        if existing_pair:
            partner_id = existing_pair.get_partner(session_a)
            if partner_id:
                return self._sessions[partner_id]
        
        # Create session for target agent
        session_b = self.create_session(target_agent_id, conversation_id)
        
        # Create bidirectional binding
        pair = SessionPair(
            session_a=session_a,
            session_b=session_b.session_id,
            conversation_id=conversation_id,
        )
        pair_key = f"{min(session_a, session_b.session_id)}:{max(session_a, session_b.session_id)}"
        self._pairs[pair_key] = pair
        
        # Update sessions with partner refs
        session_a_obj.partner_session_id = session_b.session_id
        session_b.partner_session_id = session_a
        
        logger.info(
            "Session pair created: %s <-> %s (conv=%s)",
            session_a, session_b.session_id, conversation_id,
        )
        return session_b
    
    def resolve_target_session(self, source_session_id: str) -> Optional[str]:
        """Resolve the target session for a source session via pairing."""
        pair = self._find_pair(source_session_id)
        if pair:
            return pair.get_partner(source_session_id)
        return None
    
    def _find_pair(self, session_id: str) -> Optional[SessionPair]:
        """Find a pair containing the given session."""
        for pair in self._pairs.values():
            if session_id in (pair.session_a, pair.session_b):
                return pair
        return None
    
    def update_session_state(self, session_id: str, state: dict):
        """Update a session's state."""
        session = self._sessions.get(session_id)
        if session:
            session.state.update(state)
            session.touch()
    
    def set_session_status(self, session_id: str, status: str):
        """Set a session's status."""
        session = self._sessions.get(session_id)
        if session:
            session.status = status
            session.touch()
    
    def get_session_state(self, session_id: str) -> dict:
        """Get a session's state."""
        session = self._sessions.get(session_id)
        return session.state if session else {}
    
    async def restore_session(self, session_id: str) -> Optional[Session]:
        """Restore a session (placeholder for future DB persistence)."""
        session = self._sessions.get(session_id)
        if session:
            session.status = SESSION_ACTIVE
            session.touch()
            logger.info("Session restored: %s", session_id)
        return session
    
    def cleanup_expired(self, max_idle_seconds: int = 86400):
        """Clean up sessions idle for too long."""
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        expired = []
        for sid, session in self._sessions.items():
            try:
                last = datetime.fromisoformat(session.last_active)
                if (now - last) > timedelta(seconds=max_idle_seconds):
                    expired.append(sid)
            except (ValueError, TypeError):
                expired.append(sid)
        
        for sid in expired:
            self._sessions.pop(sid, None)
            self._agent_conv_index = {
                k: v for k, v in self._agent_conv_index.items() if v != sid
            }
        
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
    
    def get_stats(self) -> dict:
        return {
            "total_sessions": len(self._sessions),
            "total_pairs": len(self._pairs),
            "active_sessions": sum(1 for s in self._sessions.values() if s.status == SESSION_ACTIVE),
        }