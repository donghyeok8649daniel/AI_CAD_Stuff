param([switch]$OpenDefaultApps)
$ErrorActionPreference = 'Stop'
$cadExe = Join-Path $PSScriptRoot 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadExe -PathType Leaf)) {
    throw 'Extract the entire Windows ZIP, then run Install.ps1 beside PromptCADStudio.exe.'
}
# The app owns a bounded, reversible per-user registration. No elevation or
# execution-policy change is needed, and normal JSON defaults are preserved.
$cadReportPath = Join-Path ([IO.Path]::GetTempPath()) ('PromptCADStudio-install-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $cadArguments = '--register-cad-files --registration-report "' + $cadReportPath + '"'
    $cadProcess = Start-Process -FilePath $cadExe -ArgumentList $cadArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $cadReportPath -PathType Leaf)) { throw 'CAD file registration did not produce a result.' }
    $cadResult = Get-Content -LiteralPath $cadReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cadProcess.ExitCode -ne 0 -or -not $cadResult.success) { throw ('CAD file registration failed: ' + $cadResult.error) }
} finally {
    if (Test-Path -LiteralPath $cadReportPath -PathType Leaf) { Remove-Item -LiteralPath $cadReportPath -Force }
}
$cadShell = New-Object -ComObject WScript.Shell
$cadShortcut = $cadShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Prompt CAD Studio.lnk'))
$cadShortcut.TargetPath = $cadExe
$cadShortcut.WorkingDirectory = $PSScriptRoot
$cadShortcut.IconLocation = "$cadExe,0"
$cadShortcut.Description = 'Prompt CAD Studio'
$cadShortcut.Save()
Write-Host 'Installed for this Windows user. Native .pcad projects are registered with Prompt CAD Studio.'
if ($cadResult.registration.existing_pcad_default_preserved) {
    Write-Host 'An existing .pcad default was preserved. Select Prompt CAD Studio for .pcad in Windows Default Apps if needed.'
}
Write-Host 'Existing Windows choices and ordinary .json defaults are preserved. Legacy .cad.json files have an Open with CAD context action.'
Write-Host 'See docs/FILE_ASSOCIATIONS_KO.md.'
if ($OpenDefaultApps) {
    Start-Process -FilePath $cadExe -ArgumentList '--default-apps' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}
