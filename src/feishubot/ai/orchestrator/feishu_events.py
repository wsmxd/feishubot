from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import httpx
import lark_oapi as lark

from feishubot.ai.core.schemas import ChatMessage
from feishubot.ai.memory import SessionManager
from feishubot.ai.orchestrator.agent_loop import AgentLoop
from feishubot.ai.prompts import build_system_prompt
from feishubot.ai.providers import create_active_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.channel import Channel, create_default_channel
from feishubot.channel.feishu import FeishuChannel
from feishubot.config import settings

logger = logging.getLogger(__name__)

channel_client: Channel | None = None
_event_worker_loop: asyncio.AbstractEventLoop | None = None
_event_worker_thread: threading.Thread | None = None
_memory_manager: SessionManager | None = None


def _get_channel_client() -> Channel:
    global channel_client
    if channel_client is None:
        logger.debug("Creating default channel client")
        channel_client = create_default_channel()
        logger.debug(f"Channel client ready: type={type(channel_client).__name__}")
    return channel_client


def _get_memory_manager() -> SessionManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = SessionManager(max_history=50, store_sensitive=False)
    return _memory_manager


def start_event_worker_loop() -> None:
    global _event_worker_loop, _event_worker_thread
    if _event_worker_loop is not None:
        logger.debug("Event worker loop already running")
        return

    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, name="feishu-event-worker", daemon=True)
    thread.start()
    _event_worker_loop = loop
    _event_worker_thread = thread
    logger.info("Started event worker loop thread: feishu-event-worker")


def _submit_event_task(coro: Any) -> None:
    if _event_worker_loop is None:
        logger.debug("Event worker loop not started yet, starting now")
        start_event_worker_loop()

    if _event_worker_loop is None:
        raise RuntimeError("event worker loop failed to start")

    future = asyncio.run_coroutine_threadsafe(coro, _event_worker_loop)
    logger.debug("Submitted message event task to worker loop")

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


def _extract_file_key(raw_content: Any) -> str | None:
    if not isinstance(raw_content, str):
        return None

    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    file_key = payload.get("file_key") or payload.get("image_key")
    return file_key if isinstance(file_key, str) and file_key.strip() else None


async def _run_agent(message: str, user_id: str | None) -> str:
    active = settings.active_llm_config()
    model_provider = create_active_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=build_system_prompt(active.system_prompt, include_core=False),
    )
    return await agent_loop.run(user_input=message, user_id=user_id)


async def _run_agent_with_image(
    image_data_url: str, user_message: str | None = None, user_id: str | None = None
) -> str:
    """Run image analysis with a multimodal message and safe fallback."""
    active = settings.active_llm_config()
    model_provider = create_active_provider()
    system_prompt = build_system_prompt(active.system_prompt, include_core=False)
    text_prompt = user_message or "请分析这张图片的主要内容，并给出简洁结论。"

    # Use multimodal image_url content; data URL can be image/png/jpeg/webp.
    multimodal_messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(
            role="user",
            content=[
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": text_prompt},
            ],
        ),
    ]
    logger.debug(
        "Prepared multimodal request with image_url data URI prefix: "
        f"{image_data_url[:32]}..., total_chars={len(image_data_url)}"
    )

    try:
        response = await model_provider.chat(messages=multimodal_messages, user_id=user_id)
        if response.text.strip():
            return response.text
        return "图片已收到，但模型没有返回可读结果，请稍后重试。"
    except httpx.TimeoutException:
        logger.exception("Image analysis timed out when calling model provider")
        return "图片已收到，但模型分析超时。请稍后重试，或切换更快/支持视觉的模型。"
    except Exception:  # noqa: BLE001
        logger.exception("Image analysis request failed in multimodal mode")
        return "图片已收到，但当前模型暂时无法完成图片分析。请检查所选模型是否支持视觉输入后重试。"


