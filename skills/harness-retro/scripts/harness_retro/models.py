from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceSpec:
    path: Path
    harness: str


@dataclass
class EventDraft:
    session_id: str
    parent_session_id: str | None
    workspace_path: str | None
    model: str | None
    agent_kind: str
    timestamp: str | None
    actor: str
    kind: str
    text: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    status: str = "unknown"
    duration_ms: int | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    file_paths: list[str] = field(default_factory=list)
    raw_type: str = "unknown"
