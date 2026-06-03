from dataclasses import dataclass
from threading import Lock
from typing import Optional


@dataclass
class Directive:
    data: dict
    issued_at_tick: int
    valid_until_tick: int
    source: str = "BM"

    def is_valid(self, current_tick: int) -> bool:
        return current_tick <= self.valid_until_tick

    def age(self, current_tick: int) -> int:
        return max(0, current_tick - self.issued_at_tick)

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "issued_at_tick": self.issued_at_tick,
            "valid_until_tick": self.valid_until_tick,
            "source": self.source,
        }


class DirectiveStore:
    def __init__(self):
        self._lock = Lock()
        self._latest: Optional[Directive] = None

    def read(self, current_tick: int) -> Optional[Directive]:
        with self._lock:
            if self._latest is None:
                return None
            if not self._latest.is_valid(current_tick):
                return None
            return Directive(
                data=dict(self._latest.data),
                issued_at_tick=self._latest.issued_at_tick,
                valid_until_tick=self._latest.valid_until_tick,
                source=self._latest.source,
            )

    def latest(self) -> Optional[Directive]:
        with self._lock:
            if self._latest is None:
                return None
            return Directive(
                data=dict(self._latest.data),
                issued_at_tick=self._latest.issued_at_tick,
                valid_until_tick=self._latest.valid_until_tick,
                source=self._latest.source,
            )

    def write(self, directive: Directive) -> None:
        with self._lock:
            if self._latest is None or directive.issued_at_tick >= self._latest.issued_at_tick:
                self._latest = directive
