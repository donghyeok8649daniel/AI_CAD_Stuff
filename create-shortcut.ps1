$ErrorActionPreference = 'Stop'
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Prompt CAD Studio.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'Start CAD.vbs') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Prompt CAD Studio - Local parametric CAD'
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'static\app.ico') + ',0'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output $shortcutPath
