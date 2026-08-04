# Sequential single-agent baseline using GitHub Copilot CLI.
# Represents the "Claude Code / OpenCode / Copilot CLI" pattern:
# one strong generalist agent, one story at a time, no team, no board.
# This is the fair "no-orgos" comparison point.

Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# Fresh target
$target = "C:\temp\minisearch-copilot"
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
New-Item -ItemType Directory -Path $target | Out-Null
Push-Location $target
git init -q
git config user.email "orgos@example.com"
git config user.name "orgos"
"# minisearch (copilot-baseline target)" | Set-Content README.md -Encoding utf8
git add -A
git commit -q -m "init"
Pop-Location

# Parse the 28 stories from the spec into a JSON list so we don't
# reimplement spec_parser in PowerShell.
$specStoriesJson = & .\.venv\Scripts\python.exe -c @"
import json, sys
sys.path.insert(0, '.')
from orgos.agile.spec_parser import parse_spec_text
spec = open('docs/specs/minisearch.md', 'r', encoding='utf-8').read()
stories = parse_spec_text(spec)
out = []
for s in stories:
    out.append({
        'title': s.title,
        'body':  s.body,
        'files': s.files_to_touch or [],
        'ac':    s.acceptance_criteria or [],
        'type':  s.type,
    })
print(json.dumps(out))
"@
$stories = $specStoriesJson | ConvertFrom-Json
Write-Host "[baseline] parsed $($stories.Count) stories from spec"

# Wall-clock budget (match wf1/wf2/ms1-first-run: 45 min)
$budget_seconds = 2700
$t0 = Get-Date
$logPath = "C:\Users\thanh-huy.e.nguyen\Documents\orgos\copilot-baseline.log"
"" | Set-Content $logPath

$stories_done = 0
$stories_failed = 0
$per_story = @()

for ($i = 0; $i -lt $stories.Count; $i++) {
    $s = $stories[$i]
    $elapsed = (Get-Date) - $t0
    if ($elapsed.TotalSeconds -gt $budget_seconds) {
        "[baseline] budget exhausted at $($elapsed.TotalSeconds)s, stopping" | Tee-Object -Append -FilePath $logPath
        break
    }

    $storyNum = "{0:D2}" -f ($i + 1)
    $title = $s.title
    $body  = $s.body
    $ac    = if ($s.ac) { ($s.ac -join "`n  - ") } else { "(none)" }
    $files = if ($s.files) { ($s.files -join ", ") } else { "(unspecified)" }

    $prompt = @"
You are implementing a single story in a text-search-engine codebase.

TARGET REPO: $target
Current working directory is already $target. All git operations should run in $target. Do NOT cd anywhere else.

STORY ${storyNum}: $title

BODY:
$body

FILES TO TOUCH: $files

ACCEPTANCE CRITERIA:
  - $ac

INSTRUCTIONS:
- Implement the story. Create/edit only the files listed above (plus package __init__.py if needed).
- After implementing, commit with: cd $target && git add -A && git commit -m "$($s.type): $title"
- Do NOT push. Do NOT create branches. Do NOT edit unrelated files.
- If tests are needed, write them but do not spend more than 3 minutes running them.
"@

    "[baseline] === story $storyNum / $($stories.Count) === $title" | Tee-Object -Append -FilePath $logPath
    "[baseline]   files: $files" | Tee-Object -Append -FilePath $logPath

    $s_t0 = Get-Date
    $baselineSha = & git -C $target rev-parse HEAD
    try {
        # copilot is a .ps1 shim; PowerShell 5 argv-passer mangles multi-line
        # strings and embedded quotes into separate args. Flatten prompt to a
        # single line and swap double-quotes for single-quotes so it survives.
        Set-Location $target
        $flatPrompt = ($prompt -replace "`r`n", " | " -replace "`n", " | " -replace '"', "'")
        $out = & copilot -p $flatPrompt --allow-all-tools --allow-all-paths --add-dir $target 2>&1 | Out-String
    } catch {
        $out = "(copilot error: $_)"
        "[baseline]   ERROR: $_" | Tee-Object -Append -FilePath $logPath
    }
    $s_wall = ((Get-Date) - $s_t0).TotalSeconds

    # Did the story land a commit?
    $headSha = & git -C $target rev-parse HEAD
    $committed = ($headSha -ne $baselineSha)

    if ($committed) {
        $stories_done++
        $sha = $headSha.Substring(0,7)
        "[baseline]   COMMITTED $sha ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
        $status = "committed"
    } else {
        # Copilot might have written files but not committed. Try committing on its behalf.
        $dirty = & git -C $target status --porcelain
        if ($dirty) {
            & git -C $target add -A
            & git -C $target commit -q -m "copilot: $title" 2>&1 | Out-Null
            $headSha = & git -C $target rev-parse HEAD
            if ($headSha -ne $baselineSha) {
                $stories_done++
                $sha = $headSha.Substring(0,7)
                "[baseline]   RECOVERED-COMMIT $sha ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
                $status = "recovered"
            } else {
                $stories_failed++
                $sha = ""
                "[baseline]   FAILED - no changes ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
                $status = "no_commit"
            }
        } else {
            $stories_failed++
            $sha = ""
            "[baseline]   FAILED - no diff ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
            $status = "no_commit"
        }
    }

    # Save last 40 lines of copilot output for debugging
    $tail = ($out | Select-Object -Last 40) -join "`n"
    $per_story += [pscustomobject]@{
        story_num = $storyNum
        title = $title
        status = $status
        commit_sha = $sha
        wall_seconds = [math]::Round($s_wall, 2)
        output_tail = $tail
    }
}

