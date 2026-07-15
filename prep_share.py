#!/usr/bin/env python
"""Clean up local artifacts before sharing the repo.

Removes sensitive files (API keys, tokens), runtime artifacts
(sprints, audit logs, memory DB), and temporary experiment data.
Does NOT touch code, tests, persona files, wiki, or docs.

Usage:
    python3 prep_share.py          # clean only
    python3 prep_share.py --dry    # show what WOULD be cleaned
"""

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent

# These directories/files get REMOVED
PURGE_DIRS = [
    "_audit_logs",
    "_orgos_memory",
    ".sprints",
    "__pycache__",
    ".pytest_cache",
    "orgos/__pycache__",
    "orgos/agile/__pycache__",
    "orgos/spawn/__pycache__",
    "orgos/mcps/__pycache__",
    "orgos/subagents/__pycache__",
    "orgos/tools/__pycache__",
    "tests/__pycache__",
    "tests/agile/__pycache__",
    "tests/spawn/__pycache__",
    "tests/mcps/__pycache__",
    "monitor/__pycache__",
    "monitor/lib/__pycache__",
    "monitor/pages/__pycache__",
]

PURGE_FILES_GLOB = [
    "experiment_*.json",
    "*.pyc",
    "**/*.pyc",
]

# These files get data SCRUBBED (replace sensitive values but keep the file)
SCRUB_FILES = {
    ".env": None,  # Remove entirely
    ".env.example": None,  # Keep, it's a template
}


def clean(dry_run: bool = False):
    removed = 0

    # Purge directories
    for d in PURGE_DIRS:
        path = REPO / d
        if path.exists():
            if dry_run:
                print(f"  [would remove] {d}/")
            else:
                shutil.rmtree(path, ignore_errors=True)
                print(f"  [removed] {d}/")
            removed += 1

    # Purge files by glob
    for g in PURGE_FILES_GLOB:
        for f in REPO.glob(g):
            if dry_run:
                print(f"  [would remove] {f.relative_to(REPO)}")
            else:
                f.unlink(missing_ok=True)
                print(f"  [removed] {f.relative_to(REPO)}")
            removed += 1

    # Scrub .env
    env_file = REPO / ".env"
    if env_file.exists():
        if dry_run:
            print(f"  [would scrub] .env (API keys)")
        else:
            # Replace with template
            env_file.write_text(
                "# Fill in your API keys (see .env.example for reference)\n"
                "DEEPSEEK_API_KEY=sk-...\n"
                "GITHUB_TOKEN=ghp_...\n"
                "GITHUB_REPO=owner/repo\n"
            )
            print(f"  [scrubbed] .env -> placeholder")
        removed += 1

    print(f"\n{'Would clean' if dry_run else 'Cleaned'} {removed} items.")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — nothing will be changed:\n")
    else:
        print("Cleaning repo for sharing:\n")
    clean(dry_run=dry)
    if not dry:
        print("\nRepo is clean. Copy it to the target machine, then:")
        print("  1. Create .env from .env.example with your API keys")
        print("  2. pip install -r requirements.txt")
        print("  3. cd monitor && pip install -r requirements.txt")
        print("  4. python3 run_monitor.py")
