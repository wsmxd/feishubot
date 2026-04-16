from __future__ import annotations

import base64
import json
from io import IOBase
from typing import Any
from uuid import uuid4

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateImageRequest,
    CreateImageRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
)

from feishubot.config import settings


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

    async def send_image_message(
        self, receive_id: str, image_file: IOBase, receive_id_type: str = "open_id"
    ) -> dict[str, Any]:
        """Send an image message.

        Args:
            receive_id: The ID of the message receiver
            image_file: File-like object containing the image data
            receive_id_type: Type of receive_id (default: "open_id")

        Returns:
            Response dict with code, msg, and data containing message_id

        Raises:
            RuntimeError: If image upload or message sending fails
        """
        # Step 1: Upload the image
        upload_request = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder().image_type("message").image(image_file).build()
            )
            .build()
        )

        upload_response = await self._client.im.v1.image.acreate(upload_request)
        if not upload_response.success():
            raise RuntimeError(
                "failed to upload feishu image: "
                f"code={upload_response.code}, msg={upload_response.msg}, "
                f"log_id={upload_response.get_log_id()}"
            )

        # Step 2: Send the message with the uploaded image
        option = (
            lark.RequestOption.builder()
            .headers({"X-Tt-Logid": upload_response.get_log_id()})
            .build()
        )

        message_request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("image")
                .content(lark.JSON.marshal(upload_response.data))
                .uuid(str(uuid4()))
                .build()
            )
            .build()
        )

        send_response = await self._client.im.v1.message.acreate(message_request, option)
        if not send_response.success():
            raise RuntimeError(
                "failed to send feishu image message: "
                f"code={send_response.code}, msg={send_response.msg}, "
                f"log_id={send_response.get_log_id()}"
            )

        message_id = send_response.data.message_id if send_response.data else None
        return {
            "code": send_response.code,
            "msg": send_response.msg,
            "data": {"message_id": message_id},
        }

    async def get_message_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: str = "image",
    ) -> bytes:
        """Download a resource from a specific message.

        Feishu requires `message_id` + `file_key` + `type` for message resources.
        """
        request = (
            GetMessageResourceRequest.builder()
            .type(resource_type)
            .message_id(message_id)
            .file_key(file_key)
            .build()
        )

        response = await self._client.im.v1.message_resource.aget(request)
        if not response.success() or response.file is None:
            status_code = response.raw.status_code if response.raw is not None else None
            raise RuntimeError(
                f"failed to download feishu {resource_type} resource: "
                f"status={status_code}, code={response.code}, msg={response.msg}, "
                f"log_id={response.get_log_id()}, message_id={message_id}, file_key={file_key}"
            )

        resource_bytes = response.file.read()
        if not resource_bytes:
            raise RuntimeError(
                f"failed to download feishu {resource_type} resource: empty file content, "
                f"message_id={message_id}, file_key={file_key}"
            )

        return resource_bytes

    async def get_message_image_base64(self, *, message_id: str, file_key: str) -> str:
        image_bytes = await self.get_message_resource(
            message_id=message_id,
            file_key=file_key,
            resource_type="image",
        )
        return base64.b64encode(image_bytes).decode("utf-8")

    async def get_message_image_data_url(self, *, message_id: str, file_key: str) -> str:
        image_bytes = await self.get_message_resource(
            message_id=message_id,
            file_key=file_key,
            resource_type="image",
        )
        if len(image_bytes) > settings.llm_image_max_bytes:
            raise RuntimeError(
                "image too large for model request: "
                f"size={len(image_bytes)} bytes, limit={settings.llm_image_max_bytes} bytes"
            )
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_mime = self._detect_image_mime(image_bytes)
        return f"data:{image_mime};base64,{image_b64}"

    @staticmethod
    def _detect_image_mime(image_bytes: bytes) -> str:
        # Magic-number based detection for common image formats.
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        if image_bytes.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        # Fallback for providers that expect an image/* MIME type.
        return "image/png"
