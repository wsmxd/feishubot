from __future__ import annotations

from io import IOBase
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

    async def send_image_message(
        self, receive_id: str, image_file: IOBase, receive_id_type: str = "open_id"
    ) -> dict[str, Any]:
        return await self._client.send_image_message(
            receive_id=receive_id,
            image_file=image_file,
            receive_id_type=receive_id_type,
        )

    async def get_message_image_base64(self, *, message_id: str, file_key: str) -> str:
        return await self._client.get_message_image_base64(
            message_id=message_id,
            file_key=file_key,
        )

    async def get_message_image_data_url(self, *, message_id: str, file_key: str) -> str:
        return await self._client.get_message_image_data_url(
            message_id=message_id,
            file_key=file_key,
        )
