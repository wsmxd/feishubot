from __future__ import annotations

from feishubot.ai.core.schemas import ChatMessage, ModelResponse
from feishubot.ai.providers.base import ModelProvider


class EchoProvider(ModelProvider):
    async def chat(
        self, messages: list[ChatMessage], *, user_id: str | None = None
    ) -> ModelResponse:
        user_text = ""
        for message in reversed(messages):
            if message.role == "user":
                user_text = message.content
                break

        prefix = f"[echo user={user_id}] " if user_id else "[echo] "
        return ModelResponse(text=prefix + user_text)
