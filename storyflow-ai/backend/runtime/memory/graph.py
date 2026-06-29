"""Memory Graph - Timeline-aware graph-structured memory for characters and world state.

Upgrades from flat JSON (hair/cloth/face) to a graph where:
    - Nodes represent entities (characters, locations, events, items)
    - Edges represent relationships and state transitions
    - Every node/edge has a valid_from/valid_until for timeline awareness

The key capability: Runtime can query "what state is character X at chapter Y?"

Example graph:
    (林晓) --[wears]--> (白衣)         valid: chapter 1-2
    (林晓) --[injured_in]--> (河边)    valid: chapter 2
    (林晓) --[wears]--> (红衣)         valid: chapter 3+
    (林晓) --[transforms]--> (黑化)    valid: chapter 5+
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryNode:
    """A node in the memory graph."""
    id: str
    node_type: str  # "character", "location", "event", "item", "state"
    properties: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "properties": self.properties,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class MemoryEdge:
    """A directed edge in the memory graph."""
    source: str
    target: str
    relation: str  # "wears", "located_in", "knows", "transforms_into", ...
    properties: dict = field(default_factory=dict)
    valid_from: float = 0.0  # Timeline: when this edge becomes valid
    valid_until: float = float('inf')  # Timeline: when this edge expires
    metadata: dict = field(default_factory=dict)

    def is_valid_at(self, chapter: int = 0, timestamp: float = 0) -> bool:
        """Check if this edge is valid at a given point in the timeline."""
        check_val = chapter if chapter > 0 else timestamp
        return self.valid_from <= check_val <= self.valid_until

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "properties": self.properties,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "metadata": self.metadata,
        }


class MemoryGraph:
    """Timeline-aware graph memory for characters and world state.

    Key capabilities:
        1. Track character state changes over time (chapters/episodes)
        2. Query what a character looks like at any point in time
        3. Track relationships between characters
        4. Track world state changes (seasons, locations, events)

    The graph coexists with CharacterMemory/WorldMemory and adds
    the temporal dimension those layers lack.
    """

    def __init__(self):
        self._nodes: dict[str, MemoryNode] = {}
        self._edges: list[MemoryEdge] = []
        self._edge_index: dict[tuple[str, str], list[MemoryEdge]] = {}
        self._stats = {
            "nodes": 0, "edges": 0,
            "state_changes": 0, "queries": 0,
        }

    # ── Node operations ──

    def add_node(self, node: MemoryNode) -> None:
        self._nodes[node.id] = node
        self._stats["nodes"] = len(self._nodes)

    def get_node(self, node_id: str) -> MemoryNode | None:
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, node_type: str) -> list[MemoryNode]:
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def update_node_property(self, node_id: str, key: str, value: Any) -> None:
        node = self._nodes.get(node_id)
        if node:
            node.properties[key] = value

    # ── Edge operations ──

    def add_edge(self, edge: MemoryEdge) -> None:
        self._edges.append(edge)
        index_key = (edge.source, edge.relation)
        if index_key not in self._edge_index:
            self._edge_index[index_key] = []
        self._edge_index[index_key].append(edge)
        self._stats["edges"] = len(self._edges)

    def get_edges(self, source: str = "", relation: str = "",
                  target: str = "") -> list[MemoryEdge]:
        results = self._edges
        if source:
            results = [e for e in results if e.source == source]
        if target:
            results = [e for e in results if e.target == target]
        if relation:
            results = [e for e in results if e.relation == relation]
        return results

    def get_edges_at(self, chapter: int = 0, source: str = "",
                     relation: str = "") -> list[MemoryEdge]:
        results = self._edges
        if source:
            results = [e for e in results if e.source == source]
        if relation:
            results = [e for e in results if e.relation == relation]
        return [e for e in results if e.is_valid_at(chapter=chapter)]

    # ── State tracking (the key feature) ──

    def add_state_change(self, character_name: str, field_path: str,
                         value: Any, chapter: int = 0,
                         reason: str = "") -> None:
        """Record a character state change at a specific chapter.

        Creates a state node + timed edge, and expires previous state
        for the same field_path.
        """
        state_id = f"{character_name}::{field_path}::{chapter}"
        node = MemoryNode(
            id=state_id, node_type="state",
            properties={
                "character": character_name, "field": field_path,
                "value": value, "chapter": chapter, "reason": reason,
            },
        )
        self.add_node(node)

        # Expire previous state for this field
        for edge in self._edges:
            if (edge.source == character_name
                    and edge.relation == "has_state"
                    and edge.properties.get("field") == field_path):
                if chapter > 0:
                    edge.valid_until = chapter - 0.5

        edge = MemoryEdge(
            source=character_name, target=state_id,
            relation="has_state",
            properties={"field": field_path, "chapter": chapter},
            valid_from=chapter, valid_until=float('inf'),
            metadata={"reason": reason},
        )
        self.add_edge(edge)
        self._stats["state_changes"] += 1

    def get_character_state_at(self, character_name: str,
                               chapter: int = 0) -> dict[str, Any]:
        """Get the full state of a character at a specific chapter.

        KILLER FEATURE: returns all active state edges compiled into
        a flat dict suitable for prompt injection.
        """
        self._stats["queries"] += 1
        edges = self.get_edges_at(
            chapter=chapter, source=character_name, relation="has_state")
        state = {}
        for edge in edges:
            fld = edge.properties.get("field", "")
            target_node = self._nodes.get(edge.target)
            if target_node:
                state[fld] = target_node.properties.get("value")
        return state

    def get_character_appearance_at(self, character_name: str,
                                    chapter: int = 0) -> str:
        """Get formatted appearance string for a character at a chapter."""
        state = self.get_character_state_at(character_name, chapter)
        parts = []
        for f in ("appearance.hair", "appearance.face",
                  "appearance.body", "appearance.cloth"):
            val = state.get(f)
            if val:
                parts.append(str(val))
        return ", ".join(parts)

    def get_character_timeline(self, character_name: str,
                               field: str = "") -> list[dict]:
        """Get the timeline of state changes for a character."""
        edges = self.get_edges(source=character_name, relation="has_state")
        timeline = []
        for edge in sorted(edges, key=lambda e: e.valid_from):
            if field and edge.properties.get("field") != field:
                continue
            target_node = self._nodes.get(edge.target)
            if target_node:
                timeline.append({
                    "chapter": edge.valid_from,
                    "field": edge.properties.get("field", ""),
                    "value": target_node.properties.get("value"),
                    "reason": edge.metadata.get("reason", ""),
                })
        return timeline

    # ── Relationship tracking ──

    def add_relationship(self, from_char: str, to_char: str,
                         relation: str, chapter: int = 0,
                         properties: dict | None = None) -> None:
        for name in (from_char, to_char):
            if name not in self._nodes:
                self.add_node(MemoryNode(
                    id=name, node_type="character",
                    properties={"name": name}))
        edge = MemoryEdge(
            source=from_char, target=to_char, relation=relation,
            properties=properties or {}, valid_from=chapter,
            metadata={"type": "relationship"})
        self.add_edge(edge)

    def get_relationships(self, character_name: str,
                          chapter: int = 0) -> list[dict]:
        edges = self.get_edges_at(chapter=chapter, source=character_name)
        rels = []
        for edge in edges:
            if edge.metadata.get("type") == "relationship":
                target = self._nodes.get(edge.target)
                rels.append({
                    "relation": edge.relation, "with": edge.target,
                    "with_name": (target.properties.get("name", edge.target)
                                  if target else edge.target),
                    "properties": edge.properties,
                })
        return rels

    # ── Bulk operations ──

    def populate_from_script(self, script_result: dict) -> None:
        """Extract character info from script output and populate graph."""
        characters = script_result.get("characters", [])
        for char in characters:
            name = char.get("name", "")
            if not name:
                continue
            self.add_node(MemoryNode(
                id=name, node_type="character",
                properties={
                    "name": name, "gender": char.get("gender", ""),
                    "age": char.get("age", ""),
                    "personality": char.get("personality", {}),
                }))
            appearance = char.get("appearance", {})
            if isinstance(appearance, dict):
                for dim, val in appearance.items():
                    if val:
                        self.add_state_change(
                            name, f"appearance.{dim}", val, chapter=0,
                            reason="Initial character design")

    def populate_from_storyboard(self, storyboard_result: dict,
                                 chapter: int = 1) -> None:
        """Extract state changes from storyboard output."""
        scenes = storyboard_result.get("storyboard", [])
        for scene in scenes:
            dialogue = scene.get("dialogue", "")
            if dialogue and "受伤" in dialogue:
                chars = scene.get("characters", [])
                for char_name in chars:
                    self.add_state_change(
                        char_name, "status.injured", True, chapter=chapter,
                        reason=f"Scene {scene.get('scene_no', '?')}: "
                               f"{dialogue[:50]}")

    def populate_from_character_update(self, character_result: dict,
                                       chapter: int = 0) -> None:
        """Update character states from character agent output."""
        characters = character_result.get("characters", [])
        for char in characters:
            name = char.get("name", "")
            if not name:
                continue
            appearance = char.get("appearance", {})
            if isinstance(appearance, dict):
                for dim, val in appearance.items():
                    if val:
                        self.add_state_change(
                            name, f"appearance.{dim}", val, chapter=chapter,
                            reason="Character design update")

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._edge_index.clear()

    def get_stats(self) -> dict:
        return dict(self._stats)
