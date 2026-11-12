from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any

from harness_retro.config import Config
from harness_retro.store import (
    json_load,
    mark_unmatched_candidates_stale,
    replace_deterministic_findings,
    save_candidates,
    stable_id,
)


EXTRACTOR_VERSION = "deterministic-mvp-v5"
DETERMINISTIC_CATEGORIES = {
    "missing-verification",
    "oversized-tool-output",
    "repeated-tool-failure",
    "reusable-workflow-pattern",
    "user-discovered-regression",
    "verification-ignored",
}
SKILL_OPPORTUNITY_WINDOW_DAYS = 30
MAX_WORKFLOW_PATTERNS = 5
MIN_WORKFLOW_STEPS = 3
MAX_WORKFLOW_STEPS = 7
IGNORED_COMMAND_NAMES = {
    "clear",
    "compact",
    "config",
    "context",
    "cost",
    "doctor",
    "help",
    "login",
    "logout",
    "model",
    "permissions",
    "status",
}
SKILL_REFERENCE_PATTERNS = (
    re.compile(r"Base directory for this skill:\s+[^\n]*?/skills/([a-z][a-z0-9-]+)", re.I),
    re.compile(r"<skill>\s*<name>\s*([a-z][a-z0-9-]+)\s*</name>", re.I),
    re.compile(r"<command-name>/([a-z][a-z0-9-]+)</command-name>", re.I),
)
COMPLETION_CLAIM_RE = re.compile(
    r"(?im)(?:"
    r"^\s*(?:#{1,6}\s*)?(?:готово|сделано|исправлено|завершено|раскатано|"
    r"починил(?:а|и)?|исправил(?:а|и)?|сделал(?:а|и)?|завершил(?:а|и)?|"
    r"реализовал(?:а|и)?|done|fixed|implemented|completed|ready)\b|"
    r"\b(?:всё|все|оба|обе|изменение|задача|работа|ветка|реализация|функционал)\s+"
    r"(?:готово|готова|готовы|завершено|завершена)\b|"
    r"\bготово\s+к\s+(?:/|проверке|ревью|публикации|мержу|слиянию|релизу)|"
    r"\b(?:i|we)(?:'ve| have)?\s+(?:fixed|implemented|completed)\b"
    r")"
)
NEGATED_COMPLETION_CONTEXT_RE = re.compile(
    r"(?is)(?:\bне\b|\bбез\b|\bnot\b|\bwithout\b|\bчтобы\b|\bперед тем как\b|\bпрежде чем\b)"
    r"[^.!?\n]{0,50}$"
)
CORRECTION_RE = re.compile(
    r"(?i)(не работает|всё еще|все еще|ошибка|сломал|не исправ|падает|падают|not working|still fails|failed|broken)"
)
FAILED_TASK_NOTIFICATION_RE = re.compile(
    r"(?is)<task-notification\b.*?(?:"
    r"status\s*=\s*['\"]?(?:failed|error|killed|stopped)|"
    r"<status>\s*(?:failed|error|killed|stopped)\s*</status>"
    r")"
)
SYNTHETIC_USER_PREFIXES = (
    "<skill>",
    "base directory for this skill:",
    "# agents.md instructions",
    "<agents_instructions>",
    "<app-context>",
    "<environment_context>",
    "<model_switch>",
    "<permissions instructions>",
    "<recommended_plugins>",
    "<skills_instructions>",
    "<user_instructions>",
)
SYNTHETIC_USER_MARKERS = (
    "the following is the codex agent history",
)
EXPLICIT_VERIFICATION_LIMITATION_RE = re.compile(
    r"(?is)(?:"
    r"\b(?:не|без)\s+(?:(?:локальн\w*|ручн\w*|отдельн\w*|полностью|ещ[её]|пока)\s+){0,3}"
    r"(?:провер\w*|тест\w*|запуск\w*|свер\w*|валидир\w*|измер\w*|подтвержд\w*|"
    r"смотр\w*|открыва\w*|прогон\w*)|"
    r"\b(?:непровер\w*|что\s+остал\w*\s+вне\s+проверки)\b|"
    r"\b(?:нуж\w*|требуется|оста[её]тся)\b[^.!?\n]{0,60}\b"
    r"(?:провер\w*|тест\w*|smoke|прогон\w*)|"
    r"\b(?:провер\w*|тест\w*|сборк\w*|линт\w*)[^.!?\n]{0,40}\bне\s+"
    r"(?:запуск\w*|провод\w*|выполн\w*|доступ\w*)|"
    r"\b(?:not|without)\s+(?:(?:locally|manually|fully|yet|separately)\s+){0,3}"
    r"(?:test\w*|verif\w*|check\w*|run\w*|validat\w*|measur\w*)|"
    r"\b(?:tests?|checks?|build|lint)[^.!?\n]{0,40}\bnot\s+"
    r"(?:run|executed|performed|available)\b|"
    r"\bunverified\b"
    r")"
)
NO_IMPLEMENTATION_RE = re.compile(
    r"(?is)(?:"
    r"ни\s+(?:одной\s+)?строчк\w*\s+код\w*|"
    r"код\w*[^.!?\n]{0,30}\b(?:пока\s+|ещ[её]\s+)?не\s+измен\w*|"
    r"реализац\w*[^.!?\n]{0,30}\b(?:пока\s+|ещ[её]\s+)?не\s+"
    r"(?:нач\w*|выполн\w*)|"
    r"no\s+code\s+changes?|"
    r"implementation[^.!?\n]{0,30}\bnot\s+(?:started|implemented|changed)\b"
    r")"
)
RUNTIME_IMPLEMENTATION_RE = re.compile(
    r"(?is)(?:"
    r"\b(?:реализ\w*|исправ\w*|почин\w*|добав\w*|измен\w*|обнов\w*|встав\w*)"
    r"[^.!?\n]{0,80}\b(?:реализац\w*|код\w*|скрипт\w*|функционал\w*|"
    r"эндпоинт\w*|миграц\w*|сч[её]тчик\w*|страниц\w*|сайт\w*|api)\b|"
    r"\b(?:реализац\w*|код\w*|скрипт\w*|функционал\w*|эндпоинт\w*|"
    r"миграц\w*|сч[её]тчик\w*|страниц\w*|сайт\w*|api)\b[^.!?\n]{0,80}"
    r"\b(?:реализ\w*|исправ\w*|почин\w*|добав\w*|измен\w*|обнов\w*|встав\w*)|"
    r"\b(?:implemented|fixed|changed|updated|added)\b[^.!?\n]{0,80}"
    r"\b(?:implementation|code|script|feature|endpoint|migration|site|page|api)\b|"
    r"\b(?:implementation|code|script|feature|endpoint|migration|site|page|api)\b"
    r"[^.!?\n]{0,80}\b(?:implemented|fixed|changed|updated|added)\b"
    r")"
)
NON_IMPLEMENTATION_SCOPE_RE = re.compile(
    r"(?i)\b(?:"
    r"proposal(?:\.md)?|design(?:\.md)?|tasks(?:\.md)?|sdd|read[- ]only|inspection|"
    r"предложени\w*|дизайн\w*|декомпоз\w*|спецификац\w*|документац\w*|"
    r"документ\w*|отч[её]т\w*|анализ\w*|аудит\w*|инвентаризац\w*|"
    r"baseline|план\w*|материал\w*|таблиц\w*|spreadsheet\w*"
    r")\b"
)
GIT_ADMIN_SCOPE_RE = re.compile(
    r"(?i)\b(?:"
    r"репозитор\w*|ветк\w*|branch(?:es)?|коммит\w*|commit(?:ted|s)?|push(?:ed)?|pull(?:ed)?|"
    r"merge(?:d)?|checkout|переключ\w*|подтян\w*"
    r")\b"
)
GENERIC_COMPLETION_BLOCK_RE = re.compile(
    r"(?i)^(?:#{1,6}\s*)?(?:"
    r"готово|сделано|исправлено|завершено|done|fixed|completed|"
    r"сделал(?:а|и)?(?:\s+локально)?|исправил(?:а|и)?|починил(?:а|и)?|"
    r"реализовал(?:а|и)?|что\s+(?:сделано|изменено)|итог"
    r")[\s:.,!*-]*$"
)


