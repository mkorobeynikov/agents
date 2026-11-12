from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_retro.config import Config
from harness_retro.models import SourceSpec


def discover_sources(config: Config, since: datetime | None = None) -> list[SourceSpec]:
    sources: list[SourceSpec] = []
    for root in config.codex_paths:
        sources.extend(_discover(root, "codex", since))
    for root in config.claude_paths:
        sources.extend(_discover(root, "claude-code", since))
    return sorted(sources, key=lambda item: str(item.path))


def _discover(root: Path, harness: str, since: datetime | None) -> list[SourceSpec]:
    if not root.exists():
        return []
    paths = [root] if root.is_file() else root.rglob("*.jsonl")
    result: list[SourceSpec] = []
    for path in paths:
        if not path.is_file() or path.name.startswith("."):
            continue
        if since is not None:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < since:
                continue
        result.append(SourceSpec(path=path.resolve(), harness=harness))
    return result
