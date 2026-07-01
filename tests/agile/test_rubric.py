import json

from orgos.agile.envelopes import BriefEnvelope, EngineeringEnvelope
from orgos.agile.rubric import grade, qa_criteria


def _brief(allow=("src.py",), tests=("pytest test_src.py",)):
    return BriefEnvelope(
        role="pm", status="completed", summary="brief",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "picked_issue_id": "42", "task_brief_json": "{}",
            "touched_files_allowlist": list(allow),
            "acceptance_tests": list(tests),
        }),
    )


def _eng(files=("src.py",), passed=True, diff_lines=10):
    return EngineeringEnvelope(
        role="engineer", status="completed", summary="impl",
        success_criteria_met=True, requires_human_approval=False,
        payload=json.dumps({
            "diff": "\n".join("+x" for _ in range(diff_lines)),
            "commit_sha": "abcdefg", "files_touched": list(files),
            "test_command": "pytest test_src.py",
            "test_output": "1 passed", "test_passed": passed,
        }),
    )


def test_rubric_has_five_criteria():
    assert len(qa_criteria()) == 5


def test_clean_run_full_score():
    g = grade(_brief(), _eng())
    p = g.parsed_payload()
    assert p["rubric_score"] == 1.0
    assert all(c["passed"] for c in p["criteria"])


def test_test_failure_fails_grade():
    g = grade(_brief(), _eng(passed=False))
    p = g.parsed_payload()
    assert p["rubric_score"] < 1.0
    assert any(c["name"] == "tests_pass" and not c["passed"] for c in p["criteria"])


def test_out_of_allowlist_file_fails_grade():
    g = grade(_brief(allow=("src.py",)), _eng(files=("src.py", "other.py")))
    p = g.parsed_payload()
    assert any(c["name"] == "files_in_allowlist" and not c["passed"] for c in p["criteria"])


def test_diff_too_large_fails_grade():
    g = grade(_brief(), _eng(diff_lines=500))
    p = g.parsed_payload()
    assert any(c["name"] == "diff_size_ok" and not c["passed"] for c in p["criteria"])
