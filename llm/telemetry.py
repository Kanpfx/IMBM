"""Per-match JSONL trace writer that deliberately never receives credentials."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class Telemetry:
    """Keep observation, conversations and accepted decisions separate.

    A single instance belongs to one match.  The directory name is timestamped
    so later matches can never overwrite an earlier trace.
    """

    def __init__(
        self,
        metadata: dict[str, Any] | None = None,
        root: Path = Path("logs"),
        directory: Path | None = None,
    ):
        if directory is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.directory = root / timestamp
            self.directory.mkdir(parents=True, exist_ok=False)
        else:
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)
        self._metadata = dict(metadata or {})
        self._write_json("metadata.json", self._metadata)
        for filename in (
            "obs.jsonl",
            "im.jsonl",
            "bm.jsonl",
            "correction.jsonl",
            "accepted_actions.jsonl",
            "events.jsonl",
        ):
            (self.directory / filename).touch()

    def event(self, name: str, **fields: Any) -> None:
        self._append("events.jsonl", {"event": name, **fields})

    def observation(self, **fields: Any) -> None:
        self._append("obs.jsonl", fields)

    def im_conversation(self, **fields: Any) -> None:
        self._append("im.jsonl", fields)

    def bm_conversation(self, **fields: Any) -> None:
        self._append("bm.jsonl", fields)

    def correction_conversation(self, **fields: Any) -> None:
        self._append("correction.jsonl", fields)

    def accepted_decision(self, **fields: Any) -> None:
        self._append("accepted_actions.jsonl", fields)

    def update_metadata(self, **fields: Any) -> None:
        """Merge match-final fields without changing any JSONL trace."""
        self._metadata.update(fields)
        self._write_json("metadata.json", self._metadata)

    def _append(self, filename: str, fields: dict[str, Any]) -> None:
        with (self.directory / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fields, ensure_ascii=False, default=str) + "\n")

    def _write_json(self, filename: str, fields: dict[str, Any]) -> None:
        with (self.directory / filename).open("w", encoding="utf-8") as handle:
            json.dump(fields, handle, ensure_ascii=False, indent=2, default=str)
