"""IMBM-style BM directive store with iteration-based validity."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class BMDirective:
    phase: str
    guidance: tuple[str, ...]
    issued_at_iteration: int
    valid_until_iteration: int
    source: str = "BM"

    def is_valid(self, iteration: int) -> bool:
        return iteration <= self.valid_until_iteration

    def age(self, iteration: int) -> int:
        return max(0, iteration - self.issued_at_iteration)


class DirectiveStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: BMDirective | None = None

    def read(self, iteration: int) -> BMDirective | None:
        with self._lock:
            if self._latest is None or not self._latest.is_valid(iteration):
                return None
            return self._latest

    def write(self, directive: BMDirective) -> None:
        with self._lock:
            if (
                self._latest is None
                or directive.issued_at_iteration >= self._latest.issued_at_iteration
            ):
                self._latest = directive
