"""Base Memory - Abstract base class for all memory layers."""

from abc import ABC, abstractmethod
from typing import Any


class BaseMemory(ABC):
    """Abstract base for memory layers."""

    name: str = "base"

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from memory."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set a value in memory."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key from memory."""
        ...

    @abstractmethod
    def to_dict(self) -> dict:
        """Export all memory as a dict."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all memory."""
        ...

    def get_all(self) -> dict:
        return self.to_dict()