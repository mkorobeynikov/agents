from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from harness_retro.adapters.common import (
    as_dict,
    compact_json,
    extract_file_paths,
    extract_text,
    fallback_session_id,
    first_string,
    status_from_payload,
    tool_call_digest,
    usage_from,
)
from harness_retro.models import EventDraft


ADAPTER_VERSION = "codex-v2"


def iter_events(record: dict[str, Any], source_path: Path, line_number: int) -> Iterable[EventDraft]:
    payload = as_dict(record.get("payload"))
    item = as_dict(payload.get("item")) or as_dict(record.get("item")) or payload or record
    message = as_dict(item.get("message")) or as_dict(record.get("message"))
    raw_type = str(
        record.get("type")
        or payload.get("type")
        or item.get("type")
        or message.get("type")
        or "unknown"
    )
    session_id = first_string(
        record.get("session_id"),
        record.get("sessionId"),
        payload.get("session_id"),
        payload.get("sessionId"),
        item.get("session_id"),
        item.get("sessionId"),
    ) or fallback_session_id("codex", source_path)
    base = {
        "session_id": session_id,
        "parent_session_id": first_string(
            record.get("parent_session_id"),
            record.get("parentSessionId"),
            payload.get("parent_session_id"),
            payload.get("parentSessionId"),
        ),
        "workspace_path": first_string(
            record.get("cwd"),
            record.get("workspace_path"),
            payload.get("cwd"),
            payload.get("workspace_path"),
            as_dict(payload.get("context")).get("cwd"),
        ),
        "model": first_string(
            record.get("model"),
            payload.get("model"),
            item.get("model"),
            message.get("model"),
        ),
        "agent_kind": "subagent"
        if any(bool(obj.get("is_subagent") or obj.get("subagent")) for obj in (record, payload, item))
        else "main",
        "timestamp": first_string(
            record.get("timestamp"),
            record.get("created_at"),
            payload.get("timestamp"),
            payload.get("created_at"),
            item.get("timestamp"),
        ),
        "raw_type": raw_type,
    }

    yielded = False
    target = message or item
    item_type = str(target.get("type") or payload.get("type") or raw_type)

    if item_type in {"function_call", "tool_call", "tool_use"}:
        yielded = True
        yield _tool_call_event(base, target)

    if item_type in {"function_call_output", "tool_result", "tool_output"}:
        yielded = True
        yield _tool_result_event(base, target)

    role = first_string(target.get("role"), item.get("role"), record.get("role"))
    text = extract_text(
        target.get("content")
        if "content" in target
        else target.get("text")
        or target.get("output")
        or record.get("content")
    )
    if text and item_type not in {"function_call_output", "tool_result", "tool_output"}:
        input_tokens, cached_tokens, output_tokens = usage_from(target, item, payload, record)
        yielded = True
        yield EventDraft(
            actor=_actor_from_role(role),
            kind="message",
            text=text,
            status=status_from_payload(target, text),
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            file_paths=extract_file_paths(text),
            **base,
        )

    for call in _tool_calls(target, item, record):
        yielded = True
        yield _tool_call_event(base, call)

    if not yielded:
        input_tokens, cached_tokens, output_tokens = usage_from(target, item, payload, record)
        kind = "usage" if any(value is not None for value in (input_tokens, cached_tokens, output_tokens)) else "unknown"
        yield EventDraft(
            actor="system",
            kind=kind,
            text=extract_text(target) or compact_json(target if target else record),
            status=status_from_payload(target),
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            file_paths=extract_file_paths(target),
            **base,
        )


def _actor_from_role(role: str | None) -> str:
    if role in {"user", "assistant", "system", "tool"}:
        return role
    return "system"


def _tool_calls(*objects: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for obj in objects:
        calls = obj.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict):
                    yield call
        content = obj.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"tool_use", "function_call"}:
                    yield item


def _tool_call_event(base: dict[str, Any], payload: dict[str, Any]) -> EventDraft:
    function = as_dict(payload.get("function"))
    name = first_string(
        payload.get("name"),
        payload.get("tool_name"),
        function.get("name"),
        payload.get("recipient_name"),
    )
    arguments = (
        payload.get("input")
        if "input" in payload
        else payload.get("arguments")
        if "arguments" in payload
        else function.get("arguments")
    )
    text = tool_call_digest(arguments) or name
    return EventDraft(
        actor="assistant",
        kind="tool_call",
        text=text,
        tool_name=name,
        tool_call_id=first_string(
            payload.get("call_id"),
            payload.get("tool_call_id"),
            payload.get("id"),
            payload.get("tool_use_id"),
        ),
        status=status_from_payload(payload),
        file_paths=extract_file_paths(name, text),
        **base,
    )


def _tool_result_event(base: dict[str, Any], payload: dict[str, Any]) -> EventDraft:
    text = extract_text(
        payload.get("output")
        if "output" in payload
        else payload.get("content")
        or payload.get("result")
    )
    return EventDraft(
        actor="tool",
        kind="tool_result",
        text=text,
        tool_name=first_string(payload.get("name"), payload.get("tool_name")),
        tool_call_id=first_string(
            payload.get("call_id"),
            payload.get("tool_call_id"),
            payload.get("tool_use_id"),
            payload.get("id"),
        ),
        status=status_from_payload(payload, text),
        file_paths=extract_file_paths(text),
        **base,
    )
