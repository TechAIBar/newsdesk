[CmdletBinding()]
param(
    [string]$PairingFile = '',
    [switch]$EnableOpenClaw,
    [string]$OpenClawCommand = 'openclaw',
    [string]$WslDistro = '',
    [switch]$NoAutoStart,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$packageDir = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $packageDir 'NewsDesk.exe'))) {
    $packageDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\NewsDesk'
}
if (-not (Test-Path -LiteralPath (Join-Path $packageDir 'NewsDesk.exe'))) {
    throw 'Run scripts\build.ps1 first, or use the extracted release package.'
}
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\NewsDesk'
if (Get-Process -Name NewsDesk,NewsDesk-CLI -ErrorAction SilentlyContinue) {
    throw 'Please exit NewsDesk from its tray menu before installing.'
}
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
if ((Resolve-Path -LiteralPath $packageDir).Path -ne (Resolve-Path -LiteralPath $installDir).Path) {
    Get-ChildItem -LiteralPath $packageDir | Copy-Item -Destination $installDir -Recurse -Force
}
$cliExe = Join-Path $installDir 'NewsDesk-CLI.exe'
& $cliExe init
if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed.' }
if ($PairingFile) {
    & $cliExe pair-openclaw --file $PairingFile
    if ($LASTEXITCODE -ne 0) { Write-Warning 'LAN pairing failed; retry from NewsDesk Settings > OpenClaw.' }
}
if ($EnableOpenClaw) {
    $authArgs = @('authorize-openclaw','--command',$OpenClawCommand)
    if ($WslDistro) { $authArgs += @('--wsl',$WslDistro) }
    & $cliExe @authArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'OpenClaw authorization failed. NewsDesk is installed; authorize again after configuring OpenClaw.'
    }
}
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'NewsDesk.lnk'))
$shortcut.TargetPath = Join-Path $installDir 'NewsDesk.exe'
$shortcut.Arguments = 'run --show'
$shortcut.WorkingDirectory = $installDir
$shortcut.Save()
$startupLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'NewsDesk.lnk'
if (-not $NoAutoStart) {
    $startup = $shellObject.CreateShortcut($startupLink)
    $startup.TargetPath = Join-Path $installDir 'NewsDesk.exe'
    $startup.Arguments = 'run'
    $startup.WorkingDirectory = $installDir
    $startup.Save()
} elseif (Test-Path -LiteralPath $startupLink) {
    Remove-Item -LiteralPath $startupLink -Force
}
Write-Host "Installed: $installDir"
if (-not $NoLaunch) {
    Start-Process -FilePath (Join-Path $installDir 'NewsDesk.exe') -ArgumentList 'run --show' -WindowStyle Hidden
}
