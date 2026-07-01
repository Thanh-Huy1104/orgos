"""Audit-callback depth cap: third nested spawn aborts."""

import pytest

from orgos.spawn.audit import (
    DelegationDepthExceeded, _depth_registry, make_audit_callback,
)


def test_depth_registry_increments_on_new_role(monkeypatch):
    _depth_registry.clear()
    cb1 = make_audit_callback("lead", "run-1", max_depth=2)
    cb2 = make_audit_callback("engineer", "run-1", max_depth=2)
    assert _depth_registry["run-1"]["lead"] == 1
    assert _depth_registry["run-1"]["engineer"] == 2


def test_third_nested_role_raises():
    _depth_registry.clear()
    make_audit_callback("lead", "run-2", max_depth=2)
    make_audit_callback("worker_a", "run-2", max_depth=2)
    with pytest.raises(DelegationDepthExceeded):
        make_audit_callback("worker_b", "run-2", max_depth=2)


def test_independent_runs_have_independent_depth():
    _depth_registry.clear()
    make_audit_callback("lead", "r1", max_depth=2)
    make_audit_callback("worker", "r1", max_depth=2)
    make_audit_callback("lead", "r2", max_depth=2)  # different run
    assert _depth_registry["r1"]["lead"] == 1
    assert _depth_registry["r2"]["lead"] == 1
