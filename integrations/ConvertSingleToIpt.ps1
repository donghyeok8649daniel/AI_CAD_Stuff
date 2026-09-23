param([string]$JobFile = (Join-Path $PSScriptRoot 'job.json'))
$ErrorActionPreference = 'Stop'
$cadJob = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
$cadSource = [IO.Path]::GetFullPath($cadJob.source)
$cadTarget = [IO.Path]::GetFullPath($cadJob.target)
if ([IO.Path]::GetExtension($cadSource) -ne '.step' -or -not (Test-Path -LiteralPath $cadSource -PathType Leaf)) { throw 'Valid STEP source required.' }
if ([IO.Path]::GetExtension($cadTarget) -ne '.ipt' -or (Test-Path -LiteralPath $cadTarget)) { throw 'Choose a new IPT output filename.' }
$cadDocument = $null
try {
    $cadInventor = New-Object -ComObject Inventor.Application
    $cadDocument = $cadInventor.Documents.Open($cadSource, $false)
    if ($cadDocument.DocumentType -ne 12290) { throw 'Select part import settings in Inventor; this STEP opened as an assembly.' }
    $cadDocument.SaveAs($cadTarget, $false)
    if (-not (Test-Path -LiteralPath $cadTarget -PathType Leaf)) { throw 'IPT was not created.' }
    Write-Output $cadTarget
} finally {
    if ($null -ne $cadDocument) { $cadDocument.Close($true) }
}
