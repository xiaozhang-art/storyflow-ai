"""Trace Runtime - Full execution tracing for AI pipelines.

Records every step's: prompt, tokens, cost, duration, status, retries, errors.
Provides a trace tree for visualization and cost analysis.

Usage:
    trace = TraceRuntime()
    
    # Auto-start a trace for a session
    trace.start_trace(session_id="abc123", metadata={"prompt": "..."})
    
    # Record a span for each agent call
    span = trace.start_span("image", parent_id=root_span_id)
    # ... agent executes ...
    trace.end_span(span.span_id, output_summary={"images": 7},
                    tokens_in=0, tokens_out=0, cost=0.15, status="completed")
    
    # Get full trace tree for frontend visualization
    tree = trace.get_trace("abc123")
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single execution span (like OpenTelemetry Span)."""
    span_id: str
    trace_id: str
    parent_id: str | None
    name: str                    # Agent/step name
    step: str = ""               # Pipeline step
    start_time: float = 0.0
    end_time: float | None = None
    duration_ms: float = 0.0
    status: str = "running"      # running | completed | failed | skipped
    input_summary: dict = field(default_factory=dict)
    output_summary: dict = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    model: str = ""
    error: str = ""
    retry_count: int = 0
    attempt: int = 1
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "step": self.step,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 1),
            "status": self.status,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": round(self.cost, 6),
            "model": self.model,
            "error": self.error,
            "retry_count": self.retry_count,
            "attempt": self.attempt,
            "metadata": self.metadata,
        }


@dataclass
class TraceTree:
    """A tree of spans representing a full pipeline execution."""
    trace_id: str
    root_span: Span | None = None
    spans: list[Span] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float | None = None

    @property
    def total_duration_ms(self) -> float:
        if self.root_span and self.root_span.end_time:
            return self.root_span.duration_ms
        return sum(s.duration_ms for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_in + s.tokens_out for s in self.spans)

    @property
    def total_cost(self) -> float:
        return sum(s.cost for s in self.spans)

    @property
    def span_count(self) -> int:
        return len(self.spans)

    def get_children(self, parent_id: str | None) -> list[Span]:
        return [s for s in self.spans if s.parent_id == parent_id]

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "root_span": self.root_span.to_dict() if self.root_span else None,
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
            "summary": {
                "total_duration_ms": round(self.total_duration_ms, 1),
                "total_tokens": self.total_tokens,
                "total_cost": round(self.total_cost, 6),
                "span_count": self.span_count,
            },
        }


