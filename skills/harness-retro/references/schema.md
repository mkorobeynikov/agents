# Harness Retro Schema

The CLI stores normalized data in SQLite under the configured data directory. Raw JSONL payloads are not copied into the database by default.

## Session

Required fields:

- `session_id`
- `harness`: `codex`, `claude-code`, or a future adapter name
- `source_path`
- `source_fingerprint`
- `parent_session_id`
- `workspace_path`
- `project_key`
- `started_at`
- `ended_at`
- `model`
- `agent_kind`: `main`, `subagent`, or `unknown`
- `status`: `complete`, `interrupted`, or `unknown`
- `event_count`
- `parse_warnings`

`project_key` is a stable local hash. Exported reports should not show absolute project paths unless `report_absolute_paths` is enabled.

## Event

Required fields:

- `event_id`
- `session_id`
- `sequence`
- `timestamp`
- `actor`: `user`, `assistant`, `tool`, or `system`
- `kind`: `message`, `reasoning`, `tool_call`, `tool_result`, `approval`, `edit`, `usage`, `lifecycle`, or `unknown`
- `text`
- `tool_name`
- `tool_call_id`
- `status`: `success`, `failure`, `denied`, `interrupted`, or `unknown`
- `duration_ms`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `file_paths`
- `source_locator_path`
- `source_locator_line`
- `redaction_tags`
- `raw_type`

Unknown source records should become `kind: unknown` events with `raw_type`. Broken JSONL lines should produce source warnings, not abort the entire scan.

## Finding

A finding is a single-session observation. It must include evidence event IDs and redacted excerpts.

Required fields:

- `finding_id`
- `session_id`
- `category`
- `title`
- `description`
- `impact`
- `confidence`
- `evidence`
- `counterevidence`
- `scope_hint`
- `extractor_version`
- `validator_status`

## Candidate

A candidate aggregates findings into a reviewable improvement hypothesis.

Required fields:

- `candidate_id`
- `fingerprint`
- `title`
- `hypothesis`
- `category`
- `supporting_findings`
- `contradicting_findings`
- `affected_sessions`
- `affected_projects`
- `first_seen_at`
- `last_seen_at`
- `confidence`
- `impact`
- `recommended_destination`
- `recommended_scope`
- `proposed_change`
- `expected_effect`
- `risk`
- `measurement_plan`
- `state`
- `rationale`
- `reviewed_at`

Preserve `rationale`; it explains why the candidate exists and is needed for later deletion, rollback, or consolidation.

## Analysis Snapshot Semantics

Each deterministic `analyze` run replaces findings from previous deterministic extractor versions. Candidates produced by the current run are refreshed in place; unmatched unreviewed candidates become `stale`. Human-reviewed states such as `accepted`, `rejected`, `deferred`, `applied`, `measuring`, and `confirmed` are preserved.
