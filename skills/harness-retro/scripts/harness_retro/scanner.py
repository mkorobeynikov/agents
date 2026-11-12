from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from harness_retro.adapters import get_adapter
from harness_retro.config import Config
from harness_retro.discovery import discover_sources
from harness_retro.models import EventDraft, SourceSpec
from harness_retro.redact import redact_text
from harness_retro.store import (
    clear_source_import,
    get_source,
    insert_event,
    mark_missing_sources,
    save_session_meta,
    sha256_file,
    sha256_prefix,
    stable_id,
    update_session_bounds,
    upsert_source,
)


def estimate_sources(config: Config, since: datetime | None = None) -> dict[str, Any]:
    sources = discover_sources(config, since)
    by_harness: dict[str, dict[str, int]] = {}
    total_bytes = 0
    for source in sources:
        size = source.path.stat().st_size
        total_bytes += size
        stats = by_harness.setdefault(source.harness, {"files": 0, "bytes": 0})
        stats["files"] += 1
        stats["bytes"] += size
    estimated_model_payload_chars = min(total_bytes, config.limits.session_chars * len(sources))
    return {
        "source_files": len(sources),
        "total_bytes": total_bytes,
        "by_harness": by_harness,
        "estimated_model_payload_chars": estimated_model_payload_chars,
        "data_boundary": data_boundary_message(),
    }


def scan_sources(
    conn: sqlite3.Connection,
    config: Config,
    since: datetime | None = None,
) -> dict[str, Any]:
    sources = discover_sources(config, since)
    stats = {
        "discovered_sources": len(sources),
        "imported_sources": 0,
        "unchanged_sources": 0,
        "reimported_sources": 0,
        "appended_sources": 0,
        "imported_events": 0,
        "parse_warnings": 0,
        "missing_sources_marked": 0,
    }
    for source in sources:
        result = scan_source(conn, config, source)
        for key in ("imported_events", "parse_warnings"):
            stats[key] += result[key]
        if result["mode"] == "unchanged":
            stats["unchanged_sources"] += 1
        elif result["mode"] == "append":
            stats["appended_sources"] += 1
            stats["imported_sources"] += 1
        elif result["mode"] == "reimport":
            stats["reimported_sources"] += 1
            stats["imported_sources"] += 1
        elif result["mode"] == "import":
            stats["imported_sources"] += 1
    stats["missing_sources_marked"] = mark_missing_sources(conn, [source.path for source in sources])
    conn.commit()
    return stats


