$ErrorActionPreference = 'Stop'
$cadExe = Join-Path $PSScriptRoot 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadExe -PathType Leaf)) {
    throw 'Run Remove CAD File Registration.ps1 beside PromptCADStudio.exe.'
}
$cadReportPath = Join-Path ([IO.Path]::GetTempPath()) ('PromptCADStudio-remove-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $cadArguments = '--unregister-cad-files --registration-report "' + $cadReportPath + '"'
    $cadProcess = Start-Process -FilePath $cadExe -ArgumentList $cadArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $cadReportPath -PathType Leaf)) { throw 'CAD registration removal did not produce a result.' }
    $cadResult = Get-Content -LiteralPath $cadReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cadProcess.ExitCode -ne 0 -or -not $cadResult.success) { throw ('CAD registration removal failed: ' + $cadResult.error) }
} finally {
    if (Test-Path -LiteralPath $cadReportPath -PathType Leaf) { Remove-Item -LiteralPath $cadReportPath -Force }
}
# Remove only the shortcut that still points to this exact installation.
$cadShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Prompt CAD Studio.lnk'
if (Test-Path -LiteralPath $cadShortcutPath -PathType Leaf) {
    $cadShell = New-Object -ComObject WScript.Shell
    $cadShortcut = $cadShell.CreateShortcut($cadShortcutPath)
    if ([IO.Path]::GetFullPath($cadShortcut.TargetPath) -eq [IO.Path]::GetFullPath($cadExe)) {
        Remove-Item -LiteralPath $cadShortcutPath -Force
    }
}
Write-Host 'This installation''s Windows registration and shortcut were removed. Projects and app files are preserved.'
