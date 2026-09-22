# Build: python -m PyInstaller PromptCADStudio.spec --distpath <folder> --workpath <folder>
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata, get_package_paths

root=Path(SPECPATH)
site=Path(get_package_paths('OCP')[0])
datas=[(str(root/'static'),'static'),(str(root/'integrations'),'integrations')]
datas+=collect_data_files('webview')
datas+=copy_metadata('cadquery')+copy_metadata('cadquery-ocp')
binaries=collect_dynamic_libs('OCP')+collect_dynamic_libs('webview')
binaries += [(str(path),'cadquery_ocp.libs') for path in (site/'cadquery_ocp.libs').glob('*') if path.is_file()]
hidden=collect_submodules('OCP')+['uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto','uvicorn.protocols.http.h11_impl','uvicorn.protocols.websockets.auto','uvicorn.lifespan.on','webview.platforms.winforms','webview.platforms.edgechromium']
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden,excludes=['pytest','tkinter','matplotlib','IPython','jupyter','webview.platforms.qt','PyQt5','PyQt6','PySide2','PySide6'])
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PromptCADStudio',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'static/app.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PromptCADStudio')
