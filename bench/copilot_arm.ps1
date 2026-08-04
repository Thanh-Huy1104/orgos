param(
    [Parameter(Mandatory=$true)] [string] $Target,
    [Parameter(Mandatory=$true)] [string] $Label,
    [int] $BudgetSeconds = 2700
)
# Solo-agent baseline - one Copilot CLI process, one story at a time.
# Same structure as the yesterday's working run_copilot_baseline.ps1.

Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# Fresh target repo
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Path $Target | Out-Null
Push-Location $Target
git init -q
git config user.email "orgos@example.com"
git config user.name "orgos"
"# minisearch copilot solo ($Label)" | Set-Content README.md -Encoding utf8
git add -A
git commit -q -m "init"
Pop-Location

# Parse spec once
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
Write-Host "[$Label] parsed $($stories.Count) stories"

$logPath = "C:\Users\thanh-huy.e.nguyen\Documents\orgos\bench\logs\$Label.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null
"" | Set-Content $logPath

$t0 = Get-Date
$stories_done = 0
$stories_failed = 0
$per_story = @()

for ($i = 0; $i -lt $stories.Count; $i++) {
    $elapsed = ((Get-Date) - $t0).TotalSeconds
    if ($elapsed -gt $BudgetSeconds) {
        "[$Label] budget exhausted at ${elapsed}s" | Tee-Object -Append -FilePath $logPath
        break
    }

    $s = $stories[$i]
    $storyNum = "{0:D2}" -f ($i + 1)
    $title = $s.title
    $body  = $s.body
    $ac    = if ($s.ac)    { ($s.ac -join "`n  - ") } else { "(none)" }
    $files = if ($s.files) { ($s.files -join ", ") } else { "(unspecified)" }

    $prompt = @"
You are implementing a single story in a text-search-engine codebase.

TARGET REPO: $Target
Current working directory is already $Target. All git operations should run in $Target. Do NOT cd anywhere else.

STORY ${storyNum}: $title

BODY:
$body

FILES TO TOUCH: $files

ACCEPTANCE CRITERIA:
  - $ac

INSTRUCTIONS:
- Implement the story. Create/edit only the files listed above (plus package __init__.py if needed).
- After implementing, commit with: cd $Target && git add -A && git commit -m "$($s.type): $title"
- Do NOT push. Do NOT create branches. Do NOT edit unrelated files.
- If tests are needed, write them but do not spend more than 3 minutes running them.
"@

    # PowerShell 5 argv-passing bug: flatten prompt to a single line + swap quotes.
    $flatPrompt = ($prompt -replace "`r`n", " | " -replace "`n", " | " -replace '"', "'")

    "[$Label] === story $storyNum / $($stories.Count) === $title" | Tee-Object -Append -FilePath $logPath
    $s_t0 = Get-Date
    $baselineSha = & git -C $Target rev-parse HEAD
    try {
        Set-Location $Target
        $out = & copilot -p $flatPrompt --allow-all-tools --allow-all-paths --add-dir $Target 2>&1 | Out-String
    } catch {
        $out = "(copilot error: $_)"
    }
    $s_wall = ((Get-Date) - $s_t0).TotalSeconds

    $headSha = & git -C $Target rev-parse HEAD
    if ($headSha -ne $baselineSha) {
        $stories_done++
        "[$Label]   COMMITTED $($headSha.Substring(0,7)) ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
        $status = "committed"
    } else {
        # Recover uncommitted changes
        $dirty = & git -C $Target status --porcelain
        if ($dirty) {
            & git -C $Target add -A
            & git -C $Target commit -q -m "copilot: $title" 2>&1 | Out-Null
            $stories_done++
            $status = "recovered"
        } else {
            $stories_failed++
            $status = "no_commit"
            "[$Label]   FAILED - no diff ($([math]::Round($s_wall,1))s)" | Tee-Object -Append -FilePath $logPath
        }
    }
    $per_story += [pscustomobject]@{
        story_num = $storyNum; title = $title; status = $status
        wall_seconds = [math]::Round($s_wall, 2)
    }
}

Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$total_wall = ((Get-Date) - $t0).TotalSeconds

# Emit a campaign_result.json shaped like orgos's
$workspaceDir = "$Target\.orgos_teams\$Label"
New-Item -ItemType Directory -Path "$workspaceDir\board\stories" -Force | Out-Null

$campaign = @{
    team_id = $Label; goal = "minisearch spec (28 stories) via scripted Copilot CLI"
    model = "copilot (default)"; executor = "copilot-cli"; topology = "sequential-solo-agent"
    started_at = $t0.ToUniversalTime().ToString("o")
    ended_at   = (Get-Date).ToUniversalTime().ToString("o")
    stories_created = $stories.Count
    stories_done    = $stories_done
    stories_blocked = $stories_failed
    total_tokens_input = 0; total_tokens_output = 0
    per_story_results = @($per_story)
    wall_seconds = [math]::Round($total_wall, 2)
}
$campaign | ConvertTo-Json -Depth 10 | Set-Content "$workspaceDir\campaign_result.json" -Encoding utf8

Write-Host "[$Label] $stories_done done / $stories_failed failed / $($stories.Count) total in $([math]::Round($total_wall,1))s"
