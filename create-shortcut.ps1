$ErrorActionPreference = 'Stop'
$cadCanonical = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs\PromptCADStudio'))
$cadExe = Join-Path $cadCanonical 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadExe -PathType Leaf)) { throw 'Run the Windows package Install.ps1 first. Source/VBS launchers cannot become the installed app.' }
$cadReportPath = Join-Path ([IO.Path]::GetTempPath()) ('PromptCADStudio-shortcut-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $cadProcess = Start-Process -FilePath $cadExe -ArgumentList ('--register-cad-files --registration-report "' + $cadReportPath + '"') -WorkingDirectory $cadCanonical -WindowStyle Hidden -Wait -PassThru
    if (-not (Test-Path -LiteralPath $cadReportPath -PathType Leaf)) { throw 'Canonical app verification did not produce a receipt.' }
    $cadResult = Get-Content -LiteralPath $cadReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cadProcess.ExitCode -ne 0 -or -not $cadResult.success) { throw ('Canonical registration failed: ' + $cadResult.error) }
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
} finally {
    if (Test-Path -LiteralPath $cadReportPath -PathType Leaf) { Remove-Item -LiteralPath $cadReportPath -Force }
}
