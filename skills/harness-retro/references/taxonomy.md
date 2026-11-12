# Harness Retro Taxonomy

Use categories only when there is event-level evidence. Do not infer hidden causes from absent data.

## Misalignment

- `wrong-project-diagnosis`: incorrect understanding of the codebase, project state, or error cause.
- `misread-user-intent`: plausible but wrong interpretation of the user's request.
- `constraint-violation`: violation of an explicit user, project, or system constraint.
- `scope-overreach`: action outside the allowed scope.
- `faulty-implementation`: syntactically, logically, or functionally wrong result.
- `operational-error`: wrong command, path, environment, target, or tool operation.
- `inaccurate-self-reporting`: success claim without support, or against visible evidence.
- `other`: evidence-backed observation outside the current taxonomy.

## Tool Routing And Efficiency

- `repeated-tool-failure`: equivalent operation fails repeatedly.
- `avoidable-retry`: retry caused by a missed precondition check.
- `tool-mismatch`: brittle low-level tool used when a specialized route was available.
- `redundant-read`: same large resource read repeatedly without a visible reason.
- `oversized-tool-output`: large output returned when a filtered/aggregated result was enough.
- `premature-delegation`: subagent receives insufficient context or a task without independence.
- `unused-available-capability`: specialized capability appeared relevant but was not used. In MVP this is low confidence unless availability is recorded in the log.

## Verification

- `missing-verification`: runtime implementation completion declared without relevant verification evidence. Do not emit it for explicitly scoped planning, SDD artifact, documentation, read-only, or git-administration completion, or when the assistant clearly discloses that verification was not performed.
- `wrong-verification-target`: verification ran against the wrong environment, file, branch, project, or scenario.
- `verification-ignored`: verification contradicted the final status.
- `user-discovered-regression`: user immediately found a defect after completion was claimed.

## User-Side Signals

- `underspecified-request`: a critical choice was not supplied and could not be safely inferred.
- `late-constraint`: a material constraint appeared after implementation began.
- `repeated-context-provision`: the same context is repeatedly supplied by the user.
- `effective-prompt-pattern`: a request pattern consistently leads to short successful completion.

These categories are not blame labels. Use them to suggest prompt templates, memory, project context, or process changes.

## Reusable Workflows

- `reusable-workflow-pattern`: an ordered composition of at least three distinct skills recurs across independent sessions and may justify an orchestration skill. Keep two-session evidence as `observed`. Mark it `corroborated` only after at least three sessions across two projects, or five sessions in one project.

This category proposes discovery work, not automatic skill creation. Before proposing a new skill, check whether an existing skill already owns the workflow end to end. Preserve the approval boundaries of every composed skill.

## Destination Rules

Prefer the narrowest destination that matches the evidence:

- stable personal preference: `memory` or personal instruction, after explicit approval;
- project invariant: `agents-md`, `claude-md`, or project docs;
- repeated conditional workflow: `skill`;
- mechanically checkable constraint: `hook` or validation script;
- fragile repeated command sequence: `cli-helper`;
- input formulation problem: `user-workflow` or prompt template;
- single or weak signal: `none`.

Do not recommend a skill merely because the observation is about agent behavior. Recommend a skill only when it captures a repeatable task or decision workflow.
