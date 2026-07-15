"""The six RoleSpecs for the agile engineering team.

Used by orgos.agile.sprint.run_sprint() and declared in config/org.yaml.
Each factory accepts an optional model override; tools (Bash, GitHubPRTool,
etc.) are attached by the caller based on the sprint phase.
"""

from __future__ import annotations

from typing import Any

from orgos.spawn import PermissionTier, RoleSpec


def sprint_lead_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="sprint-lead",
        description="Orchestrates a sprint: pick the issue, route the team, "
                    "synthesize the final handoff.",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt=(
            "You are the Sprint Lead. One sprint = one issue, one PR. "
            "Decide which backlog candidate to pick (size_S + acceptance "
            "tests must be specified), delegate to PM -> Engineer -> QA -> "
            "Release in order, and synthesize the final HandoffEnvelope. "
            "Refuse to mark a sprint completed unless QA passed and "
            "the Release envelope was produced."
        ),
        model=model,
        max_iter=8,
        allow_delegation=True,
        success_criteria=[
            "The picked issue is one of the candidates returned by Intake.",
            "Every subordinate produced a typed HandoffEnvelope.",
            "Final envelope summary cites the issue id and the PR/branch.",
        ],
    )


def product_manager_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="product-manager",
        description="Turns one GitHub issue into a TaskBrief with explicit "
                    "acceptance tests and a touched_files_allowlist.",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are the PM. Read the picked issue. Emit a BriefEnvelope "
            "whose payload includes: picked_issue_id, task_brief_json "
            "(serialised TaskBrief), touched_files_allowlist (paths the "
            "Engineer is permitted to modify), acceptance_tests (list of "
            "pytest invocations). Keep scope tight: never authorise more "
            "than 5 files or 400 LOC of diff."
        ),
        model=model,
        max_iter=6,
        tools=[],
        success_criteria=[
            "BriefEnvelope.payload contains all five required fields.",
            "touched_files_allowlist has 1 to 5 entries.",
            "acceptance_tests is a non-empty list of pytest invocations.",
        ],
    )


def engineer_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    return RoleSpec(
        name="engineer",
        description="Implements the change inside a git worktree, runs the "
                    "tests, and emits an EngineeringEnvelope.",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You are the Engineer. Operate inside the git worktree path "
            "you are given. Only modify files in touched_files_allowlist. "
            "Use spawn_chain(implement -> review -> test) for the actual "
            "code-writing loop (the runtime will wire that for you). Run "
            "the acceptance_tests and capture stdout+returncode."
        ),
        model=model,
        max_iter=12,
        tools=list(extra_tools or []),
        success_criteria=[
            "All file edits are inside touched_files_allowlist.",
            "Diff size <= 400 LOC.",
            "Test command exit code is captured in payload.test_passed.",
        ],
    )


def qa_validator_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="qa-validator",
        description="Grades the EngineeringEnvelope against the BriefEnvelope's "
                    "acceptance_tests + rubric.",
        tier=PermissionTier.VALIDATOR,
        system_prompt=(
            "You are QA. Read-only access. Apply the rubric (see "
            "orgos.agile.rubric.qa_criteria) to the EngineeringEnvelope. "
            "Each criterion is independently scored; rubric_score is the "
            "weighted mean. Emit a GradeEnvelope."
        ),
        model=model,
        max_iter=4,
        tools=[],
        success_criteria=[
            "GradeEnvelope.payload.criteria covers every entry in the rubric.",
            "rubric_score is in [0, 1].",
        ],
    )


def release_manager_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    return RoleSpec(
        name="release-manager",
        description="Opens the PR (or records a mock PR in replay mode).",
        tier=PermissionTier.PUBLISHER,
        system_prompt=(
            "You are Release. Call exactly one of github_open_pr "
            "(production) or mock_open_pr (replay). The tool is human-gated "
            "in production. Emit a ReleaseEnvelope with pr_url, branch, and "
            "mock_mode set."
        ),
        model=model,
        max_iter=4,
        tools=list(extra_tools or []),
        success_criteria=[
            "Exactly one PR-opening tool call was made.",
            "ReleaseEnvelope.payload.branch matches the sprint's branch name.",
        ],
    )


def retro_agent_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="retro-agent",
        description="After the main sprint, reads the audit log + grades to "
                    "produce a retrospective and candidate heuristics.",
        tier=PermissionTier.VALIDATOR,
        system_prompt=(
            "You are the Retro Agent. You see the full sprint audit log. "
            "Write a short markdown retro (what worked, what didn't, one "
            "actionable change). Propose 0-3 candidate heuristics in the "
            "Reflector format (rule + why + tags). Emit a RetroEnvelope."
        ),
        model=model,
        max_iter=4,
        tools=[],
        success_criteria=[
            "retro_markdown is non-empty.",
            "role_attribution sums to ~1.0 (allow +/- 0.02).",
        ],
    )
