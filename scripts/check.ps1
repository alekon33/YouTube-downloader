$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $python -m ruff check $projectRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m mypy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pytest
exit $LASTEXITCODE