class TraceRuntime:
    """Records execution traces for the entire pipeline.

    Provides:
    - Per-step timing, token usage, cost tracking
    - Hierarchical span tree (parent-child relationships)
    - Session-scoped traces
    - Summary statistics for frontend visualization
    """

    def __init__(self):
        self._traces: dict[str, TraceTree] = {}
        self._active_spans: dict[str, Span] = {}  # span_id → Span

    def start_trace(self, session_id: str, metadata: dict | None = None) -> str:
        """Start a new trace for a session. Returns trace_id (same as session_id)."""
        trace_id = session_id
        root_span = Span(
            span_id=f"root-{uuid.uuid4().hex[:8]}",
            trace_id=trace_id,
            parent_id=None,
            name="pipeline",
            start_time=time.time(),
            status="running",
            metadata=metadata or {},
        )

        tree = TraceTree(
            trace_id=trace_id,
            root_span=root_span,
            metadata=metadata or {},
            created_at=time.time(),
        )
        tree.spans.append(root_span)

        self._traces[trace_id] = tree
        self._active_spans[root_span.span_id] = root_span
        logger.info("Trace started: %s", trace_id)
        return trace_id

    def start_span(self, name: str, parent_id: str | None = None,
                   trace_id: str = "", step: str = "",
                   model: str = "", input_summary: dict | None = None,
                   metadata: dict | None = None) -> Span:
        """Start a new span within a trace."""
        # Find trace by trace_id or by parent
        if trace_id and trace_id in self._traces:
            tree = self._traces[trace_id]
        elif parent_id and parent_id in self._active_spans:
            parent_span = self._active_spans[parent_id]
            tree = self._traces.get(parent_span.trace_id)
            if tree and not parent_id:
                parent_id = tree.root_span.span_id if tree.root_span else None
        else:
            logger.warning("Cannot find trace for span '%s', creating orphan", name)
            tree = None

        span = Span(
            span_id=uuid.uuid4().hex[:12],
            trace_id=tree.trace_id if tree else "orphan",
            parent_id=parent_id,
            name=name,
            step=step,
            start_time=time.time(),
            status="running",
            model=model,
            input_summary=input_summary or {},
            metadata=metadata or {},
        )

        if tree:
            tree.spans.append(span)
        self._active_spans[span.span_id] = span
        return span

    def end_span(self, span_id: str, status: str = "completed",
                 output_summary: dict | None = None,
                 tokens_in: int = 0, tokens_out: int = 0,
                 cost: float = 0.0, error: str = "",
                 retry_count: int = 0) -> Span | None:
        """End a span and record its results."""
        span = self._active_spans.get(span_id)
        if not span:
            logger.warning("Cannot end unknown span: %s", span_id)
            return None

        span.end_time = time.time()
        span.duration_ms = (span.end_time - span.start_time) * 1000
        span.status = status
        span.output_summary = output_summary or {}
        span.tokens_in = tokens_in
        span.tokens_out = tokens_out
        span.cost = cost
        span.error = error
        span.retry_count = retry_count

        del self._active_spans[span_id]

        # If this is the root span, mark trace as completed
        tree = self._traces.get(span.trace_id)
        if tree and tree.root_span and tree.root_span.span_id == span_id:
            tree.completed_at = time.time()
            tree.root_span = span
            logger.info("Trace completed: %s (%.0fms, %d tokens, $%.4f)",
                        span.trace_id, span.duration_ms,
                        tree.total_tokens, tree.total_cost)

        return span

    def get_trace(self, trace_id: str) -> TraceTree | None:
        """Get a trace tree by session/trace ID."""
        return self._traces.get(trace_id)

    def get_trace_summary(self, trace_id: str) -> dict | None:
        """Get a flat summary of a trace for quick display."""
        tree = self._traces.get(trace_id)
        if not tree:
            return None

        steps = []
        for span in tree.spans:
            if span.parent_id and span.step:  # Skip root span
                steps.append({
                    "step": span.step,
                    "name": span.name,
                    "duration_ms": round(span.duration_ms, 1),
                    "tokens": span.tokens_in + span.tokens_out,
                    "cost": round(span.cost, 6),
                    "status": span.status,
                    "retries": span.retry_count,
                })

        return {
            "trace_id": trace_id,
            "total_duration_ms": round(tree.total_duration_ms, 1),
            "total_tokens": tree.total_tokens,
            "total_cost": round(tree.total_cost, 6),
            "steps": steps,
        }

    def list_traces(self) -> list[dict]:
        """List all traces with summaries."""
        return [
            {
                "trace_id": t.trace_id,
                "span_count": t.span_count,
                "total_duration_ms": round(t.total_duration_ms, 1),
                "total_tokens": t.total_tokens,
                "total_cost": round(t.total_cost, 6),
                "status": "completed" if t.completed_at else "running",
                "created_at": t.created_at,
            }
            for t in self._traces.values()
        ]

    def cleanup_old_traces(self, max_age_seconds: int = 3600):
        """Remove traces older than max_age_seconds."""
        now = time.time()
        to_remove = [
            tid for tid, t in self._traces.items()
            if now - t.created_at > max_age_seconds
        ]
        for tid in to_remove:
            del self._traces[tid]
        if to_remove:
            logger.info("Cleaned up %d old traces", len(to_remove))

    def get_stats(self) -> dict:
        active = len(self._active_spans)
        total = len(self._traces)
        return {
            "active_spans": active,
            "total_traces": total,
        }


# Global singleton
_trace_runtime: TraceRuntime | None = None

def get_trace_runtime() -> TraceRuntime:
    global _trace_runtime
    if _trace_runtime is None:
        _trace_runtime = TraceRuntime()
    return _trace_runtime