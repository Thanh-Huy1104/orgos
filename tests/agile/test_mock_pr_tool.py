from orgos.tools.mock_pr_tool import MockPRTool


def test_mock_pr_tool_category_is_read():
    t = MockPRTool()
    assert t.tool_category == "read"


def test_mock_pr_tool_returns_deterministic_url():
    t = MockPRTool()
    a = t._run(branch="agile/abc", title="t", body="b")
    b = t._run(branch="agile/abc", title="t", body="b")
    assert a == b
    assert a.startswith("mock://pr/")


def test_mock_pr_tool_distinct_inputs_distinct_url():
    t = MockPRTool()
    a = t._run(branch="agile/abc", title="x", body="b")
    b = t._run(branch="agile/abc", title="y", body="b")
    assert a != b
