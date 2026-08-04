param(
    [int] $N = 3,
    [int] $BudgetSeconds = 2700
)
# Batch driver - runs N iterations of each arm sequentially.
# Total wall time: ~N * 3 * BudgetSeconds ~= 6.75 hrs at N=3.
# Scores each run against the held-out reference test suite immediately
# so partial results are usable if the batch is interrupted.

Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos

$benchRoot = "C:\temp\bench"
$targetsRoot = "$benchRoot\targets"
$scoresRoot = "$benchRoot\scores"
New-Item -ItemType Directory -Force -Path $targetsRoot | Out-Null
New-Item -ItemType Directory -Force -Path $scoresRoot | Out-Null

$summaryPath = "$scoresRoot\_summary.json"
$results = @()

function Save-Summary {
    param($rs)
    ($rs | ConvertTo-Json -Depth 10) | Set-Content $summaryPath -Encoding utf8
}

function Score-Run {
    param([string]$Target, [string]$Label)
    Write-Host "[batch] scoring $Label ..." -ForegroundColor Cyan
    $out = "$scoresRoot\$Label.json"
    $exit = & .\.venv\Scripts\python.exe scripts\score_reftests.py `
        --target $Target --label $Label --out $out 2>&1 |
        Select-Object -Last 1
    Write-Host $exit -ForegroundColor Green
    if (Test-Path $out) {
        $r = Get-Content $out -Raw | ConvertFrom-Json
        return @{
            label = $Label
            passed = $r.counts.passed
            total  = $r.counts.total
            pct    = $r.counts.pct_pass
            wall_score_seconds = $r.wall_seconds
        }
    }
    return @{ label = $Label; passed = 0; total = 0; pct = 0; error = "score file missing" }
}

$overallT0 = Get-Date

for ($i = 1; $i -le $N; $i++) {
    foreach ($arm in @("wf", "co", "ms")) {
        $label = "${arm}-${i}"
        $target = "$targetsRoot\$label"
        $scoreFile = "$scoresRoot\$label.json"

        # Resumable: skip labels that already have a real score (nonzero total).
        if (Test-Path $scoreFile) {
            try {
                $prev = Get-Content $scoreFile -Raw | ConvertFrom-Json
                if ($prev.counts.total -gt 0) {
                    Write-Host "[batch] SKIP $label (already scored: $($prev.counts.passed)/$($prev.counts.total))" -ForegroundColor DarkGray
                    $results += @{
                        label = $label; arm = $arm; iteration = $i
                        passed = $prev.counts.passed; total = $prev.counts.total
                        pct = $prev.counts.pct_pass; arm_wall_seconds = 0
                        resumed = $true
                    }
                    Save-Summary $results
                    continue
                }
            } catch {}
        }

        Write-Host "" 
        Write-Host "==========================================================" -ForegroundColor Yellow
        Write-Host "[batch] iteration $i / $N   arm: $arm   label: $label"     -ForegroundColor Yellow
        Write-Host "==========================================================" -ForegroundColor Yellow

        $armT0 = Get-Date
        switch ($arm) {
            "wf" { & .\bench\wf_arm.ps1      -Target $target -TeamId $label -BudgetSeconds $BudgetSeconds }
            "co" { & .\bench\copilot_arm.ps1 -Target $target -Label  $label -BudgetSeconds $BudgetSeconds }
            "ms" { & .\bench\scrum_arm.ps1   -Target $target -TeamId $label -BudgetSeconds $BudgetSeconds }
        }
        $armWall = ((Get-Date) - $armT0).TotalSeconds

        # Score against reftests - use the arm's delivery branch as target
        $scoreTarget = switch ($arm) {
            "wf" { "$target\.orgos_teams\$label\integration" }
            "co" { $target }
            "ms" { "$target\.orgos_teams\$label\integration" }
        }
        if (-not (Test-Path $scoreTarget)) {
            Write-Host "[batch] score target missing: $scoreTarget - falling back to $target" -ForegroundColor Red
            $scoreTarget = $target
        }

        $score = Score-Run -Target $scoreTarget -Label $label
        $score.arm = $arm
        $score.iteration = $i
        $score.arm_wall_seconds = [math]::Round($armWall, 1)
        $results += $score

        Save-Summary $results
        Write-Host "[batch] $label -> $($score.passed)/$($score.total) ($($score.pct)%) in $([math]::Round($armWall/60,1))min" -ForegroundColor Magenta
    }
}

$overallWall = ((Get-Date) - $overallT0).TotalSeconds
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "[batch] all N=$N iterations complete in $([math]::Round($overallWall/3600,2))h" -ForegroundColor Green
Write-Host "         summary: $summaryPath"                                                  -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

# Print concise per-arm mean / range
Write-Host ""
Write-Host "REFERENCE-SUITE PASS RATE (per arm):" -ForegroundColor Cyan
foreach ($arm in @("wf", "co", "ms")) {
    $vals = @($results | Where-Object arm -eq $arm | ForEach-Object { $_.pct })
    if ($vals.Count -gt 0) {
        $m = [math]::Round(($vals | Measure-Object -Average).Average, 1)
        $lo = ($vals | Measure-Object -Minimum).Minimum
        $hi = ($vals | Measure-Object -Maximum).Maximum
        Write-Host ("  {0} : mean={1}% range=[{2},{3}] runs={4}" -f $arm, $m, $lo, $hi, $vals.Count)
    }
}
