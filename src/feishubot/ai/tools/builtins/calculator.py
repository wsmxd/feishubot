from __future__ import annotations

import ast
import operator as operator_module
from typing import Any

from pydantic import BaseModel, Field

from feishubot.ai.tools.base import Tool

_ALLOWED_BINARY_OPERATORS: dict[type[ast.AST], Any] = {
    ast.Add: operator_module.add,
    ast.Sub: operator_module.sub,
    ast.Mult: operator_module.mul,
    ast.Div: operator_module.truediv,
    ast.FloorDiv: operator_module.floordiv,
    ast.Mod: operator_module.mod,
    ast.Pow: operator_module.pow,
}

_ALLOWED_UNARY_OPERATORS: dict[type[ast.AST], Any] = {
    ast.UAdd: operator_module.pos,
    ast.USub: operator_module.neg,
}


def _safe_eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        operator = _ALLOWED_BINARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise ValueError("unsupported operator")
        return operator(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        operator = _ALLOWED_UNARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise ValueError("unsupported operator")
        return operator(_safe_eval(node.operand))
    raise ValueError("unsupported expression")


class CalculatorArguments(BaseModel):
    expression: str = Field(
        min_length=1, description="Arithmetic expression to evaluate"
    )


class CalculatorTool(Tool):
    name = "calculator"
    description = "Evaluate simple arithmetic expressions."
    args_model = CalculatorArguments

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        expression = str(arguments.get("expression", "")).strip()

        parsed = ast.parse(expression, mode="eval")
        result = _safe_eval(parsed)
        return {"expression": expression, "result": result}
