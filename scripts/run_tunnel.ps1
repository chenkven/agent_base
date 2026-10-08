# Run after hsk-cli login. The latest public URL is stored outside Git.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) {
    throw 'npx.cmd not found. Install Node.js first.'
}
$stateDir = Join-Path $projectRoot '.service-state'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$urlFile = Join-Path $stateDir 'public_url.txt'
Set-Location -LiteralPath $projectRoot
while ($true) {
    Remove-Item -LiteralPath $urlFile -ErrorAction SilentlyContinue
    & npx.cmd -y '@aweray/hsk-cli' tunnel --ip 127.0.0.1 --port 8000 --format json 2>&1 | ForEach-Object {
        $line = [string]$_
        Write-Host $line
        if ($line -match '"(?:publicUrl|public_url)"\s*:\s*"(https?://[^"\s]+)"') {
            $url = $Matches[1]
            Set-Content -LiteralPath $urlFile -Value $url -Encoding UTF8
            Write-Host "Current public URL: $url"
        }
    }
    Write-Warning 'Tunnel exited. Reconnecting in 5 seconds; public URL may change. Press Ctrl+C to stop.'
    Start-Sleep -Seconds 5
}
