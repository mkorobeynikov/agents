---
name: harness-retro
description: Analyze local Codex and Claude Code session history to find evidence-backed recurring collaboration, tool-use, verification, and token-efficiency patterns and propose reviewable improvements. Use for session retrospectives and harness-improvement audits; do not use for ordinary code review or automatically modify agent configuration.
---

# Harness Retro

Use this skill when the user asks for a retrospective over local coding-agent sessions, wants to understand recurring collaboration/tooling failures, or wants reviewable improvements for skills, hooks, project instructions, helper scripts, or personal workflow.

Do not use this skill for ordinary code review, one-off debugging, or direct editing of skills/instructions unless the user separately approves that exact mutation.

## Data Boundary

Before any run that may use an LLM provider, state clearly that discovery, parsing, redaction, SQLite storage, and deterministic metrics are local, while selected redacted excerpts may be sent to the configured provider. Offer `--deterministic-only` when the user wants no model-boundary crossing.

The MVP CLI currently supports a local deterministic evidence pipeline. Treat any provider-backed extraction as an explicit future/opt-in step unless the user has separately approved it for the current run.

## Workflow

Use the bundled CLI:

```bash
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py doctor
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py estimate --since 7d
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py scan --since 7d
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py analyze --since 7d --deterministic-only
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py report weekly
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py candidates list
python3 ~/.agents/skills/harness-retro/scripts/harness_retro.py candidates show <id>
```

Use `doctor` before the first scan. Use `estimate` before a large backfill or any provider-backed run. Use `analyze --deterministic-only` for local-only retrospectives.

The deterministic analysis also maintains a rolling 30-day audit of repeated multi-skill workflows. Weekly reports place these review-only proposals in `Кандидаты на новые skills`. Treat them as discovery leads: confirm that no existing skill covers the workflow end to end before proposing a new skill, and preserve every approval gate used by the composed skills.

Default sources are `~/.codex/sessions/**/*.jsonl` and `~/.claude/projects/**/*.jsonl`. Default state is `~/.local/share/harness-retro/`. Override paths with CLI flags, environment variables, or `HARNESS_RETRO_CONFIG`.

## Evidence Rules

- Every finding must cite concrete event IDs and short redacted excerpts.
- Assistant self-reporting is not success evidence without a tool result, artifact, test, or later user confirmation.
- Missing information is a limitation, not an error.
- One episode is an observation, not a global rule.
- A repeated command or a single skill invocation is not a new-skill opportunity. Require a recurring multi-step decision workflow.
- Cross-session candidates stay reviewable proposals; never edit `SKILL.md`, hooks, `AGENTS.md`, `CLAUDE.md`, memory, or helper scripts without separate explicit approval.

## References

- Read [references/schema.md](references/schema.md) when changing storage, JSON output, adapters, or report fields.
- Read [references/taxonomy.md](references/taxonomy.md) when classifying findings or changing destination rules.
- Read [references/privacy.md](references/privacy.md) before changing redaction, provider payloads, exports, or path display.
- Read [references/candidate-lifecycle.md](references/candidate-lifecycle.md) when reviewing, accepting, rejecting, deferring, applying, or measuring candidates.
