from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Channel(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def send_text_message(
        self, receive_id: str, text: str, receive_id_type: str = "open_id"
    ) -> dict[str, Any]:
        raise NotImplementedError
