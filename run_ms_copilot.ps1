Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:OTEL_SDK_DISABLED = "true"

$target = "C:\temp\minisearch-copilot-scrum"
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
New-Item -ItemType Directory -Path $target | Out-Null
Push-Location $target
git init -q
git config user.email "orgos@example.com"
git config user.name "orgos"
"# minisearch (scrum + copilot executor)" | Set-Content README.md -Encoding utf8
git add -A
git commit -q -m "init"
Pop-Location

$logPath = "C:\Users\thanh-huy.e.nguyen\Documents\orgos\ms-copilot.log"
"" | Set-Content $logPath

# Same shape as ms1: 3 arch + 2 test + 1 sec, 45 min budget, 5-min sprints.
# --executor copilot: coding agents use Copilot CLI. PO/SM/gates still on DeepSeek.
& .\.venv\Scripts\orgos.exe start `
    --repo $target `
    --team-id ms-copilot `
    --spec-file docs/specs/minisearch.md `
    --executor copilot `
    --architects 3 --testers 2 --devsecops 1 `
    --timeout-seconds 2700 `
    --sprint-duration-seconds 300 `
    --fresh 2>&1 | Tee-Object -FilePath $logPath | Out-Null

Write-Host "`n=== ms-copilot finished ==="
Write-Host "log: $logPath"
Write-Host "workspace: $target\.orgos_teams\ms-copilot\"
Get-Content $logPath -Tail 30
