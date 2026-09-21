[CmdletBinding()]
param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$distRoot = [IO.Path]::GetFullPath((Join-Path $projectDir 'dist'))
$outputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $projectDir $OutputDirectory))
}
if ($outputRoot -ne $distRoot -and -not $outputRoot.StartsWith($distRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDirectory must be inside the project dist directory.'
}
$running = Get-Process 'NewsDesk*' -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and (Split-Path -Parent $_.Path) -eq (Join-Path $outputRoot 'NewsDesk')
}
if ($running) {
    throw 'The output is in use. Choose a new -OutputDirectory inside dist, or exit that copy before building.'
}
Push-Location $projectDir
try {
    $pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    }
    & $pythonExe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $pythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $pythonExe scripts\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    & $pythonExe -m PyInstaller --noconfirm --distpath $outputRoot NewsDesk.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    & $pythonExe scripts\package.py --dist-root $outputRoot
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    Write-Host "Ready: $outputRoot\NewsDesk\NewsDesk.exe and $outputRoot\NewsDesk-windows-x64.zip"
} finally {
    Pop-Location
}
