# Third-party components

- **Three.js 0.180.0**, MIT. Browser runtime is vendored in `static/vendor/`; copyright and full license are in `static/vendor/LICENSE`. The sole source adjustment to `OrbitControls.js` changes its `three` import to the local `./three.module.js` path. [Upstream](https://github.com/mrdoob/three).
- **CadQuery 2.8.0**, Apache-2.0. Installed with pip for source use and bundled in the Windows download. [Source](https://github.com/CadQuery/cadquery/tree/2.8.0).
- **cadquery-ocp 7.9.3.1.1**, Apache-2.0 Python bindings. [Source and build tooling](https://github.com/CadQuery/OCP).
- **Open CASCADE Technology 7.9.3**, LGPL-2.1 with the OCCT exception. Its unmodified shared libraries are included by the OCP wheel in `_internal/cadquery_ocp.libs`. Notices are in `licenses/OCCT-*`. [Corresponding upstream source](https://github.com/Open-Cascade-SAS/OCCT/tree/V7_9_3). The portable distribution keeps shared libraries replaceable.
- **pywebview 6.2.1**, BSD-3-Clause, native window using Microsoft WebView2 (separately installed runtime). **PyInstaller 6.22.3** uses its GPL license with bootloader exception. Their distribution notices are in `licenses/`.
- FastAPI, Uvicorn, Pydantic, OpenAI Python SDK, pytest, and their transitive dependencies are installed through their official PyPI distributions and retain their upstream licenses. Exact tested package versions are recorded in `requirements-lock.txt`.

No Autodesk source code, artwork, logos, or proprietary assets are included. Interface ideas were informed by public Autodesk documentation; this is an independent application.

The Windows package includes the installed distributions' license/notice files in `licenses/`, plus Python, Three.js and OCCT notices. `requirements-lock.txt` and `licenses/distribution-versions.txt` identify the build environment. This includes development dependencies that may not all be present in the executable. Third-party components retain their own licenses; no alternative license is assigned to them by this application.
