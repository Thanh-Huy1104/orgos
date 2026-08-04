Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:OTEL_SDK_DISABLED = "true"
$envFile = Get-Content .env
foreach ($line in $envFile) {
    if ($line -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
        Set-Item -Path ("Env:" + $matches[1]) -Value $matches[2].Trim('"')
    }
}
# Fresh target
$t = "C:\temp\minisearch-wf2"
if (Test-Path $t) { Remove-Item -Recurse -Force $t }
New-Item -ItemType Directory -Path $t | Out-Null
Push-Location $t
git init -q
git config user.email "orgos@example.com"
git config user.name "orgos"
"# minisearch (waterfall fair-baseline target)" | Set-Content README.md -Encoding utf8
git add -A
git commit -q -m "init"
Pop-Location

.\.venv\Scripts\python.exe -m orgos.cli run `
    --waterfall `
    --repo C:\temp\minisearch-wf2 `
    --team-id wf2 `
    --spec-file docs\specs\minisearch.md `
    --model deepseek/deepseek-chat `
    --n-workers 1 `
    --sprint-story-cap 28 `
    --sprint-duration 2700 `
    --fresh 2>&1 | Tee-Object -FilePath wf2.log | Out-Null

Write-Host "wf2 finished"
Get-Content wf2.log -Tail 15
