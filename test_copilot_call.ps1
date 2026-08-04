# Minimal reproducer of what the loop does.
Set-Location C:\temp\minisearch-copilot
$prompt = @"
You are implementing a single story. Create a file called ping.txt with content 'hello world'. Then commit with: git add -A ; git commit -m 'ping'
"@
Write-Host "prompt length: $($prompt.Length)"
Write-Host "cwd: $PWD"
Write-Host "--- invoking copilot ---"
$t0 = Get-Date
$out = & copilot -p $prompt --allow-all-tools --allow-all-paths --add-dir C:\temp\minisearch-copilot 2>&1 | Out-String
$t1 = ((Get-Date) - $t0).TotalSeconds
Write-Host "--- copilot returned in ${t1}s ---"
Write-Host "output length: $($out.Length)"
Write-Host "output:"
Write-Host $out
Write-Host "--- exit code: $LASTEXITCODE ---"
Write-Host "--- git log ---"
git log --oneline
