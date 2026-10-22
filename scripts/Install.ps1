param([string]$UvPath = '', [string]$Python = '3.13', [switch]$WithoutLive)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (!$UvPath) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCommand) { $UvPath = $uvCommand.Source }
}
if (!$UvPath) { throw 'uv is required. Supply -UvPath with the installed uv.exe path.' }
$env:UV_CACHE_DIR = Join-Path $projectRoot '.uv-cache'
$uvArgs = @('sync', '--locked', '--project', $projectRoot, '--python', $Python)
if (!$WithoutLive) { $uvArgs += @('--extra', 'live') }
& $UvPath @uvArgs
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $pythonExe -m ddda_mcp --project $projectRoot --check
if ($LASTEXITCODE -ne 0) { throw 'Setup validation failed; inspect the configured upstream repository.' }
