param(
    [Parameter(Mandatory=$true)] [string] $Target,
    [Parameter(Mandatory=$true)] [string] $TeamId,
    [int] $BudgetSeconds = 2700
)
# Scrum arm - flat team of specialists on a shared board.
# 3 architects + 2 testers + 1 devsecops + PO + SM.
# Same shape as the original ms1 pilot run.

Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:OTEL_SDK_DISABLED = "true"

# Load .env (DeepSeek + other keys)
if (Test-Path .env) {
    foreach ($line in Get-Content .env) {
        if ($line -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
            Set-Item -Path ("Env:" + $matches[1]) -Value $matches[2].Trim('"')
        }
    }
}

# Fresh target repo
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
New-Item -ItemType Directory -Path $Target | Out-Null
Push-Location $Target
git init -q
git config user.email "orgos@example.com"
git config user.name "orgos"
"# minisearch scrum ($TeamId)" | Set-Content README.md -Encoding utf8
git add -A
git commit -q -m "init"
Pop-Location

$logPath = "C:\Users\thanh-huy.e.nguyen\Documents\orgos\bench\logs\$TeamId.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null

Write-Host "[$TeamId] scrum starting -> $Target"
$t0 = Get-Date
& .\.venv\Scripts\orgos.exe start `
    --repo $Target `
    --team-id $TeamId `
    --spec-file docs\specs\minisearch.md `
    --executor spawn `
    --model deepseek/deepseek-chat `
    --architects 3 --testers 2 --devsecops 1 `
    --timeout-seconds $BudgetSeconds `
    --sprint-duration-seconds 300 `
    --fresh 2>&1 | Tee-Object -FilePath $logPath | Out-Null
$wall = ((Get-Date) - $t0).TotalSeconds
Write-Host "[$TeamId] scrum finished in $([math]::Round($wall,1))s"
