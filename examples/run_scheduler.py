"""Run the org on a production calendar.

Loads the org constitution, attaches tools, and runs the scheduler.
Use --once for a single pending-jobs pass; default is continuous loop.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/run_scheduler.py              # continuous loop (Ctrl+C to stop)
    python examples/run_scheduler.py --once       # run pending jobs once and exit
"""

import sys

from examples.quant_pair_scanner import test_cointegration
from orgos import Scheduler, cli_approval, load_org


def main():
    org = load_org("examples/org.yaml")
    print(f"Loaded: {org.name} — {len(org.departments)} departments")
    for d in org.departments:
        sched = [s.name for s in d.sops if s.cadence]
        print(f"  {d.name}: {len(d.all_roles())} roles, {len(sched)} scheduled")

    # Attach Python tools (can't live in YAML)
    finance = org.find_department("finance")
    if finance:
        finance.members[0] = finance.members[0].model_copy(
            update={"tools": [test_cointegration]}
        )

    scheduler = Scheduler(org)
    scheduler.set_approval(cli_approval)

    jobs = scheduler.jobs()
    print(f"\nScheduled jobs: {len(jobs)}")
    for j in jobs:
        print(f"  {j.department.name}/{j.sop_name} — {j.cadence}")

    if "--once" in sys.argv:
        print("\nRunning pending jobs once...")
        results = scheduler.run_pending()
        print(f"\nDone. {len(results)} jobs executed.")
        for r in results:
            print(f"  {r['department']}/{r['sop']}: {r['status']} ({r['tokens']:,} tokens)")
    else:
        print("\nStarting continuous scheduler (Ctrl+C to stop)...")
        scheduler.run_loop(interval_sec=30)  # check every 30s


if __name__ == "__main__":
    main()
