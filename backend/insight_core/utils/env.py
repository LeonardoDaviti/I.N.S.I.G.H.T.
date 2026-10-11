"""Numbers from the environment: a tuning knob that is unset, empty or not a number falls
back to its default, so a typo in .env never stops the app."""
from __future__ import annotations

import os
from typing import Callable, Optional, TypeVar

N = TypeVar("N", int, float)


def _env_number(name: str, default: N, cast: Callable[[str], N], minimum: Optional[N]) -> N:
    raw = os.getenv(name)
    try:
        value = cast(raw) if raw else cast(default)
    except ValueError:
        return cast(default)
    return max(minimum, value) if minimum is not None else value


def env_int(name: str, default: int, *, minimum: Optional[int] = None) -> int:
    """int(os.environ[name]), at least `minimum` when given; `default` when unset or not an int."""
    return _env_number(name, default, int, minimum)


def env_float(name: str, default: float, *, minimum: Optional[float] = None) -> float:
    """float(os.environ[name]), at least `minimum` when given; `default` when unset or not a number."""
    return _env_number(name, default, float, minimum)
