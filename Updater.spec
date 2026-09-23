"""Small standalone updater for existing native installations."""
from pathlib import Path
root = Path(SPECPATH)
a = Analysis([str(root / 'update_desktop.py')], pathex=[str(root)],
             binaries=[], datas=[], hiddenimports=[],
             excludes=['PySide6', 'OCP', 'cadquery', 'numpy', 'scipy', 'vtkmodules', 'openai', 'pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PromptCADStudioUpdater',
          debug=False, strip=False, upx=False, console=False, icon=str(root / 'static/app.ico'))
