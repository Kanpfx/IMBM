"""Cross-frame state that has no dependency on a particular LLM provider."""

from __future__ import annotations


class TagIdMapper:
    """Compact IDs that are never reused after a unit dies."""

    def __init__(self) -> None:
        self._tag_to_id: dict[int, int] = {}
        self._id_to_tag: dict[int, int] = {}

    def alias(self, tag: int) -> str:
        if tag not in self._tag_to_id:
            candidate = tag % 1000
            while candidate in self._id_to_tag:
                candidate = (candidate + 1) % 1000
            self._tag_to_id[tag] = candidate
            self._id_to_tag[candidate] = tag
        return str(self._tag_to_id[tag])
