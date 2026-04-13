from __future__ import annotations

from typing import Any

from feishubot.channel.base import Channel
from feishubot.feishu import FeishuClient


class FeishuChannel(Channel):
    name = "feishu"

    def __init__(self, *, app_id: str, app_secret: str) -> None:
        self._client = FeishuClient(app_id=app_id, app_secret=app_secret)

    async def send_text_message(
        self, receive_id: str, text: str, receive_id_type: str = "open_id"
    ) -> dict[str, Any]:
        return await self._client.send_text_message(
            receive_id=receive_id,
            text=text,
            receive_id_type=receive_id_type,
        )
