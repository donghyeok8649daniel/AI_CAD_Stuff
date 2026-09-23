"""Create a portable ZIP from a completed PyInstaller onedir build."""
from pathlib import Path
import argparse
import hashlib
import shutil
import sys
from zipfile import ZipFile, ZIP_DEFLATED
parser=argparse.ArgumentParser();parser.add_argument('bundle',type=Path);parser.add_argument('zip',type=Path);parser.add_argument('--updater',type=Path,required=True);args=parser.parse_args()
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
from cadstudio import __version__
from cadstudio.updater import make_manifest
assert (args.bundle/'PromptCADStudio.exe').is_file()
assert args.updater.is_file()
shutil.copy2(args.updater,args.bundle/'PromptCADStudioUpdater.exe')
for folder in ['licenses','examples','integrations','docs']:
    shutil.copytree(root/folder,args.bundle/folder,dirs_exist_ok=True)
for name in ['README.md','THIRD_PARTY.md','VALIDATION.md','requirements-lock.txt']:
    shutil.copy2(root/name,args.bundle/name)
(args.bundle/'Create Desktop Shortcut.ps1').write_text('''$cadExe = Join-Path $PSScriptRoot 'PromptCADStudio.exe'
if (-not (Test-Path -LiteralPath $cadExe)) { throw 'Extract the entire ZIP first.' }
$cadShell = New-Object -ComObject WScript.Shell
$cadShortcut = $cadShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Prompt CAD Studio.lnk'))
$cadShortcut.TargetPath = $cadExe
$cadShortcut.WorkingDirectory = $PSScriptRoot
$cadShortcut.IconLocation = "$cadExe,0"
$cadShortcut.Description = 'Prompt CAD Studio'
$cadShortcut.Save()
''',encoding='utf-8-sig')
make_manifest(args.bundle,__version__)
with ZipFile(args.zip,'w',ZIP_DEFLATED,compresslevel=6) as archive:
    for path in args.bundle.rglob('*'):
        if path.is_file():archive.write(path,Path('PromptCADStudio')/path.relative_to(args.bundle))
digest=hashlib.file_digest(args.zip.open('rb'),'sha256').hexdigest()
args.zip.with_suffix('.sha256').write_text(f'{digest}  {args.zip.name}\n',encoding='ascii')
print(f'{args.zip.name}: {args.zip.stat().st_size/1024**2:.1f} MiB; SHA256 {digest}')
