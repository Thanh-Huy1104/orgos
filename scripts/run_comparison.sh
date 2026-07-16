#!/usr/bin/env bash
# scripts/run_comparison.sh — waterfall vs scrum comparison on the same goal.
#
# Runs both topologies against a target repo, collects per-topology metrics,
# prints a side-by-side summary. Safe to re-run — deletes previous team
# workspaces first.
#
# Usage:
#   scripts/run_comparison.sh \
#     --repo /tmp/flask-target \
#     --goal "Add /notes-count GET endpoint returning {count: N}" \
#     [--model deepseek/deepseek-chat] \
#     [--executor auto|claude|copilot|spawn] \
#     [--scrum-seconds 360]
#
# Requires: `orgos` on PATH, `python3`, `git`, plus whichever executor's
# prerequisites (claude / copilot / API key).

set -euo pipefail

REPO=""
GOAL=""
MODEL="deepseek/deepseek-chat"
EXECUTOR="auto"
SCRUM_SECONDS=360
WATERFALL_TEAM="cmp-waterfall"
SCRUM_TEAM="cmp-scrum"

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)          REPO="$2"; shift 2 ;;
        --goal)          GOAL="$2"; shift 2 ;;
        --model)         MODEL="$2"; shift 2 ;;
        --executor)      EXECUTOR="$2"; shift 2 ;;
        --scrum-seconds) SCRUM_SECONDS="$2"; shift 2 ;;
        -h|--help)       sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1"; exit 2 ;;
    esac
done

if [ -z "$REPO" ] || [ -z "$GOAL" ]; then
    echo "ERROR: --repo and --goal are required. Use --help." >&2
    exit 2
fi
REPO="$(cd "$REPO" && pwd)"
if [ ! -d "$REPO/.git" ]; then
    echo "ERROR: $REPO is not a git repo." >&2
    exit 2
fi

echo "==> Comparison config"
echo "    repo:          $REPO"
echo "    goal:          $GOAL"
echo "    model:         $MODEL"
echo "    executor:      $EXECUTOR"
echo "    scrum window:  ${SCRUM_SECONDS}s"

# ── clean previous runs ────────────────────────────────────────────────────
echo "==> Cleaning previous team workspaces + branches"
for team in "$WATERFALL_TEAM" "$SCRUM_TEAM"; do
    rm -rf "$REPO/.orgos_teams/$team" 2>/dev/null || true
    (
        cd "$REPO"
        for wt in $(git worktree list --porcelain | awk '/^worktree /{print $2}' | grep "$team" || true); do
            git worktree remove --force "$wt" 2>/dev/null || true
        done
        git worktree prune
        for br in $(git branch --list "team/$team*" | tr -d ' *'); do
            git branch -D "$br" 2>/dev/null || true
        done
    )
done

# ── 1. WATERFALL run ──────────────────────────────────────────────────────
echo ""
echo "==> [1/2] Running WATERFALL topology..."
W_START=$(date +%s)
if orgos run \
    --repo "$REPO" --team-id "$WATERFALL_TEAM" --goal "$GOAL" \
    --waterfall --model "$MODEL" \
    > "/tmp/orgos-cmp-waterfall.log" 2>&1; then
    W_EXIT=0
else
    W_EXIT=$?
fi
W_END=$(date +%s)
echo "    waterfall exit=$W_EXIT wall=$((W_END - W_START))s (log: /tmp/orgos-cmp-waterfall.log)"

# ── 2. SCRUM run ───────────────────────────────────────────────────────────
echo ""
echo "==> [2/2] Running SCRUM topology (${SCRUM_SECONDS}s window)..."
S_START=$(date +%s)
if orgos start \
    --repo "$REPO" --team-id "$SCRUM_TEAM" --goal "$GOAL" \
    --executor "$EXECUTOR" --model "$MODEL" \
    --timeout-seconds "$SCRUM_SECONDS" \
    > "/tmp/orgos-cmp-scrum.log" 2>&1; then
    S_EXIT=0
else
    S_EXIT=$?
fi
S_END=$(date +%s)
echo "    scrum exit=$S_EXIT wall=$((S_END - S_START))s (log: /tmp/orgos-cmp-scrum.log)"

# ── 3. Metrics ─────────────────────────────────────────────────────────────
echo ""
echo "==> Collecting metrics"
python3 - "$REPO" "$WATERFALL_TEAM" "$SCRUM_TEAM" <<'PY'
import json, sys, subprocess, pathlib
from collections import Counter

