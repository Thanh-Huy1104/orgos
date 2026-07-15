"""Quality evaluator — combines deterministic checks with LLM scoring.

Spawns a lightweight LLM agent to grade AC compliance, code quality,
and test relevance. Combined with deterministic criteria from
quality_rubric.py to produce a QualityReport.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orgos.spawn import TaskBrief, spawn
from orgos.spawn.contracts import PermissionTier, RoleSpec


@dataclass
class QualityReport:
    sprint_id: str
    overall: float
    deterministic_score: float
    deterministic_criteria: dict
    llm_score: float
    llm_scores: dict
    llm_summary: str
    errors: list[str] = field(default_factory=list)


def _read_diff(worktree: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD~1"],
        cwd=worktree, capture_output=True, text=True,
    )
    diff = result.stdout or ""
    if not diff.strip():
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=worktree, capture_output=True, text=True,
        )
        diff = result.stdout or ""
    return diff[:8000]


def _evaluator_role(model: str | None = None) -> RoleSpec:
    return RoleSpec(
        name="quality-evaluator",
        description="Reads git diffs and acceptance criteria, scores code quality on a 1-5 scale.",
        tier=PermissionTier.VALIDATOR,
        system_prompt=(
            "You are a code quality evaluator. You receive a git diff and "
            "acceptance criteria. Score the change on three axes (1-5 scale):\n"
            "1. AC compliance — does every acceptance criterion have evidence in the diff?\n"
            "2. Code quality — is this the minimal change? does it follow conventions?\n"
            "3. Test relevance — do tests actually verify the criteria?\n\n"
            "Output ONLY a JSON object:\n"
            '{"ac_compliance": 4, "code_quality": 5, "test_relevance": 3, '
            '"summary": "Brief explanation of scores."}\n'
            "NO markdown. NO prose. ONLY the JSON."
        ),
        model=model,
        max_iter=4,
        success_criteria=["Produces valid JSON with three numeric scores."],
    )


class QualityEvaluator:
    def __init__(self, model: str | None = None):
        self.model = model

    def evaluate(
        self, sprint, issue: dict,
        allowlist: list[str] | None = None,
    ) -> QualityReport:
        from orgos.agile.quality_rubric import evaluate as det_eval

        errors: list[str] = []
        worktree = getattr(sprint, "worktree_path", None)
        if not worktree or not Path(str(worktree)).exists():
            return QualityReport(
                sprint_id=getattr(sprint, "id", "?"), overall=0.0,
                deterministic_score=0.0, deterministic_criteria={},
                llm_score=0.0, llm_scores={}, llm_summary="",
                errors=["worktree not found"],
            )

        wt = Path(str(worktree))
        test_output = ""
        eng = sprint.envelopes.get("engineering", {})
        if isinstance(eng, dict):
            test_output = str(eng.get("test_output", ""))

        det_result = det_eval(wt, allowlist=allowlist, test_output=test_output)

        diff = _read_diff(wt)
        ac_text = issue.get("body", issue.get("title", ""))
        llm_score, llm_scores, llm_summary = self._llm_evaluate(diff, ac_text)

        overall = round(
            det_result["score"] * 0.40 + llm_score * 0.60, 3
        )

        return QualityReport(
            sprint_id=getattr(sprint, "id", "?"),
            overall=overall,
            deterministic_score=det_result["score"],
            deterministic_criteria=det_result["criteria"],
            llm_score=llm_score,
            llm_scores=llm_scores,
            llm_summary=llm_summary,
            errors=errors,
        )

    def _llm_evaluate(self, diff: str, acceptance_criteria: str) -> tuple[float, dict, str]:
        if not diff.strip():
            return 0.0, {}, "no diff to evaluate"

        role = _evaluator_role(self.model)
        brief = TaskBrief(
            objective=(
                f"Evaluate this code change for quality.\n\n"
                f"ACCEPTANCE CRITERIA:\n{acceptance_criteria[:2000]}\n\n"
                f"GIT DIFF:\n{diff[:6000]}\n\n"
                f"Score each axis 1-5. Output ONLY the JSON."
            ),
            expected_output="JSON object with ac_compliance, code_quality, test_relevance, summary.",
            success_criteria=["Valid JSON with three numeric scores."],
        )

        try:
            result = spawn(role, brief, run_budget_tokens=50_000)
            raw = getattr(result, "raw_output", "") or ""
            if not raw:
                return 3.0, {}, "no LLM output, assuming average"
            blob = _extract_json(raw)
            if blob:
                data = json.loads(blob)
                scores = {
                    k: min(5, max(1, int(v)))
                    for k, v in data.items()
                    if k in ("ac_compliance", "code_quality", "test_relevance")
                }
                avg = sum(scores.values()) / max(len(scores), 1) / 5.0
                return round(avg, 3), scores, data.get("summary", "")
        except Exception as e:
            pass
        return 3.0, {}, "evaluation failed, assuming average"


def _extract_json(text: str) -> str | None:
    import re
    m = re.search(r'\{[^{}]*"ac_compliance"[^{}]*\}', text, re.DOTALL)
    if not m:
        m = re.search(r'\{.*?\}', text, re.DOTALL)
    return m.group(0) if m else None
