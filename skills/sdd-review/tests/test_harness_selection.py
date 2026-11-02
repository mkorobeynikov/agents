import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "review_runner", Path(__file__).resolve().parents[1] / "scripts/run_cross_review.py"
)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class HarnessSelectionTest(unittest.TestCase):
    def test_both_axes_use_caller_backend(self):
        for caller in ("codex", "claude"):
            with self.subTest(caller=caller):
                args = SimpleNamespace(repo=Path.cwd(), change_id="test-change", baseline=None,
                                       code_repo=[], part=None, pathspec=[], caller=caller,
                                       codex_bin="codex", claude_bin="claude", codex_model=None,
                                       claude_model=None, codex_reasoning_effort=None, timeout=5)
                spec = SimpleNamespace(repo=Path.cwd(), branch="feature/test", baseline="HEAD",
                                       baseline_commit="test", tree_state="dirty", diff_command="git diff")
                snapshot = SimpleNamespace(spec=spec, code_repos=[], change_id="test-change",
                                           part=None, pathspecs=[])

                def response(*call):
                    return {"axis": call[-2], "findings": [], "summary": "Проверено", "complete": True}

                with patch.object(runner, "collect_snapshot", return_value=snapshot), \
                     patch.object(runner, "resolve_executable", side_effect=lambda name: name), \
                     patch.object(runner, "cli_version", return_value="test"), \
                     patch.object(runner, "diff_files_for", return_value={}, create=True), \
                     patch.object(runner, "requirements_prompt", return_value="requirements"), \
                     patch.object(runner, "standards_prompt", return_value="standards"), \
                     patch.object(runner, "run_codex", side_effect=response) as codex, \
                     patch.object(runner, "run_claude", side_effect=response) as claude:
                    result = runner.run_review(args)
                selected, other = (codex, claude) if caller == "codex" else (claude, codex)
                self.assertEqual(selected.call_count, 2)
                other.assert_not_called()
                self.assertEqual(result["reviewer"]["backend"], caller)
                self.assertEqual({result[a]["axis"] for a in ("requirements", "standards")},
                                 {"requirements", "standards"})

    def test_codex_starts_ephemeral_read_only_session(self):
        payload = {"axis": "requirements", "findings": [], "summary": "Проверено", "complete": True}
        with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr="")) as process:
            runner.run_codex("codex", None, None, Path.cwd(), Path("schema.json"), "review", 5)
        command = process.call_args.args[0]
        self.assertEqual(command[:3], ["codex", "exec", "--ephemeral"])
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertNotIn("resume", command)
        self.assertNotIn("fork", command)
        self.assertEqual(process.call_args.kwargs["env"]["SDD_REVIEW_LEAF"], "1")

    def test_claude_starts_fresh_read_only_session(self):
        payload = {"structured_output": {"axis": "standards", "findings": [],
                                          "summary": "Проверено", "complete": True}}
        with patch.object(Path, "read_text", return_value="{}"), \
             patch.object(runner.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stdout=json.dumps(payload), stderr="")) as process:
            runner.run_claude("claude", None, Path.cwd(), [], Path("schema.json"), "review", 5)
        command = process.call_args.args[0]
        self.assertIn("--no-session-persistence", command)
        self.assertEqual(command[command.index("--tools") + 1], "Read,Grep,Glob")
        self.assertNotIn("--resume", command)
        self.assertNotIn("--continue", command)


if __name__ == "__main__":
    unittest.main()
