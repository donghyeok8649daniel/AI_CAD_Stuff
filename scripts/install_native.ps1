param([switch]$OpenDefaultApps)
$ErrorActionPreference = 'Stop'
$cadSourceExe = Join-Path $PSScriptRoot 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadSourceExe -PathType Leaf)) {
    throw 'Extract the entire Windows ZIP, then run Install.ps1 beside PromptCADStudio.exe.'
}
$cadCanonical = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\PromptCADStudio'))
$cadExe = Join-Path $cadCanonical 'PromptCADStudio.exe'
$cadReportPath = Join-Path ([IO.Path]::GetTempPath()) ('PromptCADStudio-install-' + [guid]::NewGuid().ToString('N') + '.json')
$cadConnectionIncomplete = $false
try {
    $cadArguments = '--install-canonical "' + $cadReportPath + '"'
    $cadProcess = Start-Process -FilePath $cadSourceExe -ArgumentList $cadArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $cadReportPath -PathType Leaf)) { throw 'The installer produced no verification receipt. Existing files were not assumed updated.' }
    $cadResult = Get-Content -LiteralPath $cadReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cadProcess.ExitCode -notin @(0, 3) -or -not $cadResult.success -or -not $cadResult.verified_payload -or -not $cadResult.payload_installed) { throw ('Installation was held: ' + $cadResult.error) }
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
    if ($cadResult.installation_complete -and $cadResult.pcad_routes_current -and $cadProcess.ExitCode -eq 0) {
        Write-Host ('Installed one current app at ' + $cadCanonical + '. Existing Prompt CAD .pcad routes now use this app. Projects and profiles are preserved.')
    } else {
        $cadConnectionIncomplete = $true
        Write-Warning ('App files are installed at ' + $cadCanonical + '; .pcad connection is NOT complete. ' + $cadResult.file_association_warning)
    }
    Write-Host 'Protected Windows choices and other apps are preserved. If connection is incomplete, select Prompt CAD Studio in Windows Default Apps.'
    if ($OpenDefaultApps) { Start-Process -FilePath $cadExe -ArgumentList '--default-apps' -WorkingDirectory $cadCanonical -WindowStyle Hidden }
} finally {
    if (Test-Path -LiteralPath $cadReportPath -PathType Leaf) { Remove-Item -LiteralPath $cadReportPath -Force }
}
if ($cadConnectionIncomplete) { exit 3 }
