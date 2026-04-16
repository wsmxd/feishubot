from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path


class MemoryStore(ABC):
    """State store abstraction used by memory/session layer."""

    @abstractmethod
    def append(self, key: str, value: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, key: str) -> list[str]:
        raise NotImplementedError


class JsonlMemoryStore(MemoryStore):
    """Simple file-backed implementation where each key maps to <key>.jsonl."""

    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir

    def _path_for_key(self, key: str) -> Path:
        # Key comes from date/user identifiers; keep it filename-safe.
        safe_key = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in key)
        return self._base_dir / f"{safe_key}.jsonl"

    def append(self, key: str, value: str) -> None:
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(value + "\n")
        if os.name == "posix":
            os.chmod(path, 0o600)

    def read(self, key: str) -> list[str]:
        path = self._path_for_key(key)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
