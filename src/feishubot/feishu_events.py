from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import lark_oapi as lark

from feishubot.ai.orchestrator import AgentLoop
from feishubot.ai.prompts import build_system_prompt
from feishubot.ai.providers import create_active_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.config import settings
from feishubot.feishu import FeishuClient

logger = logging.getLogger(__name__)

feishu_client = FeishuClient(
    app_id=settings.feishu_app_id,
    app_secret=settings.feishu_app_secret,
)


def _extract_text(raw_content: Any) -> str | None:
    if not isinstance(raw_content, str):
        return None

    text = raw_content.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text

    if isinstance(payload, dict):
        parsed_text = payload.get("text")
        if isinstance(parsed_text, str) and parsed_text.strip():
            return parsed_text.strip()

    return text


async def _run_agent(message: str, user_id: str | None) -> str:
    active = settings.active_llm_config()
    model_provider = create_active_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=build_system_prompt(active.system_prompt, include_core=False),
    )
    return await agent_loop.run(user_input=message, user_id=user_id)


async def process_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    event = data.event
    if event is None or event.message is None:
        return

    message = event.message
    if message.message_type != "text":
        return

    text = _extract_text(message.content)
    if not text:
        return

    chat_id = message.chat_id
    user_open_id = None
    if event.sender is not None and event.sender.sender_id is not None:
        user_open_id = event.sender.sender_id.open_id

    reply = await _run_agent(text, user_open_id)
    if chat_id:
        await feishu_client.send_text_message(
            receive_id=chat_id,
            text=reply,
            receive_id_type="chat_id",
        )


def _log_background_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except Exception:  # noqa: BLE001
        logger.exception("failed to handle feishu message event")


def on_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    # Event callbacks must return quickly; process message async to avoid retry due to timeout.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("no running event loop, skip feishu message event")
        return

    task = loop.create_task(process_p2_im_message_receive_v1(data))
    task.add_done_callback(_log_background_task_result)


def build_event_dispatcher(
    log_level: lark.LogLevel = lark.LogLevel.INFO,
) -> lark.EventDispatcherHandler:
    return (
        lark.EventDispatcherHandler.builder(
            settings.feishu_encrypt_key,
            settings.feishu_verification_token,
            log_level,
        )
        .register_p2_im_message_receive_v1(on_p2_im_message_receive_v1)
        .build()
    )
