# PreToolUse guard: block Edit/Write to secret / protected files.
$ErrorActionPreference = 'Stop'
$raw = [Console]::In.ReadToEnd()
try { $data = $raw | ConvertFrom-Json } catch { exit 0 }
$file = $data.tool_input.file_path
if (-not $file) { exit 0 }

# Block .env (but allow templates), anything named *secret*, and key material.
$blocked = ($file -match '\.env' -and $file -notmatch '\.(example|sample|template)$') `
    -or ($file -match 'secret') `
    -or ($file -match '\.pem$') `
    -or ($file -match '\.key$')

if ($blocked) {
    [Console]::Error.WriteLine("Blocked: protected file ($file)")
    exit 2
}
exit 0
