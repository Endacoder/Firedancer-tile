"""Abstract base class for all metric backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from fdmon.models import TileSnapshot


class BackendError(Exception):
    """Raised when a backend cannot connect or read data."""


class BaseBackend(ABC):
    """
    All backends implement this interface so the rest of fdmon is
    backend-agnostic.
    """

    @abstractmethod
    def connect(self) -> None:
        """Initialise the connection / open resources."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Release all resources."""
        ...

    @abstractmethod
    def read_tiles(self) -> List[TileSnapshot]:
        """
        Fetch the current tile metrics snapshot.

        Returns a list of TileSnapshot objects — one per tile instance.
        Raises BackendError on transient I/O failures.
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the backend is currently operational."""
        ...

    # ── Context-manager convenience ──────────────────────────────────────────

    def __enter__(self) -> "BaseBackend":
        self.connect()
        return self

    def __exit__(self, *_args) -> None:
        self.disconnect()
