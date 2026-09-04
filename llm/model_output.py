"""Small, non-executing parsers for LLM response formats."""

from __future__ import annotations

import ast
import math
import re
from typing import Any

from game.actions.errors import OutputFormatError


def _tag_content(text: str, tag: str) -> str:
    pattern = re.compile(
        rf"<\s*{tag}\s*>(.*?)<\s*/\s*{tag}\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise OutputFormatError.dsl_section(tag, len(matches))
    return matches[0].strip()


def _dsl_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("numbers must be finite")
            return value
    elif isinstance(node, ast.Name):
        special = {"true": True, "false": False, "null": None, "none": None}
        return special.get(node.id.casefold(), node.id)
    elif isinstance(node, (ast.List, ast.Tuple)):
        return [_dsl_value(item) for item in node.elts]
    elif isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                raise ValueError("dictionary unpacking is not allowed")
            key = _dsl_value(key_node)
            if not isinstance(key, str):
                raise ValueError("object keys must be names or strings")
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = _dsl_value(value_node)
        return result
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _dsl_value(node.operand)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("a sign may only prefix a number")
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("unsupported value expression")


def _parse_dsl_action(source: str) -> dict[str, Any]:
    try:
        expression = ast.parse(source, mode="eval").body
    except SyntaxError as exc:
        raise OutputFormatError.dsl_action(source, "invalid function syntax") from exc

    if not isinstance(expression, ast.Call) or not isinstance(
        expression.func, ast.Name
    ):
        raise OutputFormatError.dsl_action(
            source, "expected ActionName(argument=value, ...)"
        )
    if expression.args:
        raise OutputFormatError.dsl_action(
            source, "positional arguments are not allowed"
        )

    args: dict[str, Any] = {}
    normalized_names: set[str] = set()
    for keyword in expression.keywords:
        if keyword.arg is None:
            raise OutputFormatError.dsl_action(
                source, "argument unpacking is not allowed"
            )
        normalized = "".join(
            character for character in keyword.arg.casefold() if character.isalnum()
        )
        if normalized in normalized_names:
            raise OutputFormatError.dsl_action(
                source, f"duplicate argument {keyword.arg!r}"
            )
        normalized_names.add(normalized)
        try:
            args[keyword.arg] = _dsl_value(keyword.value)
        except ValueError as exc:
            raise OutputFormatError.dsl_action(source, str(exc)) from exc
    return {"id": expression.func.id, "args": args}


def parse_model_payload(text: str) -> dict[str, Any]:
    """Parse the tagged model DSL while retaining valid sibling actions."""
    candidate = text.strip().lstrip("\ufeff")
    phase = _tag_content(candidate, "phase")
    if len(phase) >= 2 and phase[0] == phase[-1] and phase[0] in {"'", '"', "`"}:
        phase = phase[1:-1].strip()

    actions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    action_lines = [
        line.strip()
        for line in _tag_content(candidate, "actions").splitlines()
        if line.strip()
    ]
    for index, original in enumerate(action_lines):
        source = original
        if source.startswith("- "):
            source = source[2:].lstrip()
        if source.endswith((",", ";")):
            source = source[:-1].rstrip()
        try:
            actions.append(_parse_dsl_action(source))
        except OutputFormatError as exc:
            errors.append(
                {
                    "index": index,
                    "submitted_action": original,
                    "error": str(exc),
                }
            )
    return {"phase": phase, "actions": actions, "errors": errors}
