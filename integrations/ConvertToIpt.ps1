param([string]$StepDirectory = (Join-Path $PSScriptRoot 'parts'))
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $StepDirectory -PathType Container)) { throw 'Select the exported parts folder with -StepDirectory.' }
$cadInput = (Resolve-Path -LiteralPath $StepDirectory).Path
$cadOutput = Join-Path $cadInput ('IPT-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $cadOutput | Out-Null
try { $cadInventor = New-Object -ComObject Inventor.Application } catch { throw 'Autodesk Inventor must be installed and licensed to create native IPT files.' }
$cadInventor.Visible = $true
foreach ($cadFile in (Get-ChildItem -LiteralPath $cadInput -Filter '*.step' -File)) {
    $cadDocument = $null
    try {
        $cadDocument = $cadInventor.Documents.Open($cadFile.FullName, $false)
        if ($cadDocument.DocumentType -ne 12290) { throw ('STEP did not import as a part: ' + $cadFile.Name + '. Open it in Inventor and choose the part import option.') }
        $cadTarget = Join-Path $cadOutput ($cadFile.BaseName + '.ipt')
        $cadDocument.SaveAs($cadTarget, $false)
        if (-not (Test-Path -LiteralPath $cadTarget -PathType Leaf)) { throw ('IPT save failed: ' + $cadTarget) }
        Write-Output $cadTarget
    } finally { if ($null -ne $cadDocument) { $cadDocument.Close($true) } }
}
Write-Output ('Finished. Native Inventor files: ' + $cadOutput)
