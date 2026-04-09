from feishubot.ai.tools.builtins.calculator import CalculatorTool
from feishubot.ai.tools.builtins.terminal import TerminalCommandTool
from feishubot.ai.tools.registry import tool_registry


def register_builtin_tools() -> None:
    if tool_registry.get(CalculatorTool.name) is None:
        tool_registry.register(CalculatorTool.name, CalculatorTool())
    if tool_registry.get(TerminalCommandTool.name) is None:
        tool_registry.register(TerminalCommandTool.name, TerminalCommandTool())


__all__ = ["CalculatorTool", "TerminalCommandTool", "register_builtin_tools"]
