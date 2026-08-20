param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Create .venv and install the build dependencies before building.'
}

$buildRoot = Join-Path $projectRoot 'build\nuitka'
$distributionRoot = Join-Path $projectRoot 'dist\VideoDownloader'
foreach ($buildTarget in @($buildRoot, $distributionRoot)) {
    $fullTarget = [System.IO.Path]::GetFullPath($buildTarget)
    if (-not $fullTarget.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe build path: $fullTarget"
    }
}
if ($Clean) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $distributionRoot -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:NUITKA_CACHE_DIR = Join-Path $projectRoot 'build\nuitka-cache'
$appVersion = & $venvPython -c 'from videodownloader import __version__; print(__version__)'
if ($LASTEXITCODE -ne 0 -or -not $appVersion) {
    throw 'Could not read the application version.'
}

& $venvPython (Join-Path $projectRoot 'scripts\render_icon.py')
if ($LASTEXITCODE -ne 0) {
    throw 'Could not render the Windows icon.'
}

$entryPoint = Join-Path $projectRoot 'src\videodownloader\main.py'
$iconPath = Join-Path $projectRoot 'assets\icon.ico'
& $venvPython -m nuitka `
    --mode=standalone `
    --enable-plugin=pyside6 `
    --windows-console-mode=disable `
    --assume-yes-for-downloads `
    --output-dir=$buildRoot `
    --output-filename=VideoDownloader.exe `
    --windows-icon-from-ico=$iconPath `
    --product-name=VideoDownloader `
    --company-name='VideoDownloader contributors' `
    --file-description='Video and playlist downloader powered by yt-dlp' `
    --file-version=$appVersion `
    --product-version=$appVersion `
    --include-package-data=videodownloader `
    $entryPoint
if ($LASTEXITCODE -ne 0) {
    throw 'Nuitka build failed.'
}

$builtExecutable = Get-ChildItem -LiteralPath $buildRoot -Filter 'VideoDownloader.exe' -Recurse | Select-Object -First 1
if (-not $builtExecutable) {
    throw 'Nuitka did not produce VideoDownloader.exe.'
}
$builtDirectory = $builtExecutable.Directory.FullName
Remove-Item -LiteralPath $distributionRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $distributionRoot -Force | Out-Null
Copy-Item -Path (Join-Path $builtDirectory '*') -Destination $distributionRoot -Recurse -Force
Write-Host "Standalone build: $distributionRoot"
