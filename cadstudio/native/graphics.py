"""Probe native OpenGL out of process before importing Qt/VTK in the CAD UI.

An access violation in a display driver cannot be caught by a Python exception.
Use the Qt-distributed Mesa driver only inside this app; never replace system DLLs.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

_driver_handle = None
PROBE_TIMEOUT = 20


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def software_driver(data):
    if getattr(sys, 'frozen', False):
        driver = Path(sys._MEIPASS) / 'software-renderer' / 'opengl32.dll'
        if not driver.is_file():
            raise RuntimeError('Bundled software OpenGL driver is missing')
        return driver
    spec = importlib.util.find_spec('PySide6')
    source = Path(spec.origin).parent / 'opengl32sw.dll'
    # WGL consumers require the opengl32.dll module name. The source runner
    # uses one reusable cache file; the EXE already bundles this exact name.
    driver = Path(data) / 'software-renderer' / 'opengl32.dll'
    driver.parent.mkdir(parents=True, exist_ok=True)
    digest = lambda p: hashlib.sha256(p.read_bytes()).digest()
    if not driver.is_file() or digest(driver) != digest(source):
        temporary = driver.with_name('opengl32.' + uuid4().hex + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(driver)
        finally:
            temporary.unlink(missing_ok=True)
    return driver


def load_renderer(mode, data):
    global _driver_handle
    if os.name != 'nt' or mode != 'software':
        return
    driver = software_driver(data).resolve()
    os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
    os.environ['QT_OPENGL_DLL'] = str(driver)
    # Must happen BEFORE importing QtGui, VTK, or any other OpenGL consumer.
    _driver_handle = ctypes.WinDLL(str(driver))


def child_command(mode, report):
    entry = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve().parents[2] / 'native_desktop.py')]
    return [sys.executable, *entry, '--graphics-probe', mode, str(report)]


def probe(mode, data):
    data = Path(data)
    report = data / ('graphics-probe-' + uuid4().hex + '.json')
    log_path = data / ('graphics-' + mode + '.log')
    started = time.monotonic()
    result = {'mode': mode, 'ok': False}
    env = dict(os.environ, CADSTUDIO_DATA_DIR=str(data), PYTHONIOENCODING='utf-8')
    try:
        with log_path.open('wb') as output:
            process = subprocess.Popen(child_command(mode, report), env=env,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                result['exit_code'] = process.wait(timeout=PROBE_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this owned, disposable graphics probe.
                process.wait()
                result['error'] = 'Graphics probe timed out'
        if report.exists():
            details = json.loads(report.read_text(encoding='utf-8'))
            result['ok'] = details.get('ok') is True
            result['capabilities'] = details.get('capabilities', '')
        result['ok'] = result.get('exit_code') == 0 and result.get('ok') is True
    except (OSError, ValueError, AttributeError) as exc:
        result.update(ok=False, error=str(exc))
    finally:
        report.unlink(missing_ok=True)
    result['seconds'] = round(time.monotonic() - started, 2)
    return result


def prepare(data, requested='auto'):
    """No graphics libraries may be imported in the caller before this returns."""
    if os.name != 'nt':
        return {'requested': requested, 'selected': 'hardware', 'attempts': []}
    state = {'requested': requested, 'selected': None, 'attempts': []}
    modes = ['hardware', 'software'] if requested == 'auto' else [requested]
    for mode in modes:
        attempt = probe(mode, data)
        state['attempts'].append(attempt)
        if attempt['ok']:
            try:
                load_renderer(mode, data)
                state['selected'] = mode
                break
            except (OSError, RuntimeError) as exc:
                attempt.update(ok=False, error=str(exc))
    write_json(Path(data) / 'graphics-status.json', state)
    if state['selected']:
        os.environ['CADSTUDIO_RENDERER'] = state['selected']
    return state


def run_probe(mode, report, data):
    # Crash dialogs would otherwise keep a failed probe alive indefinitely.
    if os.name == 'nt':
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    import faulthandler
    faulthandler.enable()
    load_renderer(mode, data)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    import vtkmodules.qt
    vtkmodules.qt.PyQtImpl = 'PySide6'
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    from vtkmodules.vtkRenderingCore import vtkRenderer, vtkActor, vtkPolyDataMapper, vtkWindowToImageFilter
    from vtkmodules.vtkRenderingOpenGL2 import vtkWin32OpenGLRenderWindow
    from vtkmodules.vtkFiltersSources import vtkSphereSource
    from vtkmodules.util.numpy_support import vtk_to_numpy
    app = QApplication([])
    window = vtkWin32OpenGLRenderWindow()
    window.SetMultiSamples(0)
    widget = QVTKRenderWindowInteractor(rw=window)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(160, 120)
    renderer = vtkRenderer()
    renderer.SetBackground(.05, .1, .15)
    window.AddRenderer(renderer)
    sphere = vtkSphereSource()
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(sphere.GetOutputPort())
    actor = vtkActor()
    actor.SetMapper(mapper)
    renderer.AddActor(actor)
    renderer.ResetCamera()
    widget.show()
    app.processEvents()
    widget.Initialize()
    for _ in range(3):
        window.Render()
        app.processEvents()
    capture = vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.Update()
    pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
    if pixels.size == 0 or int(pixels.max()) - int(pixels.min()) < 80:
        raise RuntimeError('OpenGL context did not render the test geometry')
    capabilities = window.ReportCapabilities().split('OpenGL extensions:')[0].strip()
    widget.Finalize()
    widget.close()
    app.processEvents()
    write_json(report, {'ok': True, 'capabilities': capabilities})
    return 0


def recovery_dialog(app, data, status):
    """Keep an actionable Qt-only window alive if every renderer fails."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
    dialog = QDialog()
    dialog.setWindowTitle('Prompt CAD Studio · 그래픽 시작 복구')
    dialog.resize(560, 260)
    layout = QVBoxLayout(dialog)
    label = QLabel('3D 그래픽을 초기화하지 못했습니다. 설계 파일은 변경하지 않았습니다.\n'
                   '진단 폴더의 graphics-status.json과 로그를 확인할 수 있습니다.\n'
                   '다시 시도해도 실패하면 그래픽 드라이버를 확인해 주세요.')
    label.setWordWrap(True)
    layout.addWidget(label)
    retry = QPushButton('그래픽 검사 다시 시도')
    retry.clicked.connect(dialog.accept)
    layout.addWidget(retry)
    logs = QPushButton('진단 폴더 열기')
    logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data))))
    layout.addWidget(logs)
    copy = QPushButton('진단 내용 복사')
    copy.clicked.connect(lambda: app.clipboard().setText(json.dumps(status, ensure_ascii=False, indent=2)))
    layout.addWidget(copy)
    close = QPushButton('닫기')
    close.clicked.connect(dialog.reject)
    layout.addWidget(close)
    return dialog.exec() == QDialog.DialogCode.Accepted