$total_wall = ((Get-Date) - $t0).TotalSeconds

# Emit a campaign_result.json shaped like orgos's for the comparison HTML.
$workspaceDir = "$target\.orgos_teams\copilot-baseline"
New-Item -ItemType Directory -Path $workspaceDir -Force | Out-Null
New-Item -ItemType Directory -Path "$workspaceDir\board\stories" -Force | Out-Null

$campaign = @{
    team_id = "copilot-baseline"
    goal = "minisearch spec (28 stories) via scripted GitHub Copilot CLI"
    model = "copilot (default)"
    executor = "copilot-cli"
    topology = "sequential-solo-agent"
    started_at = $t0.ToUniversalTime().ToString("o")
    ended_at   = (Get-Date).ToUniversalTime().ToString("o")
    reason_stopped = if ($stories_done + $stories_failed -ge $stories.Count) { "backlog_empty" } else { "timeout" }
    stories_created = $stories.Count
    stories_done = $stories_done
    stories_blocked = $stories_failed
    story_counts_by_state = @{
        done = $stories_done
        blocked = $stories_failed
        ready = ($stories.Count - $stories_done - $stories_failed)
    }
    total_tokens_input = 0   # Copilot CLI doesn't expose token counts
    total_tokens_output = 0
    per_story_results = @($per_story | ForEach-Object {
        @{
            story_id = "CB-$($_.story_num)-$([regex]::Replace($_.title.ToLower(),'[^a-z0-9]+','-'))"
            worker = "copilot-cli"
            status = $_.status
            commit_sha = $_.commit_sha
            wall_seconds = $_.wall_seconds
            tokens_in = 0
            tokens_out = 0
        }
    })
    sprints = @()  # no sprint concept
    wall_seconds = [math]::Round($total_wall, 2)
}
$campaign | ConvertTo-Json -Depth 10 | Set-Content "$workspaceDir\campaign_result.json" -Encoding utf8

# Also emit minimal story JSONs so build_comparison_html can read state
foreach ($p in $per_story) {
    $sid = "CB-$($p.story_num)-$([regex]::Replace($p.title.ToLower(),'[^a-z0-9]+','-'))"
    $state = if ($p.status -eq "committed" -or $p.status -eq "recovered") { "done" } else { "blocked" }
    $storyDoc = @{
        issue_id = $sid
        title = $p.title
        type = "feature"
        state = $state
        priority = 100 - [int]$p.story_num
        commit_sha = $p.commit_sha
        points = 3
    }
    $storyDoc | ConvertTo-Json | Set-Content "$workspaceDir\board\stories\$sid.json" -Encoding utf8
}

# Point integration files at the flat repo (no worktree here — one target)
New-Item -ItemType Directory -Path "$workspaceDir\integration" -Force | Out-Null
Copy-Item "$target\*" "$workspaceDir\integration\" -Recurse -Force -Exclude ".orgos_teams" -ErrorAction SilentlyContinue

"" | Tee-Object -Append -FilePath $logPath
"=== SUMMARY ===" | Tee-Object -Append -FilePath $logPath
"stories_created: $($stories.Count)" | Tee-Object -Append -FilePath $logPath
"stories_done:    $stories_done" | Tee-Object -Append -FilePath $logPath
"stories_blocked: $stories_failed" | Tee-Object -Append -FilePath $logPath
"wall_seconds:    $([math]::Round($total_wall,1))" | Tee-Object -Append -FilePath $logPath
"campaign_result: $workspaceDir\campaign_result.json" | Tee-Object -Append -FilePath $logPath
Write-Host "`ncopilot-baseline finished. See $logPath and $workspaceDir\campaign_result.json"