repo = pathlib.Path(sys.argv[1])
teams = sys.argv[2], sys.argv[3]

def load_json(p):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.exists() else None

def story_states(root):
    d = pathlib.Path(root) / "board" / "stories"
    if not d.exists(): return Counter()
    return Counter(json.loads(f.read_text()).get("state", "?") for f in d.glob("*.json"))

def event_counts(root):
    p = pathlib.Path(root) / "live.jsonl"
    if not p.exists(): return Counter()
    return Counter(
        json.loads(l).get("action", "?")
        for l in p.read_text().splitlines() if l.strip()
    )

def run_tests(worktree):
    if not pathlib.Path(worktree).exists():
        return None, "(no worktree)"
    r = subprocess.run(
        ["pytest", "-q", "--no-header"],
        cwd=str(worktree), capture_output=True, text=True, timeout=120,
    )
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode, tail

rows = []
for team in teams:
    root = repo / ".orgos_teams" / team
    if not root.exists():
        rows.append({"team": team, "workspace": "MISSING"})
        continue

    campaign = load_json(root / "campaign_result.json") or {}
    states = story_states(root)
    events = event_counts(root)

    stories_created = campaign.get("stories_created") or sum(states.values())
    stories_done    = campaign.get("stories_done")    or states.get("done", 0)
    stories_blocked = campaign.get("stories_blocked") or states.get("blocked", 0)
    tokens_in       = campaign.get("total_tokens_input", "?")
    tokens_out      = campaign.get("total_tokens_output", "?")

    if campaign.get("started_at") and campaign.get("ended_at"):
        wall = f"{campaign['started_at']} → {campaign['ended_at']}"
    else:
        wall = "(scrum: see log)"

    integ = root / ("worktree" if (root / "worktree").exists() else "integration")
    rc, tail = run_tests(integ)

    rows.append({
        "team": team,
        "stories_created": stories_created,
        "stories_done":    stories_done,
        "stories_blocked": stories_blocked,
        "tokens_in":       tokens_in,
        "tokens_out":      tokens_out,
        "states":          dict(states),
        "events":          dict(events),
        "test_rc":         rc,
        "test_tail":       tail,
        "wall":            wall,
    })

def cell(v, w=24):
    s = str(v)
    return s if len(s) <= w else s[:w-1] + "…"

if len(rows) >= 2 and "MISSING" not in (r.get("workspace") for r in rows):
    print("\n─── COMPARISON " + "─" * 60)
    print(f"{'metric':<20} | {'waterfall':<24} | {'scrum':<24}")
    print("-" * 74)
    def row(label, key):
        wv = rows[0].get(key, "-")
        sv = rows[1].get(key, "-")
        print(f"{label:<20} | {cell(wv):<24} | {cell(sv):<24}")
    row("stories_created",     "stories_created")
    row("stories_done",        "stories_done")
    row("stories_blocked",     "stories_blocked")
    row("tokens_in",           "tokens_in")
    row("tokens_out",          "tokens_out")
    row("test_rc",             "test_rc")
    print(f"{'test_tail':<20} | {cell(rows[0]['test_tail']):<24} | {cell(rows[1]['test_tail']):<24}")
    print("\n─── SCRUM EVENTS " + "─" * 58)
    for k, v in sorted(rows[1]["events"].items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")
    print()

for r in rows:
    if r.get("workspace") == "MISSING":
        print(f"\n[{r['team']}] MISSING workspace — did the run fail before writing?")
PY

echo ""
echo "==> Building HTML comparison report"
HERE="$(cd "$(dirname "$0")" && pwd)"
HTML_OUT="/tmp/orgos-comparison.html"
python3 "$HERE/build_comparison_html.py" \
    --repo "$REPO" \
    --waterfall-team "$WATERFALL_TEAM" \
    --scrum-team     "$SCRUM_TEAM" \
    --goal "$GOAL" --model "$MODEL" --executor "$EXECUTOR" \
    --out "$HTML_OUT"

echo ""
echo "==> Done."
echo "    logs:    /tmp/orgos-cmp-waterfall.log  /tmp/orgos-cmp-scrum.log"
echo "    html:    $HTML_OUT"
if command -v open >/dev/null 2>&1; then
    echo "    (open in browser: open $HTML_OUT)"
fi
