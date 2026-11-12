from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class ProviderStatus:
    name: str
    available: bool
    detail: str


def codex_provider_status() -> ProviderStatus:
    path = shutil.which("codex")
    if not path:
        return ProviderStatus(
            name="codex",
            available=False,
            detail="Codex CLI was not found on PATH. Deterministic-only analysis is available.",
        )
    return ProviderStatus(
        name="codex",
        available=True,
        detail=(
            f"Codex CLI found at {path}. Provider-backed extraction is not invoked by the MVP "
            "without a separate opt-in path."
        ),
    )
