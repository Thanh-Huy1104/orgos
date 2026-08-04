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
.\.venv\Scripts\python.exe -m orgos.cli run `
    --waterfall `
    --repo C:\temp\minisearch-wf `
    --team-id wf1 `
    --spec-file docs\specs\minisearch.md `
    --model deepseek/deepseek-chat `
    --n-workers 3 `
    --sprint-story-cap 28 `
    --sprint-duration 2700 `
    --fresh 2>&1 | Tee-Object -FilePath wf1.log | Out-Null
Write-Host "wf1 finished"
Get-Content wf1.log -Tail 30
