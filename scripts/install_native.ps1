param([switch]$OpenDefaultApps)
$ErrorActionPreference = 'Stop'
$cadSourceExe = Join-Path $PSScriptRoot 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadSourceExe -PathType Leaf)) {
    throw 'Extract the entire Windows ZIP, then run Install.ps1 beside PromptCADStudio.exe.'
}
$cadCanonical = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\PromptCADStudio'))
$cadExe = Join-Path $cadCanonical 'PromptCADStudio.exe'
$cadReportPath = Join-Path ([IO.Path]::GetTempPath()) ('PromptCADStudio-install-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $cadArguments = '--install-canonical "' + $cadReportPath + '"'
    $cadProcess = Start-Process -FilePath $cadSourceExe -ArgumentList $cadArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $cadReportPath -PathType Leaf)) { throw 'The installer produced no verification receipt. Existing files were not assumed updated.' }
    $cadResult = Get-Content -LiteralPath $cadReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cadProcess.ExitCode -ne 0 -or -not $cadResult.success -or -not $cadResult.verified_payload) { throw ('Installation was held: ' + $cadResult.error) }
    if ([IO.Path]::GetFullPath($cadResult.install_dir) -ne $cadCanonical -or -not (Test-Path -LiteralPath $cadExe -PathType Leaf)) { throw 'The verified app is not in the single canonical installation folder.' }
    $cadShell = New-Object -ComObject WScript.Shell
    foreach ($cadLinkFolder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $cadShortcut = $cadShell.CreateShortcut((Join-Path $cadLinkFolder 'Prompt CAD Studio.lnk'))
        $cadShortcut.TargetPath = $cadExe
        $cadShortcut.Arguments = ''
        $cadShortcut.WorkingDirectory = $cadCanonical
        $cadShortcut.IconLocation = "$cadExe,0"
        $cadShortcut.Description = 'Prompt CAD Studio'
        $cadShortcut.Save()
    }
    Write-Host ('Installed one current app at ' + $cadCanonical + '. Projects and user profiles are preserved.')
    if (-not $cadResult.registration_succeeded) { Write-Warning ('App files are installed; file registration needs attention: ' + $cadResult.file_association_warning) }
    Write-Host 'Protected Windows choices are preserved. Choose Prompt CAD Studio for .pcad in Default Apps when needed.'
    if ($OpenDefaultApps) { Start-Process -FilePath $cadExe -ArgumentList '--default-apps' -WorkingDirectory $cadCanonical -WindowStyle Hidden }
} finally {
    if (Test-Path -LiteralPath $cadReportPath -PathType Leaf) { Remove-Item -LiteralPath $cadReportPath -Force }
}
