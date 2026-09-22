# Third-party components

The native Windows package uses unmodified upstream libraries. The portable layout keeps their DLLs individually replaceable. This application does not prohibit modification or reverse engineering of LGPL-covered libraries for debugging modifications to those libraries. Third-party components retain their own licenses.

- **PySide6 / Shiboken 6.10.2**, LGPL-3.0 or upstream alternative licenses. **Qt 6.10.2** Core, GUI, Widgets, SVG, Network and test/runtime support. Full LGPL/GPL texts are in `licenses/Qt-*.txt`; wheel notices are in `licenses/PySide6*` and `licenses/shiboken6*`. [Corresponding PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.10.2), [Qt base source](https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v6.10.2), [Qt SVG source](https://code.qt.io/cgit/qt/qtsvg.git/tree/?h=v6.10.2), [Qt image formats source](https://code.qt.io/cgit/qt/qtimageformats.git/tree/?h=v6.10.2). Qt third-party source notices are preserved in the corresponding upstream sources. Qt DLLs and plugins are in `_internal/PySide6/` and may be replaced with compatible modified builds.
- **VTK 9.6.2**, BSD-style license; notice in `licenses/vtk-9.6.2/`. [Corresponding source](https://gitlab.kitware.com/vtk/vtk/-/tree/v9.6.2).
- **CadQuery 2.8.0**, Apache-2.0. [Source](https://github.com/CadQuery/cadquery/tree/2.8.0).
- **cadquery-ocp 7.9.3.1.1**, Apache-2.0 Python bindings. [Source and build tooling](https://github.com/CadQuery/OCP).
- **Open CASCADE Technology 7.9.3**, LGPL-2.1 with the OCCT exception. Shared libraries are in `_internal/cadquery_ocp.libs`. Notices in `licenses/OCCT-*`. [Corresponding source](https://github.com/Open-Cascade-SAS/OCCT/tree/V7_9_3).
- **PyInstaller 6.22.3**, GPL with bootloader exception. Python, NumPy, SciPy, Pydantic, HTTPX, OpenAI SDK and dependencies retain upstream notices in `licenses/`.

`requirements-lock.txt` and `licenses/distribution-versions.txt` record the complete build environment, including packages not bundled in the native executable. The license collection also retains notices from the legacy web development environment.

The optional legacy web source includes **Three.js 0.180.0** (MIT), FastAPI and Uvicorn. Three.js is in `static/vendor`; OrbitControls only changes its import to the local vendored module. These web assets and pywebview are not included in the native executable.

No Autodesk source code, artwork, logos or proprietary assets are included. This is an independent application.
