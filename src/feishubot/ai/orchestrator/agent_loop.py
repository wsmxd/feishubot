from __future__ import annotations

import json
from json import JSONDecodeError, JSONDecoder
from typing import Any

from feishubot.ai.tools.runtime import ToolRuntime
from feishubot.llm_client import OpenAICompatibleLLMClient


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = [line for line in stripped.splitlines() if not line.startswith("```")]
    return "\n".join(lines).strip()


def _extract_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    payload_text = _strip_code_fences(text)

    payload = _parse_json_object(payload_text)
    if payload is None:
        return None

    tool_name = payload.get("tool") or payload.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None

    arguments = payload.get("arguments") or payload.get("args") or {}
    if not isinstance(arguments, dict):
        return None

    return tool_name.strip(), arguments


def _parse_json_object(text: str) -> dict[str, Any] | None:
    decoder = JSONDecoder()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except JSONDecodeError:
        pass

    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


class AgentLoop:
    """Coordinates model calls and tool invocations."""

    def __init__(
        self,
        *,
        llm_client: Any,
        tool_runtime: ToolRuntime,
        system_prompt: str | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_runtime = tool_runtime
        self._system_prompt = system_prompt

    async def _generate_model_reply(self, *, prompt: str, user_id: str | None = None) -> str:
        if isinstance(self._llm_client, OpenAICompatibleLLMClient) and self._system_prompt:
            return await self._llm_client.generate_reply_with_system_prompt(
                prompt=prompt,
                system_prompt=self._system_prompt,
                user_id=user_id,
            )
        return await self._llm_client.generate_reply(prompt=prompt, user_id=user_id)

    def _build_tool_routing_prompt(self, user_input: str) -> str:
        tool_catalog = self._tool_runtime.render_tool_catalog()
        return (
            "You can answer directly or call one tool.\n"
            f"{tool_catalog}\n\n"
            "If a tool is needed, respond with exactly one JSON object:\n"
            '{"tool": "terminal", "arguments": {"command": "df -h"}}\n\n'
            "If no tool is needed, answer normally.\n\n"
            f"User request:\n{user_input}"
        )

    async def run(self, user_input: str, user_id: str | None = None) -> str:
        first_prompt = self._build_tool_routing_prompt(user_input)
        first_reply = await self._generate_model_reply(prompt=first_prompt, user_id=user_id)

        tool_call = _extract_tool_call(first_reply)
        if tool_call is None:
            return first_reply

        tool_name, arguments = tool_call
        tool_failed = False
        tool_error = ""
        try:
            tool_result = await self._tool_runtime.execute(tool_name, arguments)
            formatted_result = self._tool_runtime.format_result(tool_name, tool_result)
        except Exception as exc:  # noqa: BLE001
            tool_failed = True
            tool_error = str(exc)
            formatted_result = "<tool execution failed>"

        second_prompt = (
            f"User request:\n{user_input}\n\n"
            f"Tool called: {tool_name}\n"
            f"Tool arguments:\n{json.dumps(arguments, ensure_ascii=False, indent=2)}\n\n"
            f"Tool result:\n{formatted_result}\n\n"
            f"Tool failed: {tool_failed}\n"
            f"Tool error: {tool_error}\n\n"
            "Now answer the user based on the tool result. "
            "If tool failed, explain the failure and suggest a safer retry."
        )

        return await self._generate_model_reply(prompt=second_prompt, user_id=user_id)
