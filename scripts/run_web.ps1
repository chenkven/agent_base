# Run from either the project root or this script's directory. Ctrl+C stops it.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}
Set-Location -LiteralPath $projectRoot
while ($true) {
    & $python -m uvicorn app.web:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
    Write-Warning 'Web service exited. Restarting in 3 seconds. Press Ctrl+C to stop.'
    Start-Sleep -Seconds 3
}