def build_metrics(conn: sqlite3.Connection, since: datetime | None = None) -> dict[str, Any]:
    where, params = _since_where(since, "sessions.started_at")
    session_rows = conn.execute(f"SELECT * FROM sessions {where}", params).fetchall()
    where_events, event_params = _since_where(since, "timestamp")
    event_rows = conn.execute(f"SELECT * FROM events {where_events}", event_params).fetchall()
    tool_counter: Counter[str] = Counter()
    tool_status: Counter[str] = Counter()
    redaction_tags: Counter[str] = Counter()
    input_tokens = 0
    cached_tokens = 0
    output_tokens = 0
    user_turns = 0
    assistant_turns = 0
    call_names: dict[str, str] = {}
    for row in sorted(event_rows, key=lambda item: (item["session_id"], item["sequence"])):
        if row["kind"] == "tool_call":
            tool_name = row["tool_name"] or "unknown"
            tool_counter[tool_name] += 1
            if row["tool_call_id"]:
                call_names[f"{row['session_id']}:{row['tool_call_id']}"] = tool_name
        elif row["kind"] == "tool_result":
            tool_name = row["tool_name"] or call_names.get(f"{row['session_id']}:{row['tool_call_id']}", "unknown")
            tool_status[f"{tool_name}:{row['status']}"] += 1
        if row["actor"] == "user" and row["kind"] == "message":
            user_turns += 1
        if row["actor"] == "assistant" and row["kind"] == "message":
            assistant_turns += 1
        input_tokens += row["input_tokens"] or 0
        cached_tokens += row["cached_input_tokens"] or 0
        output_tokens += row["output_tokens"] or 0
        redaction_tags.update(json_load(row["redaction_tags"], []))
    return {
        "sessions": len(session_rows),
        "events": len(event_rows),
        "user_turns": user_turns,
        "assistant_turns": assistant_turns,
        "tool_calls_by_name": dict(tool_counter),
        "tool_events_by_status": dict(tool_status),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "redaction_tags": dict(redaction_tags),
        "findings": conn.execute("SELECT COUNT(*) AS count FROM findings").fetchone()["count"],
        "candidates": conn.execute(
            "SELECT COUNT(*) AS count FROM candidates WHERE state != 'stale'"
        ).fetchone()["count"],
    }


