[CmdletBinding()]
param([switch]$RemoveData)
$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\NewsDesk'
if (Get-Process -Name NewsDesk,NewsDesk-CLI -ErrorAction SilentlyContinue) {
    throw 'Please exit NewsDesk from its tray menu before uninstalling.'
}
foreach ($folder in @('Programs','Startup')) {
    $link = Join-Path ([Environment]::GetFolderPath($folder)) 'NewsDesk.lnk'
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
}
$targets = @($installDir)
if ($RemoveData) { $targets += (Join-Path $env:LOCALAPPDATA 'NewsDesk') }
$allowed = @([IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\NewsDesk')), [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'NewsDesk')))
foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if ($resolved -notin $allowed) { throw "Unexpected deletion target: $resolved" }
        if ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to remove a redirected installation directory: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
Write-Host 'NewsDesk uninstalled. OpenClaw and its model credentials are unchanged.'
