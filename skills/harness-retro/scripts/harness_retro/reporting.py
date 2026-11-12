from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_retro.config import Config
from harness_retro.metrics import build_metrics
from harness_retro.store import json_load


def write_weekly_report(
    conn: sqlite3.Connection,
    config: Config,
    since: datetime | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    output_dir = output_dir or (config.data_dir / "reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)
    metrics = build_metrics(conn, since)
    candidates = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM candidates
            WHERE state != 'stale'
            ORDER BY
                CASE impact
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    ELSE 3
                END,
                affected_sessions DESC,
                updated_at DESC
            """
        ).fetchall()
    ]
    findings_by_id = {
        row["finding_id"]: dict(row)
        for row in conn.execute("SELECT * FROM findings").fetchall()
    }
    payload = {
        "schema_version": "0.1",
        "generated_at": generated_at.isoformat(),
        "since": since.isoformat() if since else None,
        "metrics": metrics,
        "candidates": [_candidate_json(candidate) for candidate in candidates],
        "limitations": [
            "MVP uses deterministic extractors; provider-backed episode extraction is not enabled by default.",
            "Unknown and schema-drifted events are preserved as unknown signals where possible.",
            "Absence of verification in logs can mean either no verification happened or it was not recorded.",
            (
                "New-skill discovery currently detects repeated ordered compositions of explicitly invoked skills; "
                "it does not semantically cluster arbitrary natural-language workflows."
            ),
        ],
    }
    date_slug = generated_at.date().isoformat()
    json_path = output_dir / f"weekly-{date_slug}.json"
    md_path = output_dir / f"weekly-{date_slug}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown_report(payload, candidates, findings_by_id), encoding="utf-8")
    return {"markdown": md_path, "json": json_path}


def _candidate_json(candidate: dict[str, Any]) -> dict[str, Any]:
    converted = dict(candidate)
    for key in ("supporting_findings", "contradicting_findings"):
        converted[key] = json_load(candidate.get(key), [])
    return converted


def _markdown_report(
    payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    findings_by_id: dict[str, dict[str, Any]],
) -> str:
    metrics = payload["metrics"]
    skill_candidates = [
        candidate for candidate in candidates if candidate["category"] == "reusable-workflow-pattern"
    ]
    improvement_candidates = [
        candidate for candidate in candidates if candidate["category"] != "reusable-workflow-pattern"
    ]
    lines = [
        f"# Harness Retro — weekly report",
        "",
        f"Generated: {payload['generated_at']}",
        f"Since: {payload['since'] or 'all imported data'}",
        "",
        "## Объём",
        "",
        f"- Сессии: {metrics['sessions']}",
        f"- Events: {metrics['events']}",
        f"- User turns: {metrics['user_turns']}",
        f"- Assistant turns: {metrics['assistant_turns']}",
        f"- Input tokens: {metrics['input_tokens']}",
        f"- Cached input tokens: {metrics['cached_input_tokens']}",
        f"- Output tokens: {metrics['output_tokens']}",
        "",
        "## Краткий итог",
        "",
        _summary(metrics, candidates),
        "",
        "## Приоритетные improvement candidates",
        "",
    ]
    if not improvement_candidates:
        lines.append("Подтверждённых candidates пока нет.")
    for candidate in improvement_candidates:
        _append_candidate(lines, candidate, findings_by_id)
    lines.extend(["## Кандидаты на новые skills", ""])
    if not skill_candidates:
        lines.append("Повторяющиеся составные workflows пока не выделены.")
    for candidate in skill_candidates:
        _append_candidate(lines, candidate, findings_by_id)
    lines.extend(
        [
            "## Ограничения анализа",
            "",
            *[f"- {item}" for item in payload["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def _append_candidate(
    lines: list[str],
    candidate: dict[str, Any],
    findings_by_id: dict[str, dict[str, Any]],
) -> None:
    supporting = json_load(candidate["supporting_findings"], [])
    evidence = []
    for finding_id in supporting[:3]:
        finding = findings_by_id.get(finding_id)
        if not finding:
            continue
        evidence.extend(json_load(finding["evidence"], [])[:2])
    lines.extend(
        [
            f"### {candidate['title']}",
            "",
            f"- ID: `{candidate['candidate_id']}`",
            f"- State: `{candidate['state']}`",
            f"- Category: `{candidate['category']}`",
            f"- Sessions/projects: {candidate['affected_sessions']} / {candidate['affected_projects']}",
            f"- Destination/scope: `{candidate['recommended_destination']}` / `{candidate['recommended_scope']}`",
            f"- Hypothesis: {candidate['hypothesis']}",
            f"- Proposed change: {candidate['proposed_change']}",
            f"- Expected effect: {candidate['expected_effect']}",
            f"- Risk: {candidate['risk']}",
            f"- Measurement: {candidate['measurement_plan']}",
            "- Counterevidence: not found in deterministic MVP analysis.",
            "",
            "Evidence:",
        ]
    )
    if not evidence:
        lines.append("- No evidence excerpts available.")
    else:
        for item in evidence[:3]:
            lines.append(f"- `{item.get('event_id')}` {item.get('role')}: {item.get('excerpt')}")
    lines.append("")


def _summary(metrics: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "Повторяющиеся evidence-backed паттерны пока не выделены."
    corroborated = sum(1 for candidate in candidates if candidate["state"] == "corroborated")
    observed = sum(1 for candidate in candidates if candidate["state"] == "observed")
    skill_opportunities = sum(
        1 for candidate in candidates if candidate["category"] == "reusable-workflow-pattern"
    )
    return (
        f"Найдено candidates: {len(candidates)}. Corroborated: {corroborated}. "
        f"Observed: {observed}. New-skill opportunities: {skill_opportunities}. "
        f"Redaction tags: {metrics['redaction_tags'] or '{}'}."
    )
