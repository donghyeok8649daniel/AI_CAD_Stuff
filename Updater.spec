"""Small standalone updater for existing native installations."""
from pathlib import Path
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

# PyInstaller otherwise silently excludes tkinter when its build-time Tcl
# probe cannot read the runtime. A broken updater must never be publishable.
if not tcltk_info.available:
    raise RuntimeError('Tcl/Tk build probe failed. Build in an environment where tkinter.Tcl() works; do not publish without the GUI smoke test.')
root = Path(SPECPATH)
a = Analysis([str(root / 'update_desktop.py')], pathex=[str(root)],
             binaries=[], datas=[], hiddenimports=[],
             excludes=['PySide6', 'OCP', 'cadquery', 'numpy', 'scipy', 'vtkmodules', 'openai', 'pytest'])
if not any(item[0] == 'tkinter' for item in a.pure):
    raise RuntimeError('Updater build is missing tkinter.')
if not any(str(item[0]).replace('\\', '/').endswith('/init.tcl') for item in a.datas):
    raise RuntimeError('Updater build is missing Tcl runtime data.')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PromptCADStudioUpdater',
          debug=False, strip=False, upx=False, console=False, icon=str(root / 'static/app.ico'))
