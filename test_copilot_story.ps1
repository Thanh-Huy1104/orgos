Set-Location C:\Users\thanh-huy.e.nguyen\Documents\orgos
$specStoriesJson = & .\.venv\Scripts\python.exe -c @"
import json, sys
sys.path.insert(0, '.')
from orgos.agile.spec_parser import parse_spec_text
spec = open('docs/specs/minisearch.md', 'r', encoding='utf-8').read()
stories = parse_spec_text(spec)
s = stories[0]
print(json.dumps({'title': s.title, 'body': s.body, 'files': s.files_to_touch or [], 'ac': s.acceptance_criteria or [], 'type': s.type}))
"@
$s = $specStoriesJson | ConvertFrom-Json
$target = "C:\temp\minisearch-copilot"
Set-Location $target
$storyNum = "01"
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
Write-Host "prompt length: $($prompt.Length)"
Write-Host "prompt bytes utf8: $([System.Text.Encoding]::UTF8.GetByteCount($prompt))"
$flatPrompt = ($prompt -replace "`r`n", " | " -replace "`n", " | " -replace '"', "'")
Write-Host "flat length: $($flatPrompt.Length)"
$t0 = Get-Date
$out = & copilot -p $flatPrompt --allow-all-tools --allow-all-paths --add-dir $target 2>&1 | Out-String
$t1 = ((Get-Date) - $t0).TotalSeconds
Write-Host "returned in ${t1}s, output length: $($out.Length)"
Write-Host "--- OUTPUT ---"
Write-Host $out
Write-Host "--- exit: $LASTEXITCODE ---"
