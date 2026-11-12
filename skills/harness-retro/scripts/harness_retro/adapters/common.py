from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


PATH_RE = re.compile(r"(?:~|/Users|/private|/tmp|/var|[A-Za-z0-9_.-]+/)[^\s'\"`),;]+")
PROCESS_EXIT_CODE_RE = re.compile(r"(?im)^\s*process exited with code\s+(-?\d+)\s*$")


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def fallback_session_id(harness: str, source_path: Path) -> str:
    return f"{harness}:{stable_hash(str(source_path.resolve()))}"


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def compact_json(value: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = repr(value)
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n...[truncated]...\n{tail}"


def extract_text(value: Any) -> str | None:
    parts = list(_iter_text(value))
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    return text or None


def _iter_text(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_text(item)
        return
    if isinstance(value, dict):
        item_type = str(value.get("type") or "")
        if item_type in {"tool_use", "function_call"}:
            return
        if "text" in value:
            yield from _iter_text(value.get("text"))
        elif "content" in value:
            yield from _iter_text(value.get("content"))
        elif "output" in value:
            yield from _iter_text(value.get("output"))
        elif "message" in value:
            yield from _iter_text(value.get("message"))


def extract_file_paths(*values: Any) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = extract_text(value) if not isinstance(value, str) else value
        if not text:
            continue
        for match in PATH_RE.findall(text):
            path = match.rstrip(":")
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def status_from_payload(payload: dict[str, Any], text: str | None = None) -> str:
    status = str(payload.get("status") or payload.get("result") or "").lower()
    if status in {"success", "succeeded", "ok", "passed"}:
        return "success"
    if status in {"failure", "failed", "error"}:
        return "failure"
    if status in {"denied", "rejected"}:
        return "denied"
    if status in {"interrupted", "cancelled", "canceled"}:
        return "interrupted"
    if payload.get("is_error") is True or payload.get("error") is not None:
        return "failure"
    if payload.get("is_error") is False:
        return "success"
    exit_code = payload.get("exit_code")
    if exit_code is None:
        exit_code = payload.get("exitCode")
    if isinstance(exit_code, int):
        return "success" if exit_code == 0 else "failure"
    if text:
        lowered = text.lower()
        if "permission denied" in lowered or "user denied" in lowered:
            return "denied"
        process_exit = PROCESS_EXIT_CODE_RE.search(text)
        if process_exit:
            return "success" if int(process_exit.group(1)) == 0 else "failure"
    return "unknown"


def usage_from(*objects: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    for obj in objects:
        usage = as_dict(obj.get("usage"))
        if not usage:
            continue
        input_tokens = first_int(
            usage.get("input_tokens"),
            usage.get("prompt_tokens"),
            usage.get("inputTokens"),
        )
        cached = first_int(
            usage.get("cached_input_tokens"),
            usage.get("cached_tokens"),
            usage.get("cache_read_input_tokens"),
            as_dict(usage.get("input_tokens_details")).get("cached_tokens"),
        )
        output_tokens = first_int(
            usage.get("output_tokens"),
            usage.get("completion_tokens"),
            usage.get("outputTokens"),
        )
        return input_tokens, cached, output_tokens
    return None, None, None


def tool_call_digest(tool_input: Any) -> str | None:
    if tool_input in (None, "", {}, []):
        return None
    return compact_json(tool_input)