def scan_source(conn: sqlite3.Connection, config: Config, source: SourceSpec) -> dict[str, Any]:
    adapter_version, adapter = get_adapter(source.harness)
    stat = source.path.stat()
    source_fingerprint = sha256_file(source.path)
    existing = get_source(conn, source.path)
    if (
        existing
        and existing["source_fingerprint"] == source_fingerprint
        and existing["offset"] == stat.st_size
        and existing["adapter_version"] == adapter_version
    ):
        return {"mode": "unchanged", "imported_events": 0, "parse_warnings": 0}

    mode = "import"
    start_offset = 0
    start_line = 0
    if existing and existing["adapter_version"] == adapter_version:
        stored_offset = int(existing["offset"])
        if stat.st_size >= stored_offset and stored_offset > 0:
            prefix_fingerprint = sha256_prefix(source.path, stored_offset)
            if prefix_fingerprint == existing["processed_fingerprint"]:
                mode = "append"
                start_offset = stored_offset
                start_line = int(existing["line_count"])
            else:
                mode = "reimport"
                clear_source_import(conn, source.path)
        else:
            mode = "reimport"
            clear_source_import(conn, source.path)
    elif existing:
        mode = "reimport"
        clear_source_import(conn, source.path)

    parse_warnings = []
    imported_events = 0
    last_offset, line_count = _line_cursor(source.path, start_offset, start_line)
    with source.path.open("rb") as handle:
        handle.seek(start_offset)
        offset = start_offset
        line_number = start_line
        for raw_line in handle:
            offset += len(raw_line)
            line_number += 1
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                parse_warnings.append(f"{source.path}:{line_number}: {exc}")
                continue
            if not isinstance(record, dict):
                parse_warnings.append(f"{source.path}:{line_number}: expected JSON object")
                continue
            try:
                drafts = list(adapter(record, source.path, line_number))
            except Exception as exc:
                parse_warnings.append(f"{source.path}:{line_number}: adapter error: {exc}")
                continue
            for subindex, draft in enumerate(drafts):
                event = _event_from_draft(
                    draft,
                    source=source,
                    source_fingerprint=source_fingerprint,
                    raw_line=raw_line,
                    line_number=line_number,
                    subindex=subindex,
                    sequence=line_number * 1000 + subindex,
                    config=config,
                )
                insert_event(conn, event)
                save_session_meta(
                    conn,
                    session_id=draft.session_id,
                    harness=source.harness,
                    source_path=source.path,
                    source_fingerprint=source_fingerprint,
                    parent_session_id=draft.parent_session_id,
                    workspace_path=draft.workspace_path,
                    model=draft.model,
                    agent_kind=draft.agent_kind,
                    parse_warnings=parse_warnings,
                )
                imported_events += 1
            last_offset = offset
            line_count = line_number
    processed_fingerprint = sha256_prefix(source.path, last_offset)
    upsert_source(
        conn,
        path=source.path,
        harness=source.harness,
        size=stat.st_size,
        mtime=stat.st_mtime,
        source_fingerprint=source_fingerprint,
        processed_fingerprint=processed_fingerprint,
        offset=last_offset,
        line_count=line_count,
        adapter_version=adapter_version,
        parse_warnings=parse_warnings,
    )
    update_session_bounds(conn, source.path)
    return {
        "mode": mode,
        "imported_events": imported_events,
        "parse_warnings": len(parse_warnings),
    }


def data_boundary_message() -> str:
    return (
        "Local steps: discovery, parsing, redaction, SQLite storage, deterministic metrics. "
        "Provider-backed analysis may send selected redacted excerpts outside this machine; "
        "use --deterministic-only to avoid that boundary."
    )


def _event_from_draft(
    draft: EventDraft,
    *,
    source: SourceSpec,
    source_fingerprint: str,
    raw_line: bytes,
    line_number: int,
    subindex: int,
    sequence: int,
    config: Config,
) -> dict[str, Any]:
    redacted = redact_text(draft.text, config.redaction_regexes)
    raw_hash = hashlib.sha256(raw_line).hexdigest()
    event_id = stable_id(str(source.path), line_number, subindex, draft.session_id, raw_hash)
    return {
        "event_id": event_id,
        "session_id": draft.session_id,
        "sequence": sequence,
        "timestamp": draft.timestamp,
        "actor": _safe_value(draft.actor, {"user", "assistant", "tool", "system"}, "system"),
        "kind": _safe_value(
            draft.kind,
            {"message", "reasoning", "tool_call", "tool_result", "approval", "edit", "usage", "lifecycle", "unknown"},
            "unknown",
        ),
        "text": redacted.text,
        "tool_name": draft.tool_name,
        "tool_call_id": draft.tool_call_id,
        "status": _safe_value(
            draft.status,
            {"success", "failure", "denied", "interrupted", "unknown"},
            "unknown",
        ),
        "duration_ms": draft.duration_ms,
        "input_tokens": draft.input_tokens,
        "cached_input_tokens": draft.cached_input_tokens,
        "output_tokens": draft.output_tokens,
        "file_paths": draft.file_paths,
        "source_locator_path": str(source.path),
        "source_locator_line": line_number,
        "redaction_tags": redacted.tags,
        "raw_type": draft.raw_type,
        "source_fingerprint": source_fingerprint,
    }


def _safe_value(value: str, allowed: set[str], fallback: str) -> str:
    return value if value in allowed else fallback


def _line_cursor(path: Path, offset: int, line_count: int) -> tuple[int, int]:
    if offset == 0:
        return 0, 0
    return offset, line_count
