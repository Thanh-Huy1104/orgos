"""apply_proposal must not destroy the hand-curated org.yaml constitution:
comments and layout survive, and a snapshot is taken before every write."""

from pathlib import Path

from orgos.evolve import Proposal, ProposalType, apply_proposal

_ORG_YAML = """\
# orgos org constitution — KEEP THIS COMMENT.
org:
  name: TestOrg
  default_model: gpt-4o-mini  # inline rationale comment
departments:
  # research department comment
  - name: research
    supervisor:
      name: lead
      tier: orchestrator
      system_prompt: Lead.
    members:
      - name: analyst
        tier: worker
        system_prompt: Analyse.
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "org.yaml"
    p.write_text(_ORG_YAML)
    return p


def test_comments_survive_apply(tmp_path):
    path = _write(tmp_path)
    prop = Proposal.make(
        ProposalType.ADD_ROLE, "research",
        "Add a reviewer", "needs review",
        changes={"role": {"name": "reviewer", "tier": "validator",
                          "system_prompt": "Review."}},
    )
    res = apply_proposal(prop, path)
    assert res["applied"] is True
    text = path.read_text()
    # comments preserved
    assert "# orgos org constitution — KEEP THIS COMMENT." in text
    assert "# inline rationale comment" in text
    assert "# research department comment" in text
    # the change actually landed
    assert "reviewer" in text


def test_backup_written_before_change(tmp_path):
    path = _write(tmp_path)
    prop = Proposal.make(
        ProposalType.NEEDS_TOOLS, "research", "needs a tool", "reason",
        tools=["WebFetch"],
    )
    apply_proposal(prop, path)
    backups = list((tmp_path / ".org-backups").glob("org.yaml.*"))
    assert len(backups) == 1
    # the snapshot is the pre-change file, comments and all
    assert "# orgos org constitution — KEEP THIS COMMENT." in backups[0].read_text()
    assert "pending_tool_requests" not in backups[0].read_text()  # snapshot is the OLD state
