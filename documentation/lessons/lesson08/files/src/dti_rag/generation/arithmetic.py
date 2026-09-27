"""Check the model's arithmetic. The model shows its working; code does the sums.

    "£4,000 + £1,200 - £600" = "£4,600"   -> verified
    "2 × £300" = "£600"                   -> verified
    "£4,000 + £1,200 - £350" = "£4,600"   -> NOT verified

Only + - * / and brackets over plain numbers are allowed. Anything else fails verification;
nothing is ever passed to eval().
"""

from __future__ import annotations

import ast
import operator
import re
from decimal import Decimal, InvalidOperation

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_NUMBER = re.compile(r"£?\s*(\d[\d,]*(?:\.\d+)?)")


def to_number(text: str) -> Decimal | None:
    match = _NUMBER.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _normalise(expression: str) -> str:
    expr = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
    expr = re.sub(r"(?<=\d)\s*[xX]\s*(?=[£\d(])", "*", expr)
    expr = re.sub(r"£\s*", "", expr)
    return re.sub(r"(?<=\d),(?=\d{3})", "", expr)


def _evaluate(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate(node.operand)
    raise ValueError(f"unsupported expression element: {ast.dump(node)}")


def evaluate(expression: str) -> Decimal:
    return _evaluate(ast.parse(_normalise(expression), mode="eval"))


def operands(expression: str) -> list[str]:
    """The figures an expression uses, as written: ['£4,000', '£1,200', '£600']."""
    return [m.group(0).strip() for m in re.finditer(r"£\s*\d[\d,]*(?:\.\d+)?", expression)]


def verify(expression: str, result: str) -> bool:
    try:
        expected = to_number(result)
        return expected is not None and evaluate(expression) == expected
    except (ValueError, SyntaxError, ZeroDivisionError, InvalidOperation):
        return False
