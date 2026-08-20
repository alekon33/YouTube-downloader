param(
    [string]$IsccPath = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$applicationExe = Join-Path $projectRoot 'dist\VideoDownloader\VideoDownloader.exe'
if (-not (Test-Path -LiteralPath $applicationExe)) {
    throw 'Build the standalone application first with scripts\build.ps1.'
}

if (-not $IsccPath) {
    $isccCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    $IsccPath = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath)) {
    throw 'Inno Setup 6 was not found. Pass its ISCC.exe path with -IsccPath.'
}

$env:PYTHONPATH = Join-Path $projectRoot 'src'
$appVersion = & $venvPython -c 'from videodownloader import __version__; print(__version__)'
& $venvPython (Join-Path $projectRoot 'scripts\render_icon.py')
& $IsccPath "/DAppVersion=$appVersion" (Join-Path $projectRoot 'installer\VideoDownloader.iss')
if ($LASTEXITCODE -ne 0) {
    throw 'Inno Setup compilation failed.'
}

$installer = Join-Path $projectRoot "installer\output\VideoDownloaderSetup-$appVersion.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Expected installer was not created: $installer"
}
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$hashLine = "$hash  $([System.IO.Path]::GetFileName($installer))"
Set-Content -LiteralPath "$installer.sha256" -Value $hashLine -Encoding ascii
Write-Host "Installer: $installer"
Write-Host "SHA-256: $hash"

