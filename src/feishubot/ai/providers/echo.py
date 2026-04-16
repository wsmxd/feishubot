from __future__ import annotations

import json

from feishubot.ai.core.schemas import ChatMessage, ModelResponse
from feishubot.ai.providers.base import ModelProvider


class EchoProvider(ModelProvider):
    async def chat(
        self, messages: list[ChatMessage], *, user_id: str | None = None
    ) -> ModelResponse:
        user_text: str = ""
        for message in reversed(messages):
            if message.role == "user":
                content = message.content
                if isinstance(content, str):
                    user_text = content
                else:
                    user_text = json.dumps(content, ensure_ascii=False)
                break

        prefix = f"[echo user={user_id}] " if user_id else "[echo] "
        return ModelResponse(text=prefix + user_text)
