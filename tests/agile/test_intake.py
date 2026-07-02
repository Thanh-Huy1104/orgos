from orgos.agile.intake import rank_backlog


def _iss(n, labels=("agent-eligible",), body="short body"):
    return {
        "issue_id": str(n), "number": n,
        "title": f"issue {n}", "body": body,
        "labels": list(labels), "url": f"https://x/{n}",
    }


def test_rank_filters_by_allowed_labels():
    out = rank_backlog([
        _iss(1, labels=["agent-eligible"]),
        _iss(2, labels=["wontfix"]),
    ])
    assert [c["issue_id"] for c in out] == ["1"]


def test_rank_prefers_small_first():
    short = _iss(1, body="x")
    long = _iss(2, body="x" * 5000)
    out = rank_backlog([long, short])
    assert out[0]["issue_id"] == "1"
    assert out[0]["size_estimate"] == "S"


def test_rank_marks_security_high_risk():
    out = rank_backlog([_iss(1, labels=("agent-eligible", "security"))])
    assert out[0]["risk_estimate"] == "high"


def test_rank_truncates_to_max():
    issues = [_iss(i) for i in range(20)]
    out = rank_backlog(issues, max_candidates=5)
    assert len(out) == 5


def test_rank_attaches_reason():
    out = rank_backlog([_iss(1)])
    assert out[0]["rank_reason"]
