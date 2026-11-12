# Candidate Lifecycle

Candidates are reviewable hypotheses, not approved changes.

```text
observed -> corroborated -> proposed -> accepted -> applied -> measuring -> confirmed
                                  |          |          |
                                  v          v          v
                              rejected    deferred   rolled-back
```

- `observed`: supported by one session or weak evidence.
- `corroborated`: supported by at least two independent main sessions.
- `proposed`: selected for human review with a concrete change proposal.
- `accepted`: direction accepted, but file mutation is still not authorized.
- `applied`: set only after a separately approved edit.
- `measuring`: post-application observation window is running.
- `confirmed`: effect looks positive after the measurement window.
- `rejected`: human reviewer declined it.
- `deferred`: review postponed until a specific date or condition.
- `rolled-back`: applied change was reverted or superseded.
- `stale`: old unapplied candidate is no longer useful.

Global or cross-harness improvements need at least three independent sessions and at least two projects unless the user explicitly states a universal preference.

For `reusable-workflow-pattern`, two sessions remain `observed`. It becomes `corroborated` after at least three sessions across two projects, or five sessions in one project. `Corroborated` still means “review the gap”; it does not authorize creating the proposed skill.

A single high/critical finding can create an urgent candidate, but it remains a manual review item rather than a universal rule.

Default measurement window: the next 10 relevant sessions or 30 days. Lack of recurrence is positive evidence but not proof of causality.
