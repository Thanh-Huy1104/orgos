from orgos.agile.dora_bridge import dora_to_heuristic_candidates


def test_high_cfr_emits_canary_heuristic():
    snap = {"deploy_freq": 1.0, "lead_time_p50": 1000.0, "cfr": 0.3,
            "mttr_p50": 1000.0, "tier": "Medium"}
    h = dora_to_heuristic_candidates(None, snap, prior=[
        {"cfr": 0.25}, {"cfr": 0.27}, {"cfr": 0.30}
    ])
    rules = [x.rule for x in h]
    assert any("canary" in r.lower() for r in rules)


def test_slow_lead_time_emits_split_heuristic():
    snap = {"deploy_freq": 0.1, "lead_time_p50": 10 * 86400.0, "cfr": 0.0,
            "mttr_p50": 100.0, "tier": "Low"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("split" in x.rule.lower() for x in h)


def test_low_deploy_freq_emits_commit_heuristic():
    snap = {"deploy_freq": 0.02, "lead_time_p50": 1000.0, "cfr": 0.0,
            "mttr_p50": 100.0, "tier": "Low"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("commit" in x.rule.lower() for x in h)


def test_high_mttr_emits_hotfix_heuristic():
    snap = {"deploy_freq": 1.0, "lead_time_p50": 1000.0, "cfr": 0.0,
            "mttr_p50": 10 * 3600.0, "tier": "Medium"}
    h = dora_to_heuristic_candidates(None, snap)
    assert any("hotfix" in x.rule.lower() for x in h)
