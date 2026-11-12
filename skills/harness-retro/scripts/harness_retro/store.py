from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


def connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "harness-retro.sqlite3")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
            path TEXT PRIMARY KEY,
            harness TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            source_fingerprint TEXT NOT NULL,
            processed_fingerprint TEXT NOT NULL,
            offset INTEGER NOT NULL,
            line_count INTEGER NOT NULL,
            adapter_version TEXT NOT NULL,
            parse_warnings TEXT NOT NULL,
            missing INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            harness TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            parent_session_id TEXT,
            workspace_path TEXT,
            project_key TEXT,
            started_at TEXT,
            ended_at TEXT,
            model TEXT,
            agent_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            parse_warnings TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            timestamp TEXT,
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT,
            tool_name TEXT,
            tool_call_id TEXT,
            status TEXT NOT NULL,
            duration_ms INTEGER,
            input_tokens INTEGER,
            cached_input_tokens INTEGER,
            output_tokens INTEGER,
            file_paths TEXT NOT NULL,
            source_locator_path TEXT NOT NULL,
            source_locator_line INTEGER NOT NULL,
            redaction_tags TEXT NOT NULL,
            raw_type TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_session_sequence ON events(session_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
        CREATE TABLE IF NOT EXISTS findings (
            finding_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            impact TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence TEXT NOT NULL,
            counterevidence TEXT NOT NULL,
            scope_hint TEXT NOT NULL,
            extractor_version TEXT NOT NULL,
            validator_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            category TEXT NOT NULL,
            supporting_findings TEXT NOT NULL,
            contradicting_findings TEXT NOT NULL,
            affected_sessions INTEGER NOT NULL,
            affected_projects INTEGER NOT NULL,
            first_seen_at TEXT,
            last_seen_at TEXT,
            confidence REAL NOT NULL,
            impact TEXT NOT NULL,
            recommended_destination TEXT NOT NULL,
            recommended_scope TEXT NOT NULL,
            proposed_change TEXT NOT NULL,
            expected_effect TEXT NOT NULL,
            risk TEXT NOT NULL,
            measurement_plan TEXT NOT NULL,
            state TEXT NOT NULL,
            rationale TEXT NOT NULL,
            reviewed_at TEXT,
            review_note TEXT,
            deferred_until TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_prefix(path: Path, length: int) -> str:
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def stable_id(*parts: object, length: int = 24) -> str:
    text = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:length]


def get_source(conn: sqlite3.Connection, path: Path) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE path = ?", (str(path),)).fetchone()


def clear_source_import(conn: sqlite3.Connection, path: Path) -> None:
    source_path = str(path)
    session_rows = conn.execute(
        "SELECT session_id FROM sessions WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    session_ids = [row["session_id"] for row in session_rows]
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        conn.execute(f"DELETE FROM events WHERE session_id IN ({placeholders})", session_ids)
        conn.execute(f"DELETE FROM sessions WHERE session_id IN ({placeholders})", session_ids)


def upsert_source(
    conn: sqlite3.Connection,
    *,
    path: Path,
    harness: str,
    size: int,
    mtime: float,
    source_fingerprint: str,
    processed_fingerprint: str,
    offset: int,
    line_count: int,
    adapter_version: str,
    parse_warnings: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO sources(
            path, harness, size, mtime, source_fingerprint, processed_fingerprint, offset,
            line_count, adapter_version, parse_warnings, missing, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(path) DO UPDATE SET
            harness = excluded.harness,
            size = excluded.size,
            mtime = excluded.mtime,
            source_fingerprint = excluded.source_fingerprint,
            processed_fingerprint = excluded.processed_fingerprint,
            offset = excluded.offset,
            line_count = excluded.line_count,
            adapter_version = excluded.adapter_version,
            parse_warnings = excluded.parse_warnings,
            missing = 0,
            updated_at = excluded.updated_at
        """,
        (
            str(path),
            harness,
            size,
            mtime,
            source_fingerprint,
            processed_fingerprint,
            offset,
            line_count,
            adapter_version,
            json_dump(parse_warnings),
            now_iso(),
        ),
    )


def mark_missing_sources(conn: sqlite3.Connection, existing_paths: Iterable[Path]) -> int:
    existing = {str(path) for path in existing_paths}
    rows = conn.execute("SELECT path FROM sources WHERE missing = 0").fetchall()
    missing = [row["path"] for row in rows if row["path"] not in existing]
    for path in missing:
        conn.execute(
            "UPDATE sources SET missing = 1, updated_at = ? WHERE path = ?",
            (now_iso(), path),
        )
    return len(missing)


def insert_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO events(
            event_id, session_id, sequence, timestamp, actor, kind, text, tool_name,
            tool_call_id, status, duration_ms, input_tokens, cached_input_tokens,
            output_tokens, file_paths, source_locator_path, source_locator_line,
            redaction_tags, raw_type
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["event_id"],
            event["session_id"],
            event["sequence"],
            event.get("timestamp"),
            event["actor"],
            event["kind"],
            event.get("text"),
            event.get("tool_name"),
            event.get("tool_call_id"),
            event["status"],
            event.get("duration_ms"),
            event.get("input_tokens"),
            event.get("cached_input_tokens"),
            event.get("output_tokens"),
            json_dump(event.get("file_paths", [])),
            event["source_locator_path"],
            event["source_locator_line"],
            json_dump(event.get("redaction_tags", [])),
            event["raw_type"],
        ),
    )


def refresh_sessions_for_source(
    conn: sqlite3.Connection,
    *,
    source_path: Path,
    harness: str,
    source_fingerprint: str,
    parse_warnings: list[str],
) -> None:
    rows = conn.execute(
        """
        SELECT
            session_id,
            MIN(timestamp) AS started_at,
            MAX(timestamp) AS ended_at,
            COUNT(*) AS event_count,
            MAX(COALESCE(input_tokens, 0)) AS input_tokens,
            MAX(COALESCE(output_tokens, 0)) AS output_tokens
        FROM events
        WHERE source_locator_path = ?
        GROUP BY session_id
        """,
        (str(source_path),),
    ).fetchall()
    for row in rows:
        details = conn.execute(
            """
            SELECT parent_session_id, workspace_path, model, agent_kind
            FROM (
                SELECT
                    session_id,
                    NULL AS parent_session_id,
                    NULL AS workspace_path,
                    NULL AS model,
                    'unknown' AS agent_kind
            )
            WHERE session_id = ?
            """,
            (row["session_id"],),
        ).fetchone()
        event_rows = conn.execute(
            """
            SELECT text, raw_type
            FROM events
            WHERE session_id = ? AND source_locator_path = ?
            ORDER BY sequence
            LIMIT 1
            """,
            (row["session_id"], str(source_path)),
        ).fetchone()
        agent_kind = details["agent_kind"] if details else "unknown"
        raw_type = event_rows["raw_type"] if event_rows else ""
        status = "interrupted" if "interrupted" in raw_type.lower() else "unknown"
        conn.execute(
            """
            INSERT INTO sessions(
                session_id, harness, source_path, source_fingerprint, parent_session_id,
                workspace_path, project_key, started_at, ended_at, model, agent_kind,
                status, event_count, parse_warnings
            )
            VALUES(?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                harness = excluded.harness,
                source_path = excluded.source_path,
                source_fingerprint = excluded.source_fingerprint,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                agent_kind = excluded.agent_kind,
                status = excluded.status,
                event_count = excluded.event_count,
                parse_warnings = excluded.parse_warnings
            """,
            (
                row["session_id"],
                harness,
                str(source_path),
                source_fingerprint,
                row["started_at"],
                row["ended_at"],
                agent_kind,
                status,
                row["event_count"],
                json_dump(parse_warnings),
            ),
        )


def save_session_meta(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    harness: str,
    source_path: Path,
    source_fingerprint: str,
    parent_session_id: str | None,
    workspace_path: str | None,
    model: str | None,
    agent_kind: str,
    parse_warnings: list[str],
) -> None:
    project_key = stable_id(workspace_path or str(source_path.parent), length=16)
    current = conn.execute(
        "SELECT started_at, ended_at, event_count FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    started_at = current["started_at"] if current else None
    ended_at = current["ended_at"] if current else None
    event_count = current["event_count"] if current else 0
    conn.execute(
        """
        INSERT INTO sessions(
            session_id, harness, source_path, source_fingerprint, parent_session_id,
            workspace_path, project_key, started_at, ended_at, model, agent_kind,
            status, event_count, parse_warnings
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            harness = excluded.harness,
            source_path = excluded.source_path,
            source_fingerprint = excluded.source_fingerprint,
            parent_session_id = COALESCE(excluded.parent_session_id, sessions.parent_session_id),
            workspace_path = COALESCE(excluded.workspace_path, sessions.workspace_path),
            project_key = COALESCE(excluded.project_key, sessions.project_key),
            model = COALESCE(excluded.model, sessions.model),
            agent_kind = CASE
                WHEN sessions.agent_kind = 'unknown' THEN excluded.agent_kind
                ELSE sessions.agent_kind
            END,
            parse_warnings = excluded.parse_warnings
        """,
        (
            session_id,
            harness,
            str(source_path),
            source_fingerprint,
            parent_session_id,
            workspace_path,
            project_key,
            started_at,
            ended_at,
            model,
            agent_kind,
            event_count,
            json_dump(parse_warnings),
        ),
    )


def update_session_bounds(conn: sqlite3.Connection, source_path: Path) -> None:
    rows = conn.execute(
        """
        SELECT session_id, MIN(timestamp) AS started_at, MAX(timestamp) AS ended_at, COUNT(*) AS event_count
        FROM events
        WHERE source_locator_path = ?
        GROUP BY session_id
        """,
        (str(source_path),),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE sessions
            SET started_at = ?, ended_at = ?, event_count = ?
            WHERE session_id = ?
            """,
            (row["started_at"], row["ended_at"], row["event_count"], row["session_id"]),
        )


def save_findings(conn: sqlite3.Connection, findings: list[dict[str, Any]]) -> None:
    created_at = now_iso()
    for finding in findings:
        conn.execute(
            """
            INSERT OR REPLACE INTO findings(
                finding_id, session_id, category, title, description, impact, confidence,
                evidence, counterevidence, scope_hint, extractor_version,
                validator_status, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding["finding_id"],
                finding["session_id"],
                finding["category"],
                finding["title"],
                finding["description"],
                finding["impact"],
                finding["confidence"],
                json_dump(finding.get("evidence", [])),
                json_dump(finding.get("counterevidence", [])),
                finding["scope_hint"],
                finding["extractor_version"],
                finding["validator_status"],
                created_at,
            ),
        )


def replace_deterministic_findings(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
) -> None:
    conn.execute("DELETE FROM findings WHERE extractor_version LIKE 'deterministic-%'")
    save_findings(conn, findings)


def save_candidates(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> None:
    protected_states = {
        "accepted",
        "rejected",
        "deferred",
        "applied",
        "measuring",
        "confirmed",
        "rolled-back",
    }
    for candidate in candidates:
        existing = conn.execute(
            "SELECT state, reviewed_at, review_note, deferred_until FROM candidates WHERE fingerprint = ?",
            (candidate["fingerprint"],),
        ).fetchone()
        state = candidate["state"]
        reviewed_at = candidate.get("reviewed_at")
        review_note = candidate.get("review_note")
        deferred_until = candidate.get("deferred_until")
        if existing and existing["state"] in protected_states:
            state = existing["state"]
            reviewed_at = existing["reviewed_at"]
            review_note = existing["review_note"]
            deferred_until = existing["deferred_until"]
        conn.execute(
            """
            INSERT INTO candidates(
                candidate_id, fingerprint, title, hypothesis, category,
                supporting_findings, contradicting_findings, affected_sessions,
                affected_projects, first_seen_at, last_seen_at, confidence, impact,
                recommended_destination, recommended_scope, proposed_change,
                expected_effect, risk, measurement_plan, state, rationale,
                reviewed_at, review_note, deferred_until, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                title = excluded.title,
                hypothesis = excluded.hypothesis,
                category = excluded.category,
                supporting_findings = excluded.supporting_findings,
                contradicting_findings = excluded.contradicting_findings,
                affected_sessions = excluded.affected_sessions,
                affected_projects = excluded.affected_projects,
                first_seen_at = excluded.first_seen_at,
                last_seen_at = excluded.last_seen_at,
                confidence = excluded.confidence,
                impact = excluded.impact,
                recommended_destination = excluded.recommended_destination,
                recommended_scope = excluded.recommended_scope,
                proposed_change = excluded.proposed_change,
                expected_effect = excluded.expected_effect,
                risk = excluded.risk,
                measurement_plan = excluded.measurement_plan,
                state = excluded.state,
                rationale = excluded.rationale,
                reviewed_at = excluded.reviewed_at,
                review_note = excluded.review_note,
                deferred_until = excluded.deferred_until,
                updated_at = excluded.updated_at
            """,
            (
                candidate["candidate_id"],
                candidate["fingerprint"],
                candidate["title"],
                candidate["hypothesis"],
                candidate["category"],
                json_dump(candidate.get("supporting_findings", [])),
                json_dump(candidate.get("contradicting_findings", [])),
                candidate["affected_sessions"],
                candidate["affected_projects"],
                candidate.get("first_seen_at"),
                candidate.get("last_seen_at"),
                candidate["confidence"],
                candidate["impact"],
                candidate["recommended_destination"],
                candidate["recommended_scope"],
                candidate["proposed_change"],
                candidate["expected_effect"],
                candidate["risk"],
                candidate["measurement_plan"],
                state,
                candidate["rationale"],
                reviewed_at,
                review_note,
                deferred_until,
                now_iso(),
            ),
        )


def mark_unmatched_candidates_stale(
    conn: sqlite3.Connection,
    *,
    categories: set[str],
    active_fingerprints: set[str],
) -> None:
    if not categories:
        return
    category_placeholders = ",".join("?" for _ in categories)
    params: list[str] = [*sorted(categories)]
    active_clause = ""
    if active_fingerprints:
        fingerprint_placeholders = ",".join("?" for _ in active_fingerprints)
        active_clause = f"AND fingerprint NOT IN ({fingerprint_placeholders})"
        params.extend(sorted(active_fingerprints))
    conn.execute(
        f"""
        UPDATE candidates
        SET state = 'stale', updated_at = ?
        WHERE category IN ({category_placeholders})
          AND state IN ('observed', 'corroborated', 'proposed')
          {active_clause}
        """,
        [now_iso(), *params],
    )


def candidate_by_id(conn: sqlite3.Connection, candidate_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM candidates
        WHERE candidate_id = ? OR fingerprint = ?
        """,
        (candidate_id, candidate_id),
    ).fetchone()


def set_candidate_state(
    conn: sqlite3.Connection,
    candidate_id: str,
    state: str,
    *,
    note: str | None = None,
    deferred_until: str | None = None,
) -> bool:
    row = candidate_by_id(conn, candidate_id)
    if not row:
        return False
    conn.execute(
        """
        UPDATE candidates
        SET state = ?, reviewed_at = ?, review_note = ?, deferred_until = ?, updated_at = ?
        WHERE candidate_id = ?
        """,
        (state, now_iso(), note, deferred_until, now_iso(), row["candidate_id"]),
    )
    return True
