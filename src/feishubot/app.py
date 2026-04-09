from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from feishubot.ai.core.errors import ProviderNotFoundError
from feishubot.ai.orchestrator import AgentLoop
from feishubot.ai.providers import ModelProvider, create_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.config import settings
from feishubot.feishu import FeishuClient

app = FastAPI(title="FeishuBot", version="0.1.0")

feishu_client = FeishuClient(
    app_id=settings.feishu_app_id,
    app_secret=settings.feishu_app_secret,
)


def get_model_provider() -> ModelProvider:
    active = settings.active_llm_config()
    try:
        return create_provider(active)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str | None = None
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    provider: str
    model: str
    reply: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/llm/chat", response_model=ChatResponse)
async def chat_with_llm(payload: ChatRequest) -> ChatResponse:
    active = settings.active_llm_config()
    model_provider = get_model_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=payload.system_prompt or active.system_prompt,
    )
    reply = await agent_loop.run(user_input=payload.message, user_id=payload.user_id)

    return ChatResponse(
        provider=active.provider,
        model=active.model,
        reply=reply,
    )


@app.post("/webhook/feishu/events")
async def handle_feishu_events(request: Request) -> dict[str, Any]:
    body = await request.json()

    # URL verification handshake required by Feishu event subscription.
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Optional verification token check.
    if settings.feishu_verification_token:
        token = body.get("token")
        if token != settings.feishu_verification_token:
            raise HTTPException(status_code=401, detail="invalid verification token")

    event = body.get("event", {})
    message = event.get("message", {})
    sender = event.get("sender", {})

    raw_content = message.get("content", "")
    text = raw_content
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, dict):
                text = parsed.get("text") or raw_content
        except json.JSONDecodeError:
            text = raw_content

    if not text:
        return {"ok": True, "ignored": "empty message content"}

    user_open_id = sender.get("sender_id", {}).get("open_id")
    chat_id = event.get("message", {}).get("chat_id")

    model_provider = get_model_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=settings.active_llm_config().system_prompt,
    )
    reply = await agent_loop.run(user_input=text, user_id=user_open_id)

    # For private/group chat replies, send by chat_id. Adjust receive_id_type if needed.
    if chat_id:
        await feishu_client.send_text_message(
            receive_id=chat_id, text=reply, receive_id_type="chat_id"
        )

    return {"ok": True}
