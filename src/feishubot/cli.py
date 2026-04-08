from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from feishubot.app import get_llm_client
from feishubot.llm_client import OpenAICompatibleLLMClient
from feishubot.config import settings


def _add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user-id", default="terminal-user", help="User ID passed to the LLM backend")
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Optional system prompt (only works with openai_compatible provider)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FeishuBot command line")
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("chat", help="Start terminal chat loop")
    _add_chat_arguments(chat_parser)

    gateway_parser = subparsers.add_parser("gateway", help="Start HTTP gateway service")
    gateway_parser.add_argument("--host", default="0.0.0.0", help="Gateway bind host")
    gateway_parser.add_argument("--port", type=int, default=8000, help="Gateway bind port")
    gateway_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    return parser


async def _chat_loop(user_id: str, system_prompt: str | None) -> None:
    llm_client = get_llm_client()

    print("FeishuBot terminal chat is ready.")
    print("Type your message and press Enter. Use /exit to quit.")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue

        if user_input.lower() in {"/exit", "exit", "quit"}:
            print("bye")
            break

        try:
            if isinstance(llm_client, OpenAICompatibleLLMClient) and system_prompt:
                reply = await llm_client.generate_reply_with_system_prompt(
                    prompt=user_input,
                    system_prompt=system_prompt,
                    user_id=user_id,
                )
            else:
                reply = await llm_client.generate_reply(prompt=user_input, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            print(f"bot(error)> {exc}")
            continue

        print(f"bot> {reply}")


def _run_chat(args: argparse.Namespace) -> None:
    asyncio.run(_chat_loop(user_id=args.user_id, system_prompt=args.system_prompt))


def _run_gateway(args: argparse.Namespace) -> None:
    import uvicorn

    if args.reload:
        print("Starting FeishuBot gateway in reload mode.")
    else:
        print("Starting FeishuBot gateway.")
    print(f"URL: http://{args.host}:{args.port}")
    uvicorn.run(
        "feishubot.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "chat":
        _run_chat(args)
        return

    if args.command == "gateway":
        _run_gateway(args)
        return

    parser.print_help()


def chat_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run FeishuBot chat in terminal")
    _add_chat_arguments(parser)
    args = parser.parse_args(argv)
    _run_chat(args)


if __name__ == "__main__":
    main()