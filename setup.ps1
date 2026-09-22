param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $PythonPath) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $PythonPath = $bundledPython }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*WindowsApps*') { $PythonPath = $command.Source }
        else { throw 'Install 64-bit Python 3.12, then run: .\setup.ps1 -PythonPath C:\path\to\python.exe' }
    }
}
& $PythonPath -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), "Python 3.11-3.13 required; 3.12 recommended"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
& $PythonPath -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network access and retry.' }
Write-Host 'Ready. Double-click Start CAD.vbs, or run .\.venv\Scripts\python.exe launch.py'
