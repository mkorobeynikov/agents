# Common rules

- Do not preserve backward compatibility for new projects.
- Choose the simplest implementation that fully meets the current requirements.
- Prefer established, well-maintained libraries over custom implementations.
- Fix the root cause, not the symptom.
- Recommend best practices, even when they may require refactoring.
- Never hallucinate or fabricate information. If you are unsure about anything, explicitly state your uncertainty. Say "I don't know" rather than guessing or making assumptions. Honesty about limitations is required.
- Never commit or push changes unless explicitly asked to do so.
- Never add `Co-Authored-By: Claude ...` or any Claude/AI co-author trailer to commit messages or pull request bodies.

## Comment policy

### Unacceptable comments

- Comments that repeat what code does.
- Commented-out code; delete it instead.
- Obvious comments, such as "increment counter".
- Comments used instead of good naming.

### Principle

Code should be self-documenting. If a comment is needed to explain what the code does, consider refactoring to make it clearer.
