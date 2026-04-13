from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import lark_oapi as lark

from feishubot.ai.orchestrator.agent_loop import AgentLoop
from feishubot.ai.prompts import build_system_prompt
from feishubot.ai.providers import create_active_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.channel import Channel, create_default_channel
from feishubot.config import settings

logger = logging.getLogger(__name__)

channel_client: Channel | None = None
_event_worker_loop: asyncio.AbstractEventLoop | None = None
_event_worker_thread: threading.Thread | None = None


def _get_channel_client() -> Channel:
    global channel_client
    if channel_client is None:
        channel_client = create_default_channel()
    return channel_client


def start_event_worker_loop() -> None:
    global _event_worker_loop, _event_worker_thread
    if _event_worker_loop is not None:
        return

    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, name="feishu-event-worker", daemon=True)
    thread.start()
    _event_worker_loop = loop
    _event_worker_thread = thread


def _submit_event_task(coro: Any) -> None:
    if _event_worker_loop is None:
        start_event_worker_loop()

    if _event_worker_loop is None:
        raise RuntimeError("event worker loop failed to start")

    future = asyncio.run_coroutine_threadsafe(coro, _event_worker_loop)

    def _log_task_result(completed_future: Any) -> None:
        try:
            completed_future.result()
        except Exception:  # noqa: BLE001
            logger.exception("failed to handle feishu message event")

    future.add_done_callback(_log_task_result)


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
        await _get_channel_client().send_text_message(
            receive_id=chat_id,
            text=reply,
            receive_id_type="chat_id",
        )


def on_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    # Event callbacks must return quickly; process message in the dedicated worker loop.
    _submit_event_task(process_p2_im_message_receive_v1(data))


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
