from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from harness_retro.adapters import claude_code, codex
from harness_retro.models import EventDraft


Adapter = Callable[[dict[str, Any], Path, int], Iterable[EventDraft]]

ADAPTERS: dict[str, tuple[str, Adapter]] = {
    "codex": (codex.ADAPTER_VERSION, codex.iter_events),
    "claude-code": (claude_code.ADAPTER_VERSION, claude_code.iter_events),
}


def get_adapter(harness: str) -> tuple[str, Adapter]:
    try:
        return ADAPTERS[harness]
    except KeyError as exc:
        raise ValueError(f"Unsupported harness: {harness}") from exc
