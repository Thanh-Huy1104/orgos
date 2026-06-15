"""Example: running a department defined in the org constitution.

Loads the org from examples/org.yaml, adds the cointegration tool to the
finance department, and runs it via spawn_department().

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/run_department.py               # daily_scan SOP
    python examples/run_department.py --brief "..."  # custom brief
"""

import sys

from examples.quant_pair_scanner import test_cointegration
from orgos import (
    Department,
    TaskBrief,
    cli_approval,
    load_org,
    spawn_department,
)


def main():
    org = load_org("examples/org.yaml")
    print(f"Loaded: {org.name} — {len(org.departments)} departments")
    for d in org.departments:
        print(f"  {d.name}: {len(d.all_roles())} roles, {len(d.sops)} SOPs")

    finance = org.find_department("finance")
    if finance is None:
        print("ERROR: finance department not found")
        return 1

    # Add the cointegration tool (Python object — can't live in YAML)
    scanner = finance.members[0]
    finance.members[0] = scanner.model_copy(
        update={"tools": [test_cointegration]}
    )

    # Pick a brief: SOP or custom
    custom = " ".join(sys.argv[1:])
    if custom:
        brief = TaskBrief(objective=custom)
        print(f"\nRunning custom brief: {brief.objective}")
    else:
        sop = finance.find_sop("daily_pair_scan")
        if sop is None:
            print("ERROR: daily_pair_scan SOP not found")
            return 1
        brief = sop.brief
        print(f"\nRunning SOP: {sop.name} (cadence={sop.cadence})")

    result = spawn_department(finance, brief, approval_fn=cli_approval)

    env = result.envelope
    print(f"\n{'='*60}")
    print(f"status={env.status}  criteria_met={env.success_criteria_met}")
    print(f"run_id={result.run_id}")
    if result.token_usage:
        print(f"tokens={result.token_usage}")
    print(f"\nsummary:\n{env.summary}")
    print(f"{'='*60}")

    return 0 if env.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
