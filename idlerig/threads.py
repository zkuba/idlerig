"""Thread specification: how many mining threads to use in each activity state.

The ``--threads`` option takes up to three comma-separated values in the
order ``active,idle,away``. Each value is either an absolute thread count
(``4``) or a share of the logical CPUs (``50%``). Missing values repeat the
last one, so ``-t 2`` means two threads in every state.

A value of ``0`` (or ``0%``) pauses mining in that state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Union

STATES = ("active", "idle", "away")

Value = Union[int, float]  # int = absolute threads, float = fraction of CPUs (0.0-1.0)


def cpu_count() -> int:
    return os.cpu_count() or 1


def _parse_value(text: str) -> Value:
    text = text.strip()
    if text.endswith("%"):
        try:
            pct = float(text[:-1])
        except ValueError:
            raise ValueError(f"invalid percentage: {text!r}") from None
        if not 0 <= pct <= 100:
            raise ValueError(f"percentage out of range 0-100: {text!r}")
        return pct / 100.0
    try:
        n = int(text)
    except ValueError:
        raise ValueError(f"invalid thread count: {text!r} (use e.g. 4 or 50%)") from None
    if n < 0:
        raise ValueError(f"thread count must not be negative: {text!r}")
    return n


@dataclass(frozen=True)
class ThreadSpec:
    active: Value
    idle: Value
    away: Value
    text: str = ""

    @classmethod
    def parse(cls, text: str) -> "ThreadSpec":
        parts = [p for p in (text or "").split(",") if p.strip()]
        if not parts:
            raise ValueError("thread spec is empty")
        if len(parts) > 3:
            raise ValueError(f"thread spec has more than 3 values: {text!r}")
        values = [_parse_value(p) for p in parts]
        while len(values) < 3:
            values.append(values[-1])
        return cls(*values, text=text.strip())

    def value_for(self, state: str) -> Value:
        if state not in STATES:
            raise ValueError(f"unknown state: {state!r}")
        return getattr(self, state)

    def resolve(self, state: str, cpus: Optional[int] = None) -> int:
        """Number of threads for ``state``; 0 means mining should be paused."""
        cpus = cpus or cpu_count()
        value = self.value_for(state)
        if isinstance(value, float):
            if value <= 0:
                return 0
            # Round half up (same as the web UI's Math.round), not Python's banker's rounding.
            return min(cpus, max(1, int(value * cpus + 0.5)))
        return min(cpus, value)

    def __str__(self) -> str:
        return self.text or ",".join(
            f"{v * 100:g}%" if isinstance(v, float) else str(v)
            for v in (self.active, self.idle, self.away)
        )
