from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path("~/.local/share/harness-retro").expanduser()
DEFAULT_CODEX_SESSIONS = Path("~/.codex/sessions").expanduser()
DEFAULT_CLAUDE_PROJECTS = Path("~/.claude/projects").expanduser()


@dataclass
class Limits:
    session_chars: int = 30_000
    nightly_session_limit: int = 50
    weekly_findings_limit: int = 20
    oversized_output_chars: int = 20_000


@dataclass
class Config:
    data_dir: Path = DEFAULT_DATA_DIR
    codex_paths: list[Path] = field(default_factory=lambda: [DEFAULT_CODEX_SESSIONS])
    claude_paths: list[Path] = field(default_factory=lambda: [DEFAULT_CLAUDE_PROJECTS])
    report_absolute_paths: bool = False
    redaction_regexes: list[str] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)


def load_config(
    config_path: str | None = None,
    data_dir: str | None = None,
    codex_path: list[str] | None = None,
    claude_path: list[str] | None = None,
    report_absolute_paths: bool | None = None,
    redaction_regex: list[str] | None = None,
) -> Config:
    raw = _read_config(config_path)
    limits_raw = raw.get("limits", {})
    config = Config(
        data_dir=_path(
            data_dir
            or os.getenv("HARNESS_RETRO_DATA_DIR")
            or raw.get("data_dir")
            or DEFAULT_DATA_DIR
        ),
        codex_paths=_path_list(
            codex_path
            or _split_env("HARNESS_RETRO_CODEX_SESSIONS")
            or raw.get("codex_paths")
            or raw.get("codex_sessions")
            or [DEFAULT_CODEX_SESSIONS]
        ),
        claude_paths=_path_list(
            claude_path
            or _split_env("HARNESS_RETRO_CLAUDE_PROJECTS")
            or raw.get("claude_paths")
            or raw.get("claude_projects")
            or [DEFAULT_CLAUDE_PROJECTS]
        ),
        report_absolute_paths=(
            report_absolute_paths
            if report_absolute_paths is not None
            else bool(raw.get("report_absolute_paths", False))
        ),
        redaction_regexes=list(raw.get("redaction_regexes", [])) + list(redaction_regex or []),
        limits=Limits(
            session_chars=int(limits_raw.get("session_chars", Limits.session_chars)),
            nightly_session_limit=int(
                limits_raw.get("nightly_session_limit", Limits.nightly_session_limit)
            ),
            weekly_findings_limit=int(
                limits_raw.get("weekly_findings_limit", Limits.weekly_findings_limit)
            ),
            oversized_output_chars=int(
                limits_raw.get("oversized_output_chars", Limits.oversized_output_chars)
            ),
        ),
    )
    return config


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    now = datetime.now(timezone.utc)
    if value.endswith("d") and value[:-1].isdigit():
        return now - timedelta(days=int(value[:-1]))
    if value.endswith("h") and value[:-1].isdigit():
        return now - timedelta(hours=int(value[:-1]))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"Unsupported --since value: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_config(config_path: str | None) -> dict[str, Any]:
    path_value = config_path or os.getenv("HARNESS_RETRO_CONFIG")
    if not path_value:
        default_path = DEFAULT_DATA_DIR / "config.json"
        if not default_path.exists():
            return {}
        path = default_path
    else:
        path = _path(path_value)
    if not path.exists():
        raise SystemExit(f"Config file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _path_list(value: Any) -> list[Path]:
    if isinstance(value, (str, Path)):
        return [_path(value)]
    return [_path(item) for item in value]


def _split_env(name: str) -> list[str] | None:
    value = os.getenv(name)
    if not value:
        return None
    return [part for part in value.split(os.pathsep) if part]
