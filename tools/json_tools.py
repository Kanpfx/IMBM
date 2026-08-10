"""Small JSON extractors for common LLM response variants."""

from __future__ import annotations

import json
from typing import Any

from core.action_errors import OutputFormatError


def _json_objects(text: str):
    """Yield standard JSON objects found in plain, fenced, or prefixed text."""
    decoder = json.JSONDecoder()
    candidate = text.strip().lstrip("\ufeff")
    tried: set[int] = set()
    starts = [0, *(index for index, char in enumerate(candidate) if char == "{")]
    for start in starts:
        if start in tried:
            continue
        tried.add(start)
        try:
            payload, _ = decoder.raw_decode(candidate, start)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def parse_json_object(text: str) -> dict[str, Any]:
    """Return the first standard JSON object embedded in an LLM response."""
    try:
        return next(_json_objects(text))
    except StopIteration as exc:
        raise OutputFormatError.standard_json_required() from exc


def parse_im_payload(text: str) -> dict[str, Any]:
    """Extract and validate the exact top-level object required from IM."""
    for payload in _json_objects(text):
        if not {"actions", "request_background", "background_reason"}.issubset(
            payload
        ):
            continue
        if not isinstance(payload["actions"], list):
            raise OutputFormatError.field_type("actions", "a JSON list")
        if not isinstance(payload["request_background"], bool):
            raise OutputFormatError.field_type(
                "request_background", "a JSON boolean"
            )
        if not isinstance(payload["background_reason"], str):
            raise OutputFormatError.field_type(
                "background_reason", "a JSON string"
            )
        return {
            "actions": payload["actions"],
            "request_background": payload["request_background"],
            "background_reason": payload["background_reason"].strip(),
        }
    raise OutputFormatError.standard_json_required()
