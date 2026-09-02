[CmdletBinding()]
param(
    [Parameter()]
    [string] $Repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),

    [Parameter()]
    [string] $ShortcutPath = (Join-Path ([Environment]::GetFolderPath("Desktop")) "ORION Development Console.lnk")
)

$ErrorActionPreference = "Stop"
$repositoryPath = [IO.Path]::GetFullPath($Repository)
$pythonwPath = Join-Path $repositoryPath ".venv\Scripts\pythonw.exe"
$entryPath = Join-Path $repositoryPath "tools\orion_development_console\windows_entry.py"
$iconPath = Join-Path $repositoryPath "branding\orion.ico"
$projectPath = Join-Path $repositoryPath "pyproject.toml"

foreach ($requiredPath in @($repositoryPath, $pythonwPath, $entryPath, $iconPath, $projectPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required ORION Development Console path is unavailable: $requiredPath"
    }
}

$shortcutParent = Split-Path -Parent $ShortcutPath
if (-not (Test-Path -LiteralPath $shortcutParent -PathType Container)) {
    throw "Shortcut directory is unavailable: $shortcutParent"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut([IO.Path]::GetFullPath($ShortcutPath))
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = ('"{0}" --repository "{1}"' -f $entryPath, $repositoryPath)
$shortcut.WorkingDirectory = $repositoryPath
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "ORION Development Console (development repository)"
$shortcut.WindowStyle = 1
$shortcut.Save()

if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) {
    throw "Windows shortcut was not created: $ShortcutPath"
}

Write-Output ([IO.Path]::GetFullPath($ShortcutPath))
