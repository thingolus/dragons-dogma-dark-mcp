$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/Install.ps1 first.' }
& $pythonExe -m ddda_mcp --project $projectRoot @args
exit $LASTEXITCODE
