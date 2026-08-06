"""Strict JSON extraction that also accepts legacy Markdown code fences."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as original_error:
        # A model occasionally adds a short sentence before valid JSON. This is
        # a formatting defect, not a strategic one, so recover the first JSON
        # object without attempting to repair malformed JSON.
        start = candidate.find("{")
        if start < 0:
            raise original_error
        try:
            payload, _ = json.JSONDecoder().raw_decode(candidate[start:])
        except json.JSONDecodeError:
            raise original_error
    if not isinstance(payload, dict):
        raise ValueError("response must be a JSON object")
    return payload
