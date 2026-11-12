from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from harness_retro.config import Config
from harness_retro.adapters.common import status_from_payload
from harness_retro.metrics import _missing_verification, _workflow_patterns_overlap, run_analysis
from harness_retro.reporting import write_weekly_report
from harness_retro.scanner import scan_sources
from harness_retro.store import (
    connect,
    json_load,
    mark_unmatched_candidates_stale,
    set_candidate_state,
)


FIXTURES = Path(__file__).parent / "fixtures"


class HarnessRetroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.codex_dir = root / "codex" / "sessions"
        self.claude_dir = root / "claude" / "projects"
        self.codex_dir.mkdir(parents=True)
        self.claude_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "codex-session.jsonl", self.codex_dir / "codex-session.jsonl")
        shutil.copy(
            FIXTURES / "codex-synthetic-context.jsonl",
            self.codex_dir / "codex-synthetic-context.jsonl",
        )
        shutil.copy(
            FIXTURES / "codex-workflow-sessions.jsonl",
            self.codex_dir / "codex-workflow-sessions.jsonl",
        )
        shutil.copy(FIXTURES / "claude-session.jsonl", self.claude_dir / "claude-session.jsonl")
        self.config = Config(
            data_dir=self.data_dir,
            codex_paths=[self.codex_dir],
            claude_paths=[self.claude_dir],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scan_redacts_and_is_idempotent(self) -> None:
        conn = connect(self.data_dir)
        first = scan_sources(conn, self.config)
        second = scan_sources(conn, self.config)
        self.assertGreater(first["imported_events"], 0)
        self.assertEqual(second["imported_events"], 0)
        self.assertGreaterEqual(first["parse_warnings"], 1)
        text = "\n".join(row["text"] or "" for row in conn.execute("SELECT text FROM events"))
        self.assertNotIn("supersecret-token-value", text)
        self.assertNotIn("secretbearertoken1234567890", text)
        tags = []
        for row in conn.execute("SELECT redaction_tags FROM events"):
            tags.extend(json_load(row["redaction_tags"], []))
        self.assertIn("sensitive-env", tags)
        self.assertIn("authorization", tags)
        conn.close()

    def test_status_normalizes_explicit_success_and_failure(self) -> None:
        self.assertEqual(status_from_payload({"is_error": False}), "success")
        self.assertEqual(status_from_payload({}, "Process exited with code 0"), "success")
        self.assertEqual(status_from_payload({}, "Process exited with code 2"), "failure")

    def test_analysis_produces_evidence_backed_candidate(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        result = run_analysis(conn, self.config)
        self.assertGreaterEqual(result["accepted_findings"], 2)
        rows = conn.execute("SELECT * FROM candidates").fetchall()
        self.assertTrue(rows)
        repeated = [row for row in rows if row["category"] == "repeated-tool-failure"]
        self.assertTrue(repeated)
        self.assertEqual(repeated[0]["state"], "corroborated")
        finding_rows = conn.execute("SELECT evidence, validator_status FROM findings").fetchall()
        self.assertTrue(all(row["validator_status"] == "accepted" for row in finding_rows))
        self.assertTrue(all(json_load(row["evidence"], []) for row in finding_rows))
        conn.close()

    def test_candidate_lifecycle_update(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        candidate = conn.execute("SELECT candidate_id FROM candidates LIMIT 1").fetchone()
        self.assertIsNotNone(candidate)
        self.assertTrue(set_candidate_state(conn, candidate["candidate_id"], "accepted", note="reviewed"))
        conn.commit()
        updated = conn.execute(
            "SELECT state, review_note FROM candidates WHERE candidate_id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
        self.assertEqual(updated["state"], "accepted")
        self.assertEqual(updated["review_note"], "reviewed")
        run_analysis(conn, self.config)
        preserved = conn.execute(
            "SELECT state, review_note FROM candidates WHERE candidate_id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
        self.assertEqual(preserved["state"], "accepted")
        self.assertEqual(preserved["review_note"], "reviewed")
        conn.close()

    def test_analysis_proposes_repeated_multi_skill_workflow(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        candidate = conn.execute(
            "SELECT * FROM candidates WHERE category = 'reusable-workflow-pattern'"
        ).fetchone()
        self.assertIsNotNone(candidate)
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM candidates WHERE category = 'reusable-workflow-pattern'"
        ).fetchone()["count"]
        self.assertEqual(count, 1)
        self.assertEqual(candidate["state"], "corroborated")
        self.assertEqual(candidate["recommended_destination"], "skill")
        self.assertGreaterEqual(candidate["affected_sessions"], 3)
        self.assertGreaterEqual(candidate["affected_projects"], 2)
        self.assertIn("sdd-delivery", candidate["proposed_change"])
        self.assertIn("sdd-propose", candidate["title"])
        self.assertIn("ship", candidate["title"])
        conn.close()

    def test_workflow_variants_in_the_same_family_are_consolidated(self) -> None:
        self.assertTrue(
            _workflow_patterns_overlap(
                ("sdd-propose", "sdd-tasks", "sdd-apply", "sdd-archive"),
                {"one", "two", "three"},
                ("task-tracker", "sdd-tasks", "ship"),
                {"four", "five", "six"},
            )
        )

    def test_analysis_ignores_synthetic_user_context(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        synthetic_regressions = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-synthetic-context'
              AND category = 'user-discovered-regression'
            """
        ).fetchone()["count"]
        notification_findings = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-failed-notification'
              AND category = 'verification-ignored'
            """
        ).fetchone()["count"]
        notification_regressions = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-failed-notification'
              AND category = 'user-discovered-regression'
            """
        ).fetchone()["count"]
        failed_test_regressions = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-user-found-failing-tests'
              AND category = 'user-discovered-regression'
            """
        ).fetchone()["count"]
        negated_notification_findings = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-negated-completion'
              AND category = 'verification-ignored'
            """
        ).fetchone()["count"]
        verified_completion_findings = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM findings
            WHERE session_id = 'codex-successful-verification'
              AND category = 'missing-verification'
            """
        ).fetchone()["count"]
        self.assertEqual(synthetic_regressions, 0)
        self.assertEqual(notification_findings, 1)
        self.assertEqual(notification_regressions, 0)
        self.assertEqual(failed_test_regressions, 1)
        self.assertEqual(negated_notification_findings, 0)
        self.assertEqual(verified_completion_findings, 0)
        conn.close()

    def test_missing_verification_is_scoped_to_runtime_implementation(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        counts = {
            row["session_id"]: row["count"]
            for row in conn.execute(
                """
                SELECT session_id, COUNT(*) AS count
                FROM findings
                WHERE category = 'missing-verification'
                  AND session_id IN (
                    'codex-sdd-proposal-completion',
                    'codex-explicit-verification-limitation',
                    'codex-docs-completion',
                    'codex-git-completion',
                    'codex-unverified-implementation',
                    'codex-code-and-docs-completion',
                    'codex-explicit-pending-verification',
                    'codex-git-completion-with-secondary-code',
                    'codex-standalone-fixed-docs'
                  )
                GROUP BY session_id
                """
            ).fetchall()
        }
        self.assertNotIn("codex-sdd-proposal-completion", counts)
        self.assertNotIn("codex-explicit-verification-limitation", counts)
        self.assertNotIn("codex-docs-completion", counts)
        self.assertNotIn("codex-git-completion", counts)
        self.assertNotIn("codex-git-completion-with-secondary-code", counts)
        self.assertNotIn("codex-standalone-fixed-docs", counts)
        self.assertNotIn("codex-explicit-pending-verification", counts)
        self.assertEqual(counts["codex-unverified-implementation"], 1)
        self.assertEqual(counts["codex-code-and-docs-completion"], 1)
        conn.close()

    def test_missing_verification_uses_the_current_user_turn_as_its_window(self) -> None:
        events = [
            {
                "event_id": "user-1",
                "sequence": 1_000,
                "actor": "user",
                "kind": "message",
                "text": "Исправь дефект.",
                "tool_call_id": None,
                "tool_name": None,
                "status": "unknown",
                "raw_type": "message",
            },
            {
                "event_id": "call-1",
                "sequence": 2_000,
                "actor": "assistant",
                "kind": "tool_call",
                "text": "pytest",
                "tool_call_id": "verify-1",
                "tool_name": "shell",
                "status": "unknown",
                "raw_type": "tool_call",
            },
            {
                "event_id": "result-1",
                "sequence": 3_000,
                "actor": "tool",
                "kind": "tool_result",
                "text": "12 tests passed",
                "tool_call_id": "verify-1",
                "tool_name": "shell",
                "status": "success",
                "raw_type": "tool_result",
            },
        ]
        events.extend(
            {
                "event_id": f"reasoning-{index}",
                "sequence": 4_000 + index * 1_000,
                "actor": "assistant",
                "kind": "reasoning",
                "text": "Продолжаю работу.",
                "tool_call_id": None,
                "tool_name": None,
                "status": "unknown",
                "raw_type": "reasoning",
            }
            for index in range(40)
        )
        events.append(
            {
                "event_id": "claim-1",
                "sequence": 50_000,
                "actor": "assistant",
                "kind": "message",
                "text": "Готово. Реализация изменена.",
                "tool_call_id": None,
                "tool_name": None,
                "status": "unknown",
                "raw_type": "message",
            }
        )

        self.assertEqual(_missing_verification("session-1", events), [])

    def test_analysis_replaces_previous_deterministic_findings(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        conn.execute(
            """
            INSERT INTO findings(
                finding_id, session_id, category, title, description, impact,
                confidence, evidence, counterevidence, scope_hint,
                extractor_version, validator_status, created_at
            )
            VALUES(
                'find-old-noise', 'codex-main-1', 'user-discovered-regression',
                'Old noise', 'Old noise', 'high', 0.9, '[]', '[]', 'personal',
                'deterministic-mvp-v1', 'accepted', '2026-08-29T00:00:00+00:00'
            )
            """
        )
        run_analysis(conn, self.config)
        old = conn.execute(
            "SELECT COUNT(*) AS count FROM findings WHERE extractor_version = 'deterministic-mvp-v1'"
        ).fetchone()["count"]
        self.assertEqual(old, 0)
        conn.close()

    def test_stale_candidate_reactivates_when_evidence_returns(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        candidate = conn.execute(
            "SELECT fingerprint FROM candidates WHERE category = 'user-discovered-regression'"
        ).fetchone()
        self.assertIsNotNone(candidate)
        mark_unmatched_candidates_stale(
            conn,
            categories={"user-discovered-regression"},
            active_fingerprints=set(),
        )
        stale = conn.execute(
            "SELECT state FROM candidates WHERE fingerprint = ?",
            (candidate["fingerprint"],),
        ).fetchone()
        self.assertEqual(stale["state"], "stale")
        run_analysis(conn, self.config)
        reactivated = conn.execute(
            "SELECT state FROM candidates WHERE fingerprint = ?",
            (candidate["fingerprint"],),
        ).fetchone()
        self.assertEqual(reactivated["state"], "corroborated")
        conn.close()

    def test_report_contains_no_raw_secrets(self) -> None:
        conn = connect(self.data_dir)
        scan_sources(conn, self.config)
        run_analysis(conn, self.config)
        paths = write_weekly_report(conn, self.config)
        text = paths["markdown"].read_text(encoding="utf-8")
        data = paths["json"].read_text(encoding="utf-8")
        self.assertIn("Harness Retro", text)
        self.assertIn("## Кандидаты на новые skills", text)
        self.assertIn("reusable-workflow-pattern", text)
        self.assertNotIn("supersecret-token-value", text + data)
        self.assertNotIn("secretbearertoken1234567890", text + data)
        conn.close()


if __name__ == "__main__":
    unittest.main()
