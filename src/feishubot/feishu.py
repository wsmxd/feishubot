from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(lark.FEISHU_DOMAIN)
            .build()
        )

    async def send_text_message(
        self, receive_id: str, text: str, receive_id_type: str = "open_id"
    ) -> dict[str, Any]:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .uuid(str(uuid4()))
                .build()
            )
            .build()
        )

        response = await self._client.im.v1.message.acreate(request)
        if not response.success():
            raise RuntimeError(
                "failed to send feishu message: "
                f"code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )

        message_id = response.data.message_id if response.data else None
        return {
            "code": response.code,
            "msg": response.msg,
            "data": {"message_id": message_id},
        }
