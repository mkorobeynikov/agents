---
name: ship
description: "Analyze changes, update README if needed, commit with conventional commits (Russian messages), and push. Use after completing a feature, bugfix, or any implementation work."
allowed-tools: Read, Edit,
  Bash(git status:*), Bash(git diff:*), Bash(git add:*),
  Bash(git commit:*), Bash(git push:*), Bash(git branch:*)
---

# Ship — commit and push completed work

Analyzes the current git diff, optionally updates README, creates a conventional commit with a Russian-language message, and pushes to remote.

## When to Use

- User invokes `/ship` (Claude Code) or `$ship` (Codex) after finishing a feature, bugfix, or refactor
- User asks to "commit and push", "ship it", "закоммить и запуши"

## Workflow

### Step 1: Analyze changes

Run `git status` (never use `-uall` flag) and `git diff` (both staged and unstaged) to understand what changed.

**Auto-detect commit type from the diff:**

| Type | When to use |
|------|------------|
| `feat` | New functionality: new files with business logic, new endpoints, new components |
| `fix` | Bug corrections in existing code |
| `refactor` | Code restructuring without behavior change (renames, extractions, moves) |
| `chore` | Dependencies, configs, CI/CD, build scripts |
| `docs` | Only documentation files changed |
| `style` | Formatting-only changes (whitespace, semicolons, quotes) |
| `perf` | Performance optimizations |

**Auto-detect scope** from the primary directory or module of changed files. Use the most specific meaningful name (e.g. `auth`, `api`, `ui`). Omit scope if changes span the entire project.

If the commit type is genuinely ambiguous, ask the user. Do not guess.

### Step 2: Update README (if needed)

Read `README.md` in the repo root (if it exists). Compare with the diff and decide whether an update is needed.

**Update README when:**
- New API endpoints or CLI commands were added
- Public interfaces or behavior changed
- New dependencies that require setup were added
- Project structure changed significantly
- Configuration or environment variables were added/changed

**Do NOT update README when:**
- Changes are internal (refactoring, bug fixes, implementation details)
- Only tests, CI, or dev tooling changed
- Changes are cosmetic or minor

If no update is needed, skip silently — do not mention it.

### Step 3: Stage files

Stage all relevant changed files explicitly by name using `git add <file1> <file2> ...`.

**Never stage:**
- `.env`, `.env.*` files
- Files containing API keys, tokens, passwords, or credentials
- `node_modules/`, `__pycache__/`, build artifacts
- OS files (`.DS_Store`, `Thumbs.db`)

If updated README in step 2, include it in staging.

### Step 4: Commit

Create a commit with this message format:

```
<type>(<scope>): <описание на русском>

<тело — опционально>
```

**Rules:**
- First line: imperative mood, lowercase start, max 72 characters
- Body: only for non-trivial changes, explain WHY not WHAT
- Breaking changes: use `!` suffix — `feat!:` or `fix!:` — and describe in body
- Use HEREDOC to pass the message to `git commit -m`

### Step 5: Squash branch commits

A feature branch should arrive as a single commit. Determine the base branch and count what the current branch carries on top of it:

```bash
base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
merge_base=$(git merge-base HEAD "$base")
git rev-list --count "$merge_base"..HEAD
```

If the count is greater than 1, list the commits for the user, then collapse them with `git reset --soft "$merge_base"` and create one commit summarising the whole branch, using the message format from step 4.

**Rules:**
- Skip this step on `main`/`master` — there is no feature branch to collapse
- Never reset past the merge-base — commits that belong to the base branch are not yours to rewrite
- If the base branch cannot be determined, skip the squash and say so in the report

### Step 6: Push

Invoking `/ship` is itself the authorization to commit and push — do not ask for a separate confirmation, including on `main`/`master`.

- If branch has upstream: `git push`
- If no upstream: `git push -u origin <current-branch>`
- If step 5 rewrote the history of an already-pushed feature branch: `git push --force-with-lease` — never plain `--force`, and never on `main`/`master`

### Step 7: Report

After successful push, output a brief summary:
- Commit type and scope
- One-line description of what was committed
- Branch name and remote

## Anti-patterns

- **Never** use `git add .` or `git add -A` — always stage files explicitly
- **Never** commit secrets or credentials
- **Never** create empty commits
- **Never** amend or rewrite commits that already exist on the base branch — the step 5 squash touches only commits above the merge-base
- **Never** skip git hooks (`--no-verify`)
- **Never** force push to `main`/`master`, and never plain `--force` anywhere — `--force-with-lease` on a feature branch after a step 5 squash is the only permitted rewrite
- **Do not** update README for internal/cosmetic changes
- **Do not** add Co-Authored-By or other trailers unless the user asks
