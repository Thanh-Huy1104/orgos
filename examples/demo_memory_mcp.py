"""Demo: agents with memory — they remember past runs via MCP tools.

1. Runs a first scan (populates memory).
2. Wires the memory MCP into the department.
3. Runs a second scan — the agent queries memory to see what was done before.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/demo_memory_mcp.py
"""

from pathlib import Path

from examples.quant_pair_scanner import test_cointegration
from orgos import (
    Department,
    Org,
    RoleSpec,
    TaskBrief,
    PermissionTier,
    create_memory_mcp,
    run_department,
    spawn_department,
)

DB_PATH = "./_orgos_memory/demo.db"


def main():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    scanner = RoleSpec(
        name="scanner",
        tier=PermissionTier.WORKER,
        system_prompt=(
            "You scan assets for cointegration. Before scanning, use the "
            "recall_past_runs tool to check what was already tested so you "
            "don't duplicate work. After scanning, use get_department_status "
            "to report the department's token usage."
        ),
        tools=[test_cointegration],
        model="gpt-4o-mini",
        max_iter=10,
    )

    supervisor = RoleSpec(
        name="supervisor",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt=(
            "Delegate to scanner. After the scan, use get_department_status "
            "to check the department's activity and include it in your summary."
        ),
        model="gpt-4o-mini",
        max_iter=8,
    )

    dept = Department(
        name="research",
        description="Research department with memory.",
        supervisor=supervisor,
        members=[scanner],
    )

    # Phase 1: first scan without memory MCP
    print("=" * 60)
    print("PHASE 1: First scan (no memory tools yet)")

    org = Org(name="DemoOrg", departments=[dept])
    org.use_memory(DB_PATH)

    r1 = spawn_department(dept, TaskBrief(objective="Scan SPY and QQQ for cointegration."), verbose=False)
    print(f"  status={r1.envelope.status} tokens={r1.token_usage['total_tokens']}")

    # Phase 2: wire memory MCP and run again
    mcp = create_memory_mcp(DB_PATH)
    dept.shared_mcps = [mcp]

    print("\nPHASE 2: Second scan (with memory tools)")
    r2 = run_department(
        org, "research",
        TaskBrief(
            objective=(
                "Check what was scanned before using recall_past_runs. "
                "Then scan QQQ and IWM for cointegration. "
                "Finally, use get_department_status to report activity."
            )
        ),
        verbose=False,
    )
    print(f"  status={r2.envelope.status} tokens={r2.token_usage['total_tokens']}")
    print(f"  summary: {r2.envelope.summary[:300]}")

    print("\nDone. Memory db at:", DB_PATH)


if __name__ == "__main__":
    main()
