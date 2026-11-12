from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from harness_retro.adapters.common import (
    as_dict,
    compact_json,
    extract_file_paths,
    extract_text,
    fallback_session_id,
    first_int,
    first_string,
    status_from_payload,
    tool_call_digest,
    usage_from,
)
from harness_retro.models import EventDraft


ADAPTER_VERSION = "claude-code-v3"


def iter_events(record: dict[str, Any], source_path: Path, line_number: int) -> Iterable[EventDraft]:
    message = as_dict(record.get("message"))
    raw_type = str(record.get("type") or message.get("type") or "unknown")
    session_id = first_string(record.get("sessionId"), record.get("session_id")) or fallback_session_id(
        "claude-code", source_path
    )
    base = {
        "session_id": session_id,
        "parent_session_id": first_string(record.get("parentSessionId"), record.get("parent_session_id")),
        "workspace_path": first_string(record.get("cwd"), record.get("workspace_path")),
        "model": first_string(message.get("model"), record.get("model")),
        "agent_kind": "subagent" if record.get("isSidechain") is True else "main",
        "timestamp": first_string(record.get("timestamp"), message.get("timestamp")),
        "raw_type": raw_type,
    }
    content = message.get("content") if message else record.get("content")
    role = first_string(message.get("role"), record.get("role"), raw_type)
    yielded = False

    input_tokens, cached_tokens, output_tokens = usage_from(message, record)
    usage_attached = False
    text = extract_text(_message_only_content(content))
    if text:
        usage_attached = True
        yielded = True
        yield EventDraft(
            actor=_actor_from_role(role),
            kind="message",
            text=text,
            status=status_from_payload(message, text),
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            file_paths=extract_file_paths(text),
            **base,
        )

    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "tool_use":
            yielded = True
            event_input_tokens = input_tokens if not usage_attached else None
            event_cached_tokens = cached_tokens if not usage_attached else None
            event_output_tokens = output_tokens if not usage_attached else None
            usage_attached = True
            yield EventDraft(
                actor="assistant",
                kind="tool_call",
                text=tool_call_digest(item.get("input")) or item.get("name"),
                tool_name=first_string(item.get("name")),
                tool_call_id=first_string(item.get("id"), item.get("tool_use_id")),
                status="unknown",
                input_tokens=event_input_tokens,
                cached_input_tokens=event_cached_tokens,
                output_tokens=event_output_tokens,
                file_paths=extract_file_paths(item.get("name"), item.get("input")),
                **base,
            )
        elif item_type == "tool_result":
            yielded = True
            result_text = extract_text(item.get("content"))
            yield EventDraft(
                actor="tool",
                kind="tool_result",
                text=result_text,
                tool_name=first_string(item.get("name")),
                tool_call_id=first_string(item.get("tool_use_id"), item.get("id")),
                status=status_from_payload(item, result_text),
                duration_ms=first_int(item.get("duration_ms"), item.get("durationMs")),
                file_paths=extract_file_paths(result_text),
                **base,
            )

    if not yielded:
        kind = "usage" if any(value is not None for value in (input_tokens, cached_tokens, output_tokens)) else "unknown"
        yield EventDraft(
            actor=_actor_from_role(role),
            kind=kind,
            text=extract_text(record) or compact_json(record),
            status=status_from_payload(record),
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            file_paths=extract_file_paths(record),
            **base,
        )


def _actor_from_role(role: str | None) -> str:
    if role in {"user", "assistant", "system", "tool"}:
        return role
    if role == "summary":
        return "system"
    return "system"


def _message_only_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    return [
        item
        for item in content
        if not (isinstance(item, dict) and item.get("type") in {"tool_use", "tool_result"})
    ]