async def process_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    logger.debug("Begin processing p2_im_message_receive_v1 event")
    event = data.event
    if event is None or event.message is None:
        logger.warning("Skip event: missing event/message payload")
        return

    message = event.message
    message_id = message.message_id
    chat_id = message.chat_id
    user_open_id = None
    if event.sender is not None and event.sender.sender_id is not None:
        user_open_id = event.sender.sender_id.open_id

    logger.debug(
        "Incoming message: "
        f"message_id={message_id}, chat_id={chat_id}, "
        f"message_type={message.message_type}, sender_open_id={user_open_id}"
    )

    if message.message_type == "text":
        text = _extract_text(message.content)
        if not text:
            logger.warning(
                f"Skip text message with empty content: message_id={message_id}, chat_id={chat_id}"
            )
            return

        logger.debug(f"Running text agent for message_id={message_id}")
        reply = await _run_agent(text, user_open_id)
        if chat_id:
            logger.debug(f"Sending text reply to chat_id={chat_id} for message_id={message_id}")
            await _get_channel_client().send_text_message(
                receive_id=chat_id,
                text=reply,
                receive_id_type="chat_id",
            )
            logger.debug(f"Text reply sent for message_id={message_id}")
        else:
            logger.warning(f"Skip text reply due to missing chat_id: message_id={message_id}")
    elif message.message_type == "image":
        logger.info(f"Received image message: message_id={message_id}, chat_id={chat_id}")
        logger.debug(f"Image message content: {message.content}")
        file_key = _extract_file_key(message.content)
        if file_key:
            logger.debug(f"Extracted file key for image message: {file_key}")
        else:
            logger.warning(
                f"Failed to extract file key from image message content: message_id={message_id}"
            )

        if file_key and chat_id and message_id:
            try:
                logger.debug(
                    f"Downloading image resource with message_id={message_id}, file_key={file_key}"
                )
                channel_client = _get_channel_client()
                if not isinstance(channel_client, FeishuChannel):
                    raise RuntimeError("image analysis only supports FeishuChannel")

                image_data_url = await channel_client.get_message_image_data_url(
                    message_id=message_id,
                    file_key=file_key,
                )
                logger.debug(f"Successfully downloaded image, size: {len(image_data_url)} chars")

                # Send image to AI for analysis
                logger.info("Sending image to AI for analysis")
                reply = await _run_agent_with_image(
                    image_data_url=image_data_url,
                    user_message=None,
                    user_id=user_open_id,
                )
                logger.debug(f"Received analysis result length={len(reply)}")

                # Send analysis result back
                logger.debug(
                    f"Sending image analysis reply to chat_id={chat_id} for message_id={message_id}"
                )
                await channel_client.send_text_message(
                    receive_id=chat_id,
                    text=reply,
                    receive_id_type="chat_id",
                )
                logger.info(f"Image analysis reply sent for message_id={message_id}")

                if user_open_id:
                    summary = f"Image analysis result: {reply.strip()}"
                    _get_memory_manager().save_memory_event(
                        user_id=user_open_id,
                        role="assistant",
                        content=summary,
                        kind="image_analysis",
                        metadata={
                            "message_id": message_id,
                            "chat_id": chat_id,
                            "file_key": file_key,
                            "source": "feishu_image",
                        },
                    )
            except Exception as e:
                logger.exception(f"Failed to process image message: {e}")
                # Send error message
                try:
                    user_error_message = "图片处理失败，请稍后重试。"
                    if message_id:
                        user_error_message = f"{user_error_message} 消息ID: {message_id}"
                    await _get_channel_client().send_text_message(
                        receive_id=chat_id,
                        text=user_error_message,
                        receive_id_type="chat_id",
                    )
                    logger.debug(
                        f"Sent image-processing error reply to chat_id={chat_id}, "
                        f"message_id={message_id}"
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to send image-processing error reply back to Feishu")
        else:
            logger.warning(
                "Missing message_id/file_key/chat_id for image processing. "
                f"message_id={message_id}, file_key={file_key}, chat_id={chat_id}"
            )
    else:
        logger.debug(
            f"Ignoring unsupported message type '{message.message_type}' "
            f"for message_id={message_id}"
        )


def on_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
    data: lark.im.v1.P2ImChatAccessEventBotP2pChatEnteredV1,
) -> None:
    # Explicitly handle this event type to avoid noisy "processor not found" errors.
    logger.debug("Received bot_p2p_chat_entered_v1 event")


def on_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    # Event callbacks must return quickly; process message in the dedicated worker loop.
    logger.debug("Received callback for p2_im_message_receive_v1, scheduling async task")
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
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
            on_p2_im_chat_access_event_bot_p2p_chat_entered_v1
        )
        .register_p2_im_message_receive_v1(on_p2_im_message_receive_v1)
        .build()
    )
