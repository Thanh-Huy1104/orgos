from unittest.mock import MagicMock

from orgos.agile.topology import Proposal, propose_topology_mutations


def _pm_with_attribution(rows_by_role: dict[str, list[float]]) -> MagicMock:
    pm = MagicMock()
    def _list(role, since_days=30):
        return [{"score": s} for s in rows_by_role.get(role, [])]
    pm.list_role_attribution.side_effect = _list
    pm.list_qa_failure_tags = lambda since_sprints=5: []
    pm.list_blocker_tags = lambda since_sprints=5: []
    return pm


def test_low_contribution_three_sprints_proposes_remove(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: release-manager}\n"
    )
    pm = _pm_with_attribution({"release-manager": [0.02, 0.03, 0.04]})
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=3)
    kinds = [p.kind for p in props]
    assert "REMOVE_ROLE" in kinds


def test_qa_cluster_proposes_split(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: engineer}\n"
    )
    pm = _pm_with_attribution({"engineer": [0.5, 0.5, 0.5]})
    pm.list_qa_failure_tags = lambda since_sprints=5: [
        ("no-canary", 4), ("style", 1)
    ]
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=5)
    assert any(p.kind == "SPLIT_ROLE" for p in props)


def test_blocker_without_owner_proposes_add(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members: []\n"
    )
    pm = _pm_with_attribution({})
    pm.list_blocker_tags = lambda since_sprints=5: [("db-migration", 3)]
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=5)
    assert any(p.kind == "ADD_ROLE" and "expire_at" in p.after_yaml for p in props)


def test_high_contribution_produces_no_removes(tmp_path):
    (tmp_path / "org.yaml").write_text(
        "departments:\n  - name: e\n    supervisor: {name: sprint-lead}\n"
        "    members:\n      - {name: engineer}\n"
    )
    pm = _pm_with_attribution({"engineer": [0.4, 0.4, 0.4]})
    props = propose_topology_mutations(pm, tmp_path / "org.yaml", window_sprints=3)
    assert all(p.kind != "REMOVE_ROLE" for p in props)
