"""Tools for the fixed demo bot: no code execution, no shell, side effects need a verified human approval.

The chat bot never calls send_email; it is here to show the approval pattern the audit checks for.
"""

from __future__ import annotations

import ast
import hmac
import operator
import secrets
from dataclasses import dataclass

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

VERIFIED_OPERATORS = frozenset({"ops-lead@asterion.example"})


def calculator(expression: str) -> float:
    """Arithmetic only: numbers and + - * /."""

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError("unsupported expression")

    return visit(ast.parse(expression, mode="eval").body)


@dataclass(frozen=True)
class Approval:
    operator: str
    action: str


_PENDING: dict[str, Approval] = {}


def approve(operator: str, action: str) -> str:
    """Called from the operator console (authenticated), never from model output. Returns a single-use token."""
    if operator not in VERIFIED_OPERATORS:
        raise PermissionError("only verified operators can approve actions")
    token = secrets.token_urlsafe(16)
    _PENDING[token] = Approval(operator, action)
    return token


def _consume_confirmation(token: str, action: str) -> Approval:
    for known in list(_PENDING):
        if hmac.compare_digest(known, token):
            approval = _PENDING.pop(known)
            if approval.action != action:
                raise PermissionError("approval was issued for a different action")
            return approval
    raise PermissionError("send_email needs a valid, unused approval token from a verified operator")


def send_email(to: str, subject: str, body: str, *, confirmation_token: str) -> str:
    approval = _consume_confirmation(confirmation_token, f"send_email:{to}")
    return f"queued email to {to} (approved by {approval.operator})"
