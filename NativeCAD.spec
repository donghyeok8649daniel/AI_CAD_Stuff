"""Build a native Qt Widgets / VTK app. No HTML, WebView, or HTTP server."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs,collect_submodules,copy_metadata,get_package_paths
root=Path(SPECPATH)
site=Path(get_package_paths('OCP')[0])
datas=[(str(root/'static/app.ico'),'assets'),(str(root/'integrations'),'integrations'),(str(root/'examples'),'examples')]
datas+=copy_metadata('cadquery')+copy_metadata('cadquery-ocp')
binaries=collect_dynamic_libs('OCP')+[(str(p),'cadquery_ocp.libs') for p in (site/'cadquery_ocp.libs').glob('*') if p.is_file()]
hidden=collect_submodules('OCP')+['anyio._backends._asyncio','vtkmodules.qt.QVTKRenderWindowInteractor','vtkmodules.vtkRenderingOpenGL2','vtkmodules.vtkRenderingFreeType','vtkmodules.vtkInteractionStyle','vtkmodules.vtkInteractionWidgets','vtkmodules.vtkIOImage']
excluded=['pytest','tkinter','matplotlib','IPython','jupyter','webview','uvicorn','fastapi','starlette','PyQt5','PyQt6','PySide2','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick','PySide6.QtQml','PySide6.QtQuick','PySide6.QtQuickWidgets','PySide6.QtMultimedia','PySide6.QtMultimediaWidgets','PySide6.Qt3DCore','PySide6.QtCharts','PySide6.QtDataVisualization','PySide6.QtPdf','PySide6.QtPdfWidgets','cadstudio.server']
a=Analysis([str(root/'native_desktop.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden,excludes=excluded)
# Qt on Windows uses the operating system's unversioned ICU exports. Build hosts
# with Poppler on PATH can otherwise contribute an incompatible ICU 78 DLL.
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'icuuc.dll','icudt78.dll'}]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PromptCADStudio',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'static/app.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PromptCADStudio')
