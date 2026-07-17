"""MockExecutor — zero-LLM-cost coding executor for infrastructure tests.

Writes a placeholder file per story to the worktree, commits it, returns
success. Meant for validating the merge queue / sprint boundaries / DoD
gate / N>1 parallelism at machine speed instead of waiting for an LLM.

Not for real code delivery — the "code" it writes is a comment-only stub.
Use it when you want to test *orgos infrastructure* without paying $
or waiting hours.

Usage:  orgos start ... --executor mock

Typical smoke: with mock, a 12-story goal completes in ~30 seconds.
"""

from __future__ import annotations

import subprocess as _sp
import time
from pathlib import Path
from typing import Any, Callable, Optional

from orgos.agile.coding_executor import ExecutionResult


def seed_mock_backlog(board: Any, n_stories: int = 15) -> list[str]:
    """Populate the board with N synthetic stories for infrastructure smoke.

    Structured to exercise team-scale parallelism realistically:
      - 5 disjoint components (`auth`, `notes`, `folders`, `tags`, `search`).
      - Each component has architecture → feature → test progression, so
        depends_on gating fires and DoD wiki-write fires.
      - Files are strictly disjoint per component (`{comp}/mod.py`,
        `tests/test_{comp}.py`) so N>1 agents can pull in parallel
        without stepping on each other.
      - Every story marked type + component; test stories `depends_on`
        their parent feature.
    """
    components = ["auth", "notes", "folders", "tags", "search"]
    created: list[str] = []
    # Round-robin through components so 3 architects each get an
    # available parallel component on the first tick.
    for i in range(n_stories):
        comp = components[i % len(components)]
        cycle_pos = (i // len(components)) % 3
        # First round per component: architecture. Second: feature. Third: test.
        ttype = ["architecture", "feature", "test"][cycle_pos]
        # Test story depends on the previous story in the same component
        parent_idx = None
        if ttype == "test":
            for j in range(i - 1, -1, -1):
                prev = board.read(created[j])
                if prev.component == comp and prev.type in ("architecture", "feature"):
                    parent_idx = j
                    break
        title = f"[{comp}] {ttype} shim {i:02d}"
        # Files strictly under this component's directory (disjoint by design)
        if ttype == "test":
            files = [f"tests/test_{comp}.py"]
        else:
            files = [f"{comp}/mod.py"]
        s = board.draft_story(
            issue_id=f"MK-{i:02d}",
            title=title,
            body=f"Mock body for {ttype} story {i} in component {comp}.",
            story_type=ttype,
            priority=90 - (i * 3),
            files_to_touch=files,
            component=comp,
        )
        if parent_idx is not None:
            s.depends_on = [created[parent_idx]]
            board._write_story(s)
        board.transition(s.issue_id, "refinement", actor="po")
        board.transition(s.issue_id, "ready", actor="sm")
        board.set_points(s.issue_id, [1, 2, 3, 5][i % 4], actor="sm")
        created.append(s.issue_id)
    return created


class MockExecutor:
    """Zero-LLM-cost executor. Writes one file per story, commits it.

    - Success rate: configurable via `fail_every_n` (default: never fail)
    - Per-story wall: `wall_seconds` (default: 0.1s to simulate real work)
    - Optional token counts for downstream cost-modeling parity
    """

    def __init__(
        self,
        *,
        wall_seconds: float = 0.1,
        fail_every_n: int = 0,       # 0 = never fail; N = every Nth pull fails
        tokens_input: int = 1000,     # fake, for token accounting
        tokens_output: int = 100,
        baseline_sha_provider: Optional[Callable[[], str]] = None,
    ):
        self.wall_seconds = wall_seconds
        self.fail_every_n = fail_every_n
        self._call_count = 0
        self.tokens_input = tokens_input
        self.tokens_output = tokens_output
        self._baseline_sha_provider = baseline_sha_provider

    def _baseline_sha(self, worktree: Path) -> str:
        if self._baseline_sha_provider is not None:
            return self._baseline_sha_provider()
        r = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()

    def run_story(
        self, *,
        worktree: Path,
        story: Any,
        persona_scaffold: str,
        session_id: str,
    ) -> ExecutionResult:
        self._call_count += 1
        t0 = time.time()

        # Simulated failure — used to exercise retry-on-no-commit path
        if self.fail_every_n > 0 and (self._call_count % self.fail_every_n) == 0:
            time.sleep(self.wall_seconds)
            return ExecutionResult(
                success=False,
                error="mock: intentional failure (fail_every_n)",
                wall_seconds=round(time.time() - t0, 3),
                tokens_input=self.tokens_input,
                tokens_output=self.tokens_output,
            )

        # "Do work": write a stub file named after the story, commit it.
        baseline = self._baseline_sha(worktree)
        issue_id = getattr(story, "issue_id", f"mock-{self._call_count}")
        story_type = getattr(story, "type", "feature")
        title = getattr(story, "title", "mock story")

        # File path is derived from the session_id (role) so multiple agents
        # don't step on each other. This models a well-decomposed goal where
        # each agent works on disjoint files.
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in issue_id)
        stub_path = worktree / "mock" / session_id / f"{safe_id}.py"
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_content = (
            f"# Mock stub for story {issue_id}\n"
            f"# type: {story_type}\n"
            f"# title: {title}\n"
            f"# generated by MockExecutor session_id={session_id}\n"
            f'"""Auto-generated placeholder."""\n'
        )
        stub_path.write_text(stub_content, encoding="utf-8")

        # For architecture stories, also write to wiki/DECISIONS.md so the
        # DoD gate accepts it (same three-field format as SpawnCodingExecutor).
        if story_type == "architecture":
            decisions_path = worktree / "wiki" / "DECISIONS.md"
            decisions_path.parent.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            entry = (
                f"\n## {title}\n"
                f"author: mock-executor\n"
                f"timestamp: {ts}\n"
                f"source: {issue_id}\n\n"
                f"Auto-recorded by MockExecutor.\n"
            )
            with decisions_path.open("a", encoding="utf-8") as f:
                f.write(entry)

        # Simulate work time
        time.sleep(self.wall_seconds)

        # Commit
        try:
            _sp.run(
                ["git", "add", "-A"], cwd=str(worktree),
                check=True, capture_output=True, timeout=10,
            )
            r = _sp.run(
                ["git", "-c", "user.name=mock-executor",
                 "-c", "user.email=mock@orgos.local",
                 "commit", "-m", f"{story_type}: {title[:60]} [mock]"],
                cwd=str(worktree), capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                return ExecutionResult(
                    success=False,
                    error=f"mock: git commit failed: {r.stderr[:200]}",
                    wall_seconds=round(time.time() - t0, 3),
                )
        except (_sp.SubprocessError, OSError) as e:
            return ExecutionResult(
                success=False,
                error=f"mock: subprocess error: {e}",
                wall_seconds=round(time.time() - t0, 3),
            )

        head = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree),
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        if head == baseline:
            return ExecutionResult(
                success=False,
                error="mock: HEAD unchanged (empty commit?)",
                wall_seconds=round(time.time() - t0, 3),
            )

        r = _sp.run(
            ["git", "diff", f"{baseline}..HEAD", "--name-only"],
            cwd=str(worktree), capture_output=True, text=True, timeout=10,
        )
        files = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]

        return ExecutionResult(
            success=True,
            commit_sha=head,
            files_touched=files,
            learnings=f"mock committed {issue_id}",
            tokens_input=self.tokens_input,
            tokens_output=self.tokens_output,
            wall_seconds=round(time.time() - t0, 3),
        )

    def spawn_subagent(
        self, *,
        worktree: Path,
        parent_session_id: str,
        prompt: str,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        """No-op subagent — returns immediate success. Used in tests only."""
        return ExecutionResult(
            success=True,
            learnings=f"mock subagent: {prompt[:100]}",
            wall_seconds=0.0,
        )
