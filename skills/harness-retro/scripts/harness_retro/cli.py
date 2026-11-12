from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from harness_retro.config import Config, load_config, parse_since
from harness_retro.metrics import build_metrics, run_analysis
from harness_retro.providers import codex_provider_status
from harness_retro.reporting import write_weekly_report
from harness_retro.scanner import data_boundary_message, estimate_sources, scan_sources
from harness_retro.store import candidate_by_id, connect, json_load, set_candidate_state


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(
        config_path=args.config,
        data_dir=args.data_dir,
        codex_path=args.codex_path,
        claude_path=args.claude_path,
        report_absolute_paths=args.report_absolute_paths,
        redaction_regex=args.redact_regex,
    )
    try:
        return args.func(args, config)
    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze local coding-agent harness sessions.")
    parser.add_argument("--config", help="Path to JSON config. Defaults to HARNESS_RETRO_CONFIG or data_dir/config.json.")
    parser.add_argument("--data-dir", help="State directory. Defaults to ~/.local/share/harness-retro.")
    parser.add_argument("--codex-path", action="append", help="Codex sessions directory or JSONL file.")
    parser.add_argument("--claude-path", action="append", help="Claude Code projects directory or JSONL file.")
    parser.add_argument("--report-absolute-paths", action="store_true", help="Allow absolute paths in local reports.")
    parser.add_argument("--redact-regex", action="append", default=[], help="Additional redaction regex.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check paths, SQLite, provider status, and data boundary.")
    doctor.set_defaults(func=cmd_doctor)

    estimate = subparsers.add_parser("estimate", help="Estimate scan size and potential provider payload.")
    estimate.add_argument("--since", default="7d")
    estimate.set_defaults(func=cmd_estimate)

    scan = subparsers.add_parser("scan", help="Normalize JSONL sessions into SQLite.")
    scan.add_argument("--since", default=None)
    scan.set_defaults(func=cmd_scan)

    analyze = subparsers.add_parser("analyze", help="Extract findings and aggregate candidates.")
    analyze.add_argument("--since", default="7d")
    analyze.add_argument("--deterministic-only", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    report = subparsers.add_parser("report", help="Write reports.")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    weekly = report_sub.add_parser("weekly", help="Write weekly Markdown and JSON reports.")
    weekly.add_argument("--since", default="7d")
    weekly.add_argument("--output-dir")
    weekly.set_defaults(func=cmd_report_weekly)

    candidates = subparsers.add_parser("candidates", help="Review improvement candidates.")
    candidate_sub = candidates.add_subparsers(dest="candidate_command", required=True)
    list_cmd = candidate_sub.add_parser("list", help="List candidates.")
    list_cmd.add_argument("--state")
    list_cmd.set_defaults(func=cmd_candidates_list)
    show_cmd = candidate_sub.add_parser("show", help="Show one candidate.")
    show_cmd.add_argument("candidate_id")
    show_cmd.set_defaults(func=cmd_candidates_show)
    accept_cmd = candidate_sub.add_parser("accept", help="Mark candidate direction accepted.")
    accept_cmd.add_argument("candidate_id")
    accept_cmd.add_argument("--note")
    accept_cmd.set_defaults(func=cmd_candidates_accept)
    reject_cmd = candidate_sub.add_parser("reject", help="Reject candidate.")
    reject_cmd.add_argument("candidate_id")
    reject_cmd.add_argument("--reason", required=True)
    reject_cmd.set_defaults(func=cmd_candidates_reject)
    defer_cmd = candidate_sub.add_parser("defer", help="Defer candidate review.")
    defer_cmd.add_argument("candidate_id")
    defer_cmd.add_argument("--until", required=True)
    defer_cmd.add_argument("--reason")
    defer_cmd.set_defaults(func=cmd_candidates_defer)
    return parser


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    print("Harness Retro doctor")
    print(f"Data dir: {config.data_dir}")
    conn = connect(config.data_dir)
    conn.execute("SELECT 1").fetchone()
    conn.close()
    print("SQLite: ok")
    for label, paths in (("Codex", config.codex_paths), ("Claude Code", config.claude_paths)):
        for path in paths:
            state = "ok" if path.exists() else "missing"
            print(f"{label} source: {path} [{state}]")
    provider = codex_provider_status()
    print(f"Provider {provider.name}: {'available' if provider.available else 'unavailable'}")
    print(provider.detail)
    print(f"Data boundary: {data_boundary_message()}")
    return 0


def cmd_estimate(args: argparse.Namespace, config: Config) -> int:
    since = parse_since(args.since)
    result = estimate_sources(config, since)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_scan(args: argparse.Namespace, config: Config) -> int:
    since = parse_since(args.since)
    conn = connect(config.data_dir)
    result = scan_sources(conn, config, since)
    conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(args: argparse.Namespace, config: Config) -> int:
    since = parse_since(args.since)
    if not args.deterministic_only:
        print(f"Data boundary: {data_boundary_message()}")
        print("Provider-backed extraction is not implemented in the MVP CLI; running deterministic pipeline only.")
    conn = connect(config.data_dir)
    result = run_analysis(conn, config, since)
    conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_report_weekly(args: argparse.Namespace, config: Config) -> int:
    since = parse_since(args.since)
    conn = connect(config.data_dir)
    paths = write_weekly_report(
        conn,
        config,
        since,
        Path(args.output_dir).expanduser().resolve() if args.output_dir else None,
    )
    conn.close()
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
    return 0


def cmd_candidates_list(args: argparse.Namespace, config: Config) -> int:
    conn = connect(config.data_dir)
    where = "WHERE state = ?" if args.state else ""
    params: list[Any] = [args.state] if args.state else []
    rows = conn.execute(
        f"""
        SELECT candidate_id, state, impact, affected_sessions, affected_projects,
               recommended_destination, recommended_scope, title
        FROM candidates
        {where}
        ORDER BY updated_at DESC
        """,
        params,
    ).fetchall()
    conn.close()
    for row in rows:
        print(
            f"{row['candidate_id']} [{row['state']}/{row['impact']}] "
            f"sessions={row['affected_sessions']} projects={row['affected_projects']} "
            f"dest={row['recommended_destination']} scope={row['recommended_scope']} — {row['title']}"
        )
    if not rows:
        print("No candidates.")
    return 0


def cmd_candidates_show(args: argparse.Namespace, config: Config) -> int:
    conn = connect(config.data_dir)
    row = candidate_by_id(conn, args.candidate_id)
    if not row:
        conn.close()
        print(f"Candidate not found: {args.candidate_id}", file=sys.stderr)
        return 1
    candidate = dict(row)
    candidate["supporting_findings"] = json_load(candidate["supporting_findings"], [])
    candidate["contradicting_findings"] = json_load(candidate["contradicting_findings"], [])
    print(json.dumps(candidate, ensure_ascii=False, indent=2))
    conn.close()
    return 0


def cmd_candidates_accept(args: argparse.Namespace, config: Config) -> int:
    return _set_candidate(config, args.candidate_id, "accepted", note=args.note)


def cmd_candidates_reject(args: argparse.Namespace, config: Config) -> int:
    return _set_candidate(config, args.candidate_id, "rejected", note=args.reason)


def cmd_candidates_defer(args: argparse.Namespace, config: Config) -> int:
    return _set_candidate(config, args.candidate_id, "deferred", note=args.reason, deferred_until=args.until)


def _set_candidate(
    config: Config,
    candidate_id: str,
    state: str,
    *,
    note: str | None = None,
    deferred_until: str | None = None,
) -> int:
    conn = connect(config.data_dir)
    ok = set_candidate_state(conn, candidate_id, state, note=note, deferred_until=deferred_until)
    conn.commit()
    conn.close()
    if not ok:
        print(f"Candidate not found: {candidate_id}", file=sys.stderr)
        return 1
    print(f"{candidate_id}: {state}")
    return 0
