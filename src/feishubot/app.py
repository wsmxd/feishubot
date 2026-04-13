from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from lark_oapi.core.model import RawRequest
from pydantic import BaseModel, Field

from feishubot.ai.core.errors import ProviderNotFoundError
from feishubot.ai.orchestrator import AgentLoop
from feishubot.ai.orchestrator.feishu_events import build_event_dispatcher
from feishubot.ai.prompts import build_system_prompt
from feishubot.ai.providers import ModelProvider, create_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.channel import Channel, create_default_channel
from feishubot.config import settings

app = FastAPI(title="FeishuBot", version="0.1.0")

channel_client: Channel = create_default_channel()
feishu_event_dispatcher = build_event_dispatcher()


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


class FeishuPushRequest(BaseModel):
    receive_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    receive_id_type: str = "open_id"


class FeishuRelayRequest(BaseModel):
    message: str = Field(min_length=1)
    receive_id: str = Field(min_length=1)
    receive_id_type: str = "open_id"
    user_id: str | None = None
    system_prompt: str | None = None


def _coerce_first_value(values: list[str] | None) -> str | None:
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    normalized = str(value).strip()
    return normalized or None


def _decode_request_body(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body must be valid utf-8") from exc


async def _extract_chat_request(request: Request) -> ChatRequest:
    message: str | None = _coerce_first_value(request.query_params.getlist("message"))
    if message is None:
        message = _coerce_first_value(request.query_params.getlist("text"))
    if message is None:
        message = _coerce_first_value(request.query_params.getlist("prompt"))

    user_id = _coerce_first_value(request.query_params.getlist("user_id"))
    system_prompt = _coerce_first_value(request.query_params.getlist("system_prompt"))

    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                payload = json.loads(_decode_request_body(body))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid JSON body") from exc

            if isinstance(payload, dict):
                message = (
                    _normalize_text(payload.get("message"))
                    or _normalize_text(payload.get("text"))
                    or _normalize_text(payload.get("prompt"))
                    or message
                )
                user_id = _normalize_text(payload.get("user_id")) or user_id
                system_prompt = _normalize_text(payload.get("system_prompt")) or system_prompt
            elif isinstance(payload, str):
                message = _normalize_text(payload) or message
        elif "application/x-www-form-urlencoded" in content_type:
            form_values = parse_qs(_decode_request_body(body), keep_blank_values=True)
            message = (
                _coerce_first_value(form_values.get("message"))
                or _coerce_first_value(form_values.get("text"))
                or _coerce_first_value(form_values.get("prompt"))
                or message
            )
            user_id = _coerce_first_value(form_values.get("user_id")) or user_id
            system_prompt = _coerce_first_value(form_values.get("system_prompt")) or system_prompt
        elif message is None:
            raw_text = _decode_request_body(body).strip()
            if raw_text:
                message = raw_text

    if message is None:
        raise HTTPException(status_code=422, detail="message is required")

    return ChatRequest(message=message, user_id=user_id, system_prompt=system_prompt)


def _ensure_default_channel_configured() -> None:
    channel_name = settings.default_channel.strip().lower()
    if channel_name == "feishu" and (not settings.feishu_app_id or not settings.feishu_app_secret):
        raise HTTPException(
            status_code=500,
            detail="FEISHU_APP_ID and FEISHU_APP_SECRET must be configured",
        )


def _validate_internal_api_key(request: Request) -> None:
    expected_api_key = settings.gateway_internal_api_key.strip()
    if not expected_api_key:
        return

    provided_api_key = request.headers.get("x-api-key", "").strip()
    if provided_api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="invalid internal api key")


async def _run_agent(
    message: str, user_id: str | None, system_prompt: str | None = None
) -> ChatResponse:
    active = settings.active_llm_config()
    model_provider = get_model_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=build_system_prompt(active.system_prompt, system_prompt, include_core=False),
    )
    reply = await agent_loop.run(user_input=message, user_id=user_id)

    return ChatResponse(provider=active.provider, model=active.model, reply=reply)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/api/chat", methods=["GET", "POST"], response_model=ChatResponse)
@app.api_route("/api/llm/chat", methods=["GET", "POST"], response_model=ChatResponse)
async def chat_with_llm(request: Request) -> ChatResponse:
    payload = await _extract_chat_request(request)
    return await _run_agent(payload.message, payload.user_id, payload.system_prompt)


@app.post("/api/feishu/push")
async def push_feishu_message(payload: FeishuPushRequest, request: Request) -> dict[str, Any]:
    _validate_internal_api_key(request)
    _ensure_default_channel_configured()

    data = await channel_client.send_text_message(
        receive_id=payload.receive_id,
        text=payload.text,
        receive_id_type=payload.receive_id_type,
    )

    message_id = None
    if isinstance(data.get("data"), dict):
        message_id = data["data"].get("message_id")

    return {"ok": True, "message_id": message_id}


@app.post("/api/feishu/relay")
async def relay_feishu_message(payload: FeishuRelayRequest, request: Request) -> dict[str, Any]:
    _validate_internal_api_key(request)
    _ensure_default_channel_configured()

    llm_result = await _run_agent(payload.message, payload.user_id, payload.system_prompt)
    data = await channel_client.send_text_message(
        receive_id=payload.receive_id,
        text=llm_result.reply,
        receive_id_type=payload.receive_id_type,
    )

    message_id = None
    if isinstance(data.get("data"), dict):
        message_id = data["data"].get("message_id")

    return {
        "ok": True,
        "provider": llm_result.provider,
        "model": llm_result.model,
        "reply": llm_result.reply,
        "message_id": message_id,
    }


@app.post("/webhook/feishu/events")
async def handle_feishu_events(request: Request) -> Response | dict[str, str]:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="request body is required")

    if not settings.feishu_verification_token and not settings.feishu_encrypt_key:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid event payload") from exc

        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}

        feishu_event_dispatcher.do_without_validation(body)
        return {"msg": "success"}

    raw_request = RawRequest()
    raw_request.uri = request.url.path
    raw_request.headers = {k: v for k, v in request.headers.items()}
    raw_request.body = body

    raw_response = feishu_event_dispatcher.do(raw_request)
    return Response(
        content=raw_response.content or b"",
        status_code=raw_response.status_code or 200,
        headers=raw_response.headers,
    )
