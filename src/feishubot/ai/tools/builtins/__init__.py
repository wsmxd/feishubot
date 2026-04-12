from feishubot.ai.tools.builtins.calculator import CalculatorTool
from feishubot.ai.tools.builtins.soul import SoulMemoryTool
from feishubot.ai.tools.builtins.terminal import TerminalCommandTool
from feishubot.ai.tools.builtins.web_search import WebSearchTool
from feishubot.ai.tools.registry import tool_registry


def register_builtin_tools() -> None:
    if tool_registry.get(CalculatorTool.name) is None:
        tool_registry.register(CalculatorTool.name, CalculatorTool())
    if tool_registry.get(TerminalCommandTool.name) is None:
        tool_registry.register(TerminalCommandTool.name, TerminalCommandTool())
    if tool_registry.get(SoulMemoryTool.name) is None:
        tool_registry.register(SoulMemoryTool.name, SoulMemoryTool())
    if tool_registry.get(WebSearchTool.name) is None:
        tool_registry.register(WebSearchTool.name, WebSearchTool())


__all__ = [
    "CalculatorTool",
    "SoulMemoryTool",
    "TerminalCommandTool",
    "WebSearchTool",
    "register_builtin_tools",
]
