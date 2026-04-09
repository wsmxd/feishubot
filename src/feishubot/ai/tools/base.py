from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class Tool(ABC):
    name: str
    description: str
    args_model: type[BaseModel] | None = None

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.args_model is None:
            return arguments

        validated = self.args_model.model_validate(arguments)
        return validated.model_dump(exclude_none=True)

    @abstractmethod
    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
