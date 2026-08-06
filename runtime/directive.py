"""IMBM-style BM directive store with frame validity."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class BMDirective:
    phase: str
    guidance: tuple[str, ...]
    issued_at_loop: int
    valid_until_loop: int
    source: str = "BM"

    def is_valid(self, loop: int) -> bool:
        return loop <= self.valid_until_loop

    def age(self, loop: int) -> int:
        return max(0, loop - self.issued_at_loop)


class DirectiveStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: BMDirective | None = None

    def read(self, loop: int) -> BMDirective | None:
        with self._lock:
            if self._latest is None or not self._latest.is_valid(loop):
                return None
            return self._latest

    def write(self, directive: BMDirective) -> None:
        with self._lock:
            if self._latest is None or directive.issued_at_loop >= self._latest.issued_at_loop:
                self._latest = directive