def run_analysis(
    conn: sqlite3.Connection,
    config: Config,
    since: datetime | None = None,
) -> dict[str, Any]:
    findings = extract_findings(conn, config, since)
    accepted_findings = [finding for finding in findings if finding["validator_status"] == "accepted"]
    candidates = aggregate_candidates(conn, accepted_findings)
    replace_deterministic_findings(conn, findings)
    save_candidates(conn, candidates)
    mark_unmatched_candidates_stale(
        conn,
        categories=DETERMINISTIC_CATEGORIES,
        active_fingerprints={candidate["fingerprint"] for candidate in candidates},
    )
    conn.commit()
    return {
        "findings": len(findings),
        "accepted_findings": len(accepted_findings),
        "candidates": len(candidates),
        "metrics": build_metrics(conn, since),
    }


def extract_findings(
    conn: sqlite3.Connection,
    config: Config,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    where, params = _since_where(since, "timestamp")
    rows = conn.execute(f"SELECT * FROM events {where} ORDER BY session_id, sequence", params).fetchall()
    by_session: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_session[row["session_id"]].append(row)

    findings: list[dict[str, Any]] = []
    for session_id, events in by_session.items():
        findings.extend(_repeated_tool_failures(session_id, events))
        findings.extend(_oversized_outputs(session_id, events, config.limits.oversized_output_chars))
        findings.extend(_post_completion_failures(session_id, events))
        findings.extend(_missing_verification(session_id, events))

    workflow_since = _workflow_since(since)
    workflow_where, workflow_params = _since_where(workflow_since, "timestamp")
    workflow_rows = conn.execute(
        f"SELECT * FROM events {workflow_where} ORDER BY session_id, sequence",
        workflow_params,
    ).fetchall()
    workflow_sessions: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in workflow_rows:
        workflow_sessions[row["session_id"]].append(row)
    findings.extend(_reusable_workflow_patterns(workflow_sessions))
    return [_validate_finding(conn, finding) for finding in findings]


def aggregate_candidates(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not findings:
        return []
    session_meta = {
        row["session_id"]: row
        for row in conn.execute(
            "SELECT session_id, project_key, harness, started_at, ended_at FROM sessions"
        ).fetchall()
    }
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        groups[_candidate_fingerprint(finding)].append(finding)

    candidates: list[dict[str, Any]] = []
    for fingerprint, items in groups.items():
        sessions = {item["session_id"] for item in items}
        projects = {
            session_meta[session_id]["project_key"]
            for session_id in sessions
            if session_id in session_meta and session_meta[session_id]["project_key"]
        }
        harnesses = {
            session_meta[session_id]["harness"]
            for session_id in sessions
            if session_id in session_meta
        }
        first_seen = _min_date(
            session_meta[session_id]["started_at"]
            for session_id in sessions
            if session_id in session_meta
        )
        last_seen = _max_date(
            session_meta[session_id]["ended_at"]
            for session_id in sessions
            if session_id in session_meta
        )
        category = items[0]["category"]
        state = _candidate_state(category, len(sessions), len(projects))
        scope = _recommended_scope(len(sessions), len(projects), len(harnesses))
        destination = _recommended_destination(category, state)
        confidence = min(0.95, sum(item["confidence"] for item in items) / len(items) + 0.05 * (len(sessions) - 1))
        impact = _max_impact(item["impact"] for item in items)
        title = _candidate_title(category, items[0]["title"])
        candidates.append(
            {
                "candidate_id": f"cand-{stable_id(fingerprint, length=16)}",
                "fingerprint": fingerprint,
                "title": title,
                "hypothesis": _hypothesis(category, len(sessions), items[0]["title"]),
                "category": category,
                "supporting_findings": [item["finding_id"] for item in items],
                "contradicting_findings": [],
                "affected_sessions": len(sessions),
                "affected_projects": len(projects),
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "confidence": round(confidence, 2),
                "impact": impact,
                "recommended_destination": destination,
                "recommended_scope": scope,
                "proposed_change": _proposed_change(category, destination, items[0]["title"]),
                "expected_effect": _expected_effect(category),
                "risk": _risk(destination, state),
                "measurement_plan": (
                    "После применения сравнить следующие 10 релевантных сессий или 30 дней: "
                    "частота категории, число повторов и наличие контрпримеров."
                ),
                "state": state,
                "rationale": _candidate_rationale(
                    category,
                    len(items),
                    len(sessions),
                    len(projects),
                ),
                "reviewed_at": None,
            }
        )
    return candidates


def _reusable_workflow_patterns(
    sessions: dict[str, list[sqlite3.Row]],
) -> list[dict[str, Any]]:
    session_steps = {
        session_id: steps
        for session_id, events in sessions.items()
        if len(steps := _session_skill_steps(events)) >= MIN_WORKFLOW_STEPS
    }
    pattern_sessions: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for session_id, steps in session_steps.items():
        names = [name for name, _ in steps]
        upper_bound = min(MAX_WORKFLOW_STEPS, len(names))
        for size in range(MIN_WORKFLOW_STEPS, upper_bound + 1):
            for indexes in combinations(range(len(names)), size):
                pattern = tuple(names[index] for index in indexes)
                if len(set(pattern)) != len(pattern):
                    continue
                pattern_sessions[pattern].add(session_id)

    ranked = sorted(
        (
            (pattern, supporting_sessions)
            for pattern, supporting_sessions in pattern_sessions.items()
            if len(supporting_sessions) >= 2
        ),
        key=lambda item: (
            len(item[1]) * (len(item[0]) - 1),
            len(item[0]),
            len(item[1]),
            item[0],
        ),
        reverse=True,
    )
    selected: list[tuple[tuple[str, ...], set[str]]] = []
    for pattern, supporting_sessions in ranked:
        if any(
            _workflow_patterns_overlap(pattern, supporting_sessions, other_pattern, other_sessions)
            for other_pattern, other_sessions in selected
        ):
            continue
        selected.append((pattern, supporting_sessions))
        if len(selected) >= MAX_WORKFLOW_PATTERNS:
            break

    findings: list[dict[str, Any]] = []
    for pattern, supporting_sessions in selected:
        title = f"Повторяемый workflow: {' -> '.join(pattern)}"
        confidence = min(0.9, 0.6 + 0.05 * len(supporting_sessions))
        for session_id in sorted(supporting_sessions):
            matched_steps = _matching_workflow_steps(session_steps[session_id], pattern)
            evidence_steps = matched_steps if len(matched_steps) <= 3 else [
                matched_steps[0],
                matched_steps[len(matched_steps) // 2],
                matched_steps[-1],
            ]
            findings.append(
                _finding(
                    session_id=session_id,
                    category="reusable-workflow-pattern",
                    title=title,
                    description=(
                        "Одна и та же упорядоченная композиция нескольких skills повторилась "
                        f"в {len(supporting_sessions)} независимых сессиях."
                    ),
                    impact="medium",
                    confidence=confidence,
                    evidence=[
                        _workflow_evidence(name, event) for name, event in evidence_steps
                    ],
                    scope_hint="skill",
                )
            )
    return findings


def _session_skill_steps(events: list[sqlite3.Row]) -> list[tuple[str, sqlite3.Row]]:
    steps: list[tuple[str, sqlite3.Row]] = []
    seen: set[str] = set()
    for event in events:
        if event["actor"] != "user" or event["kind"] != "message":
            continue
        text = event["text"] or ""
        normalized = text.lstrip().lower()
        if normalized.startswith("<skills_instructions>") or any(
            marker in normalized for marker in SYNTHETIC_USER_MARKERS
        ):
            continue
        matches = []
        for pattern in SKILL_REFERENCE_PATTERNS:
            matches.extend((match.start(), match.group(1).lower()) for match in pattern.finditer(text))
        for _, name in sorted(matches):
            if name in IGNORED_COMMAND_NAMES or name in seen:
                continue
            seen.add(name)
            steps.append((name, event))
    return steps


def _matching_workflow_steps(
    steps: list[tuple[str, sqlite3.Row]],
    pattern: tuple[str, ...],
) -> list[tuple[str, sqlite3.Row]]:
    matched = []
    pattern_index = 0
    for name, event in steps:
        if name != pattern[pattern_index]:
            continue
        matched.append((name, event))
        pattern_index += 1
        if pattern_index == len(pattern):
            break
    return matched


def _workflow_evidence(name: str, event: sqlite3.Row) -> dict[str, str]:
    return {
        "event_id": event["event_id"],
        "role": "workflow-step",
        "excerpt": f"Invoked skill: {name}",
    }


def _workflow_patterns_overlap(
    pattern: tuple[str, ...],
    sessions: set[str],
    other_pattern: tuple[str, ...],
    other_sessions: set[str],
) -> bool:
    family = _workflow_family(pattern)
    if family and family == _workflow_family(other_pattern):
        return True
    shared_skills = len(set(pattern) & set(other_pattern)) / min(len(pattern), len(other_pattern))
    shared_sessions = len(sessions & other_sessions) / min(len(sessions), len(other_sessions))
    return shared_skills >= 0.6 and shared_sessions >= 0.5


def _workflow_family(pattern: tuple[str, ...]) -> str | None:
    sdd_steps = sum(step.startswith("sdd-") for step in pattern)
    if sdd_steps >= 2 and sdd_steps / len(pattern) >= 0.5:
        return "sdd"
    if sdd_steps >= 1 and "task-tracker" in pattern and "ship" in pattern:
        return "sdd"
    return None


def _workflow_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    rolling_start = datetime.now(timezone.utc) - timedelta(days=SKILL_OPPORTUNITY_WINDOW_DAYS)
    return min(since, rolling_start)


def _repeated_tool_failures(session_id: str, events: list[sqlite3.Row]) -> list[dict[str, Any]]:
    calls: dict[str, sqlite3.Row] = {}
    failures: dict[str, list[tuple[sqlite3.Row, sqlite3.Row | None]]] = defaultdict(list)
    for event in events:
        if event["kind"] == "tool_call" and event["tool_call_id"]:
            calls[event["tool_call_id"]] = event
        if event["kind"] == "tool_result" and event["status"] in {"failure", "denied", "interrupted"}:
            call = calls.get(event["tool_call_id"] or "")
            key = _operation_key(call, event)
            failures[key].append((event, call))
    findings = []
    for key, failed_events in failures.items():
        if len(failed_events) < 2:
            continue
        evidence = []
        for result, call in failed_events[:3]:
            if call:
                evidence.append(_evidence(call, "trigger"))
            evidence.append(_evidence(result, "outcome"))
        tool_name = (failed_events[0][1] or failed_events[0][0])["tool_name"] or "unknown"
        findings.append(
            _finding(
                session_id=session_id,
                category="repeated-tool-failure",
                title=f"Повторяющаяся ошибка инструмента {tool_name}",
                description="Эквивалентная tool-операция завершилась неуспешно несколько раз в одной сессии.",
                impact="medium",
                confidence=0.8,
                evidence=evidence,
                scope_hint="harness",
            )
        )
    return findings


def _oversized_outputs(session_id: str, events: list[sqlite3.Row], limit: int) -> list[dict[str, Any]]:
    findings = []
    for event in events:
        text = event["text"] or ""
        if event["kind"] == "tool_result" and len(text) > limit:
            findings.append(
                _finding(
                    session_id=session_id,
                    category="oversized-tool-output",
                    title="Крупный tool output попал в контекст",
                    description=(
                        f"Tool result содержит {len(text)} символов; вероятно, стоило фильтровать "
                        "или агрегировать вывод до возврата в контекст."
                    ),
                    impact="low",
                    confidence=0.75,
                    evidence=[_evidence(event, "outcome")],
                    scope_hint="harness",
                )
            )
    return findings


def _post_completion_failures(session_id: str, events: list[sqlite3.Row]) -> list[dict[str, Any]]:
    findings = []
    last_claim: sqlite3.Row | None = None
    for event in events:
        text = event["text"] or ""
        if event["actor"] == "assistant" and event["kind"] == "message" and _is_completion_claim(text):
            last_claim = event
            continue
        if not last_claim:
            continue
        if _is_failed_task_notification(text):
            findings.append(
                _finding(
                    session_id=session_id,
                    category="verification-ignored",
                    title="Фоновая проверка опровергла заявление о готовности",
                    description=(
                        "После assistant success claim служебное уведомление сообщило о провале "
                        "или остановке фоновой проверки."
                    ),
                    impact="high",
                    confidence=0.95,
                    evidence=[_evidence(last_claim, "trigger"), _evidence(event, "contradiction")],
                    scope_hint="harness",
                )
            )
            last_claim = None
            continue
        if not (event["actor"] == "user" and event["kind"] == "message"):
            continue
        if _is_synthetic_user_context(text):
            continue
        if CORRECTION_RE.search(text):
            findings.append(
                _finding(
                    session_id=session_id,
                    category="user-discovered-regression",
                    title="Пользователь нашёл дефект после заявления о готовности",
                    description=(
                        "После assistant success claim пользователь сообщил о сохраняющейся ошибке "
                        "или регрессии."
                    ),
                    impact="high",
                    confidence=0.85,
                    evidence=[_evidence(last_claim, "trigger"), _evidence(event, "confirmation")],
                    scope_hint="personal",
                )
            )
        last_claim = None
    return findings


def _is_failed_task_notification(text: str) -> bool:
    return bool(FAILED_TASK_NOTIFICATION_RE.search(text))


def _is_synthetic_user_context(text: str) -> bool:
    normalized = text.lstrip().lower()
    return normalized.startswith(SYNTHETIC_USER_PREFIXES) or any(
        marker in normalized for marker in SYNTHETIC_USER_MARKERS
    )


def _is_completion_claim(text: str) -> bool:
    for match in COMPLETION_CLAIM_RE.finditer(text):
        prefix = text[max(0, match.start() - 60) : match.start()]
        if not NEGATED_COMPLETION_CONTEXT_RE.search(prefix):
            return True
    return False


def _missing_verification(session_id: str, events: list[sqlite3.Row]) -> list[dict[str, Any]]:
    findings = []
    calls = {
        event["tool_call_id"]: event
        for event in events
        if event["kind"] == "tool_call" and event["tool_call_id"]
    }
    success_evidence_sequences = {
        event["sequence"]
        for event in events
        if (
            event["kind"] in {"tool_result", "edit"}
            and event["status"] == "success"
            and _verification_event(event, calls.get(event["tool_call_id"] or ""))
        )
    }
    last_user_sequence = 0
    for event in events:
        text = event["text"] or ""
        if event["actor"] == "user" and event["kind"] == "message":
            if not _is_synthetic_user_context(text):
                last_user_sequence = event["sequence"]
            continue
        if not (event["actor"] == "assistant" and event["kind"] == "message" and _is_completion_claim(text)):
            continue
        if not _completion_requires_runtime_verification(text):
            continue
        previous_verification = [
            seq
            for seq in success_evidence_sequences
            if last_user_sequence <= seq < event["sequence"]
        ]
        if previous_verification:
            continue
        findings.append(
            _finding(
                session_id=session_id,
                category="missing-verification",
                title="Заявление о готовности без видимой проверки",
                description=(
                    "Assistant сообщил о завершении, но в ближайшем контексте нет успешного test/build/lint "
                    "или другого проверочного tool result."
                ),
                impact="medium",
                confidence=0.7,
                evidence=[_evidence(event, "trigger")],
                scope_hint="personal",
            )
        )
    return findings


def _completion_requires_runtime_verification(text: str) -> bool:
    if EXPLICIT_VERIFICATION_LIMITATION_RE.search(text):
        return False
    if NO_IMPLEMENTATION_RE.search(text):
        return False
    primary_scope = _primary_completion_scope(text)
    if NON_IMPLEMENTATION_SCOPE_RE.search(primary_scope) and not RUNTIME_IMPLEMENTATION_RE.search(primary_scope):
        return False
    if GIT_ADMIN_SCOPE_RE.search(primary_scope) and not RUNTIME_IMPLEMENTATION_RE.search(primary_scope):
        return False
    return True


def _primary_completion_scope(text: str) -> str:
    blocks = re.split(r"(?<=[.!?])\s+|\n\s*\n", text)
    for block in blocks:
        normalized = block.strip()
        if normalized and not GENERIC_COMPLETION_BLOCK_RE.fullmatch(normalized):
            return normalized
    return text


def _validate_finding(conn: sqlite3.Connection, finding: dict[str, Any]) -> dict[str, Any]:
    evidence = finding.get("evidence", [])
    if not evidence:
        finding["validator_status"] = "rejected"
        return finding
    event_ids = [item.get("event_id") for item in evidence if item.get("event_id")]
    if len(event_ids) != len(evidence):
        finding["validator_status"] = "rejected"
        return finding
    placeholders = ",".join("?" for _ in event_ids)
    count = conn.execute(
        f"SELECT COUNT(*) AS count FROM events WHERE event_id IN ({placeholders})",
        event_ids,
    ).fetchone()["count"]
    finding["validator_status"] = "accepted" if count == len(event_ids) else "rejected"
    return finding


def _finding(
    *,
    session_id: str,
    category: str,
    title: str,
    description: str,
    impact: str,
    confidence: float,
    evidence: list[dict[str, str]],
    scope_hint: str,
) -> dict[str, Any]:
    fingerprint = stable_id(
        session_id,
        category,
        title,
        "|".join(item["event_id"] for item in evidence),
        length=20,
    )
    return {
        "finding_id": f"find-{fingerprint}",
        "session_id": session_id,
        "category": category,
        "title": title,
        "description": description,
        "impact": impact,
        "confidence": confidence,
        "evidence": evidence,
        "counterevidence": [],
        "scope_hint": scope_hint,
        "extractor_version": EXTRACTOR_VERSION,
        "validator_status": "uncertain",
    }


def _evidence(event: sqlite3.Row, role: str) -> dict[str, str]:
    return {
        "event_id": event["event_id"],
        "role": role,
        "excerpt": _excerpt(event["text"] or event["raw_type"] or ""),
    }


def _excerpt(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit // 2]} ... {text[-limit // 2 :]}"


def _operation_key(call: sqlite3.Row | None, result: sqlite3.Row) -> str:
    source = call or result
    return stable_id(
        source["tool_name"] or "unknown",
        _normalize_operation(source["text"] or ""),
        length=20,
    )


def _normalize_operation(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().lower())
    text = re.sub(r"\d+", "0", text)
    return text[:500]


def _looks_like_verification(text: str, tool_name: str) -> bool:
    haystack = f"{tool_name} {text}".lower()
    return any(
        term in haystack
        for term in (
            "test",
            "pytest",
            "vitest",
            "lint",
            "build",
            "compile",
            "gradle",
            "mvn",
            "curl",
            "healthy",
            "healthz",
            "/health",
            "smoke",
            "playwright",
            "browser_",
            "network_requests",
            "diff --check",
            "syntax",
        )
    )


def _verification_event(result: sqlite3.Row, call: sqlite3.Row | None) -> bool:
    text = result["text"] or ""
    tool_name = result["tool_name"] or ""
    if call:
        text = f"{call['text'] or ''}\n{text}"
        tool_name = call["tool_name"] or tool_name
    return _looks_like_verification(text, tool_name)


def _candidate_fingerprint(finding: dict[str, Any]) -> str:
    return stable_id(finding["category"], _normalize_operation(finding["title"]), length=24)


def _candidate_title(category: str, finding_title: str) -> str:
    return {
        "repeated-tool-failure": "Сократить повторяющиеся ошибки инструментов",
        "oversized-tool-output": "Ограничить крупные tool outputs",
        "user-discovered-regression": "Усилить проверку перед заявлением о готовности",
        "verification-ignored": "Не игнорировать провал фоновой проверки",
        "missing-verification": "Убрать completion claims без проверки",
        "reusable-workflow-pattern": finding_title,
    }.get(category, finding_title)


def _hypothesis(category: str, sessions: int, finding_title: str) -> str:
    return {
        "repeated-tool-failure": (
            f"В {sessions} сессии(ях) повторялись эквивалентные неуспешные tool-операции; "
            "предварительная проверка предусловий или helper может уменьшить retries."
        ),
        "oversized-tool-output": (
            f"В {sessions} сессии(ях) крупный вывод попадал в контекст; фильтрация может снизить шум и расход токенов."
        ),
        "user-discovered-regression": (
            f"В {sessions} сессии(ях) пользователь нашёл ошибку после success claim; нужна более строгая финальная проверка."
        ),
        "verification-ignored": (
            f"В {sessions} сессии(ях) фоновая проверка опровергла success claim; её результат должен менять финальный статус."
        ),
        "missing-verification": (
            f"В {sessions} сессии(ях) готовность заявлялась без видимого подтверждения проверкой."
        ),
        "reusable-workflow-pattern": (
            f"В {sessions} независимых сессиях повторилась композиция "
            f"`{_workflow_label(finding_title)}`; orchestration skill может убрать повторную "
            "передачу контекста и сохранить единые переходы между этапами."
        ),
    }.get(category, f"Категория {category} повторилась в {sessions} сессии(ях).")


def _candidate_state(category: str, session_count: int, project_count: int) -> str:
    if category == "reusable-workflow-pattern":
        if session_count >= 3 and (project_count >= 2 or session_count >= 5):
            return "corroborated"
        return "observed"
    return "corroborated" if session_count >= 2 else "observed"


def _recommended_destination(category: str, state: str) -> str:
    if state == "observed":
        return "none"
    return {
        "repeated-tool-failure": "cli-helper",
        "oversized-tool-output": "hook",
        "user-discovered-regression": "skill",
        "verification-ignored": "skill",
        "missing-verification": "skill",
        "reusable-workflow-pattern": "skill",
    }.get(category, "none")


def _recommended_scope(session_count: int, project_count: int, harness_count: int) -> str:
    if session_count >= 3 and project_count >= 2 and harness_count >= 2:
        return "cross-harness"
    if project_count == 1:
        return "project"
    if harness_count == 1:
        return "harness"
    return "personal"


def _proposed_change(category: str, destination: str, finding_title: str) -> str:
    if destination == "none":
        return "Ничего не менять автоматически; оставить как наблюдение до появления повторов."
    return {
        "repeated-tool-failure": (
            "Добавить helper или инструкцию предусловий для повторяющейся операции; перед повтором менять диагностическую гипотезу."
        ),
        "oversized-tool-output": (
            "Добавить ограничение или wrapper, который возвращает агрегированный/фильтрованный вывод вместо полного лога."
        ),
        "user-discovered-regression": (
            "Добавить в релевантный skill финальный evidence checklist: не заявлять готовность без теста, артефакта или явного ограничения."
        ),
        "verification-ignored": (
            "Считать failed/killed/stopped task notification опровержением success claim и отражать провал в финальном статусе."
        ),
        "missing-verification": (
            "Добавить проверочное правило в workflow skill: success claim должен ссылаться на выполненную проверку либо честно назвать её отсутствие."
        ),
        "reusable-workflow-pattern": (
            f"Подготовить отдельный orchestration skill `{_suggested_skill_name(finding_title)}` для "
            f"последовательности `{_workflow_label(finding_title)}`. Перед созданием вручную проверить, "
            "что существующий skill не покрывает workflow целиком, и сохранить все действующие approval gates."
        ),
    }.get(category, "Подготовить ручной diff после review кандидата.")


def _expected_effect(category: str) -> str:
    return {
        "repeated-tool-failure": "Меньше повторов одной и той же неуспешной операции и быстрее смена диагностики.",
        "oversized-tool-output": "Меньше шума в контексте и ниже расход токенов на большие tool results.",
        "user-discovered-regression": "Меньше дефектов, обнаруженных пользователем сразу после отчёта о готовности.",
        "verification-ignored": "Меньше ложных success claims при провале или остановке фоновой проверки.",
        "missing-verification": "Более точные финальные отчёты и меньше неподтверждённых success claims.",
        "reusable-workflow-pattern": (
            "Меньше повторной передачи контекста между этапами и более стабильное выполнение составного workflow."
        ),
    }.get(category, "Снижение частоты подтверждённого паттерна.")


def _candidate_rationale(
    category: str,
    finding_count: int,
    session_count: int,
    project_count: int,
) -> str:
    if category == "reusable-workflow-pattern":
        return (
            f"Кандидат создан из {finding_count} evidence-backed finding(s) в "
            f"{session_count} независимых сессиях и {project_count} проектах. Новый skill не создавать "
            "до ручной проверки пересечения с существующими skills."
        )
    return (
        f"Кандидат создан из {finding_count} evidence-backed finding(s) "
        f"в {session_count} независимых сессии(ях)."
    )


def _workflow_label(finding_title: str) -> str:
    return finding_title.removeprefix("Повторяемый workflow: ")


def _suggested_skill_name(finding_title: str) -> str:
    steps = _workflow_label(finding_title).split(" -> ")
    if all(step.startswith("sdd-") or step == "ship" for step in steps):
        return "sdd-delivery"
    name = f"{steps[0]}-to-{steps[-1]}"
    return name[:63].rstrip("-")


def _risk(destination: str, state: str) -> str:
    if destination == "none":
        return "Низкий: изменение не предлагается до дополнительной evidence."
    if state == "observed":
        return "Средний: один эпизод может быть шумом; нужен ручной review перед изменением."
    return "Средний: возможен instruction bloat или overfitting; изменение должно быть узким и измеряемым."


def _max_impact(impacts: Any) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(impacts, key=lambda impact: order.get(impact, 0))


def _min_date(values: Any) -> str | None:
    clean = [value for value in values if value]
    return min(clean) if clean else None


def _max_date(values: Any) -> str | None:
    clean = [value for value in values if value]
    return max(clean) if clean else None


def _since_where(since: datetime | None, field: str) -> tuple[str, list[str]]:
    if since is None:
        return "", []
    return f"WHERE {field} IS NULL OR {field} >= ?", [since.isoformat()]
