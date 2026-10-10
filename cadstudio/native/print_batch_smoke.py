"""Owned native print workflow with synthetic CAD and real output files.

The normal MainWindow action opens both dialogs. File-picker return values
are restricted to owned paths; no user project, printer, SDK, or AI is used.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import marshal
import os
from pathlib import Path, PurePosixPath
import sys
import threading
import time
import traceback
from zipfile import ZipFile

from PySide6.QtCore import QEvent, QPoint, QRectF, QThreadPool, QTimer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton, QScrollArea, QToolButton


def fixture():
    import cadquery as cq
    from ..imported import encode_shape
    from ..kernel import KERNEL_LOCK
    from ..models import Design, Part
    with KERNEL_LOCK:
        imported = encode_shape(cq.Workplane('XY').box(60, 60, 4, centered=(True, True, False)).val(), 'synthetic-box.brep')
    rows = [('big-a', '큰 부품 A', 60), ('big-b', '가져온 큰 부품 B', 60),
            ('small-a', '작은 부품 A', 30), ('small-b', '작은 부품 B', 30),
            ('bolt', 'M8 bolt', 10), ('nut', 'M8 nut', 10),
            ('washer', 'M8 washer', 10), ('pin', 'retaining pin', 10)]
    parts = []
    for index, (identifier, name, size) in enumerate(rows):
        geometry = dict(kind='imported', asset_id='synthetic-brep') if identifier == 'big-b' else dict(kind='plate', length=size, width=size, thickness=4, hole_count=0)
        if identifier == 'small-a':
            geometry = dict(kind='extrusion', thickness=12,
                points=[dict(x=x,y=y) for x,y in [(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)]])
        parts.append(Part(id=identifier, name=name, color='#64C4AA' if index < 4 else '#E6C977',
                          mechanical_function='fastener' if index >= 4 else 'unspecified',
                          geometry=geometry, transform=dict(x=index * 100, y=40, z=10, rz=90)))
    return Design(name='Synthetic print batch fixture', parts=parts, assets={'synthetic-brep': imported})


def run(app, window, output):
    from .. import __version__, models, printing
    from . import document as document_module, print_dialog, print_placement
    from .document import Document, read_project
    from .print_dialog import PrintDialog

    supplied = Path(output).absolute()
    if supplied.suffix.lower() != '.json' or any(path.is_symlink() for path in (supplied, *supplied.parents)):
        raise ValueError('A new report inside the owned, non-symlink output directory is required.')
    output = supplied.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(success=False, phase='starting', version=__version__, frozen=bool(getattr(sys, 'frozen', False)),
        runtime_executable=sys.executable, pid=os.getpid(), parent_pid=os.getppid(), started_utc=datetime.now(timezone.utc).isoformat(),
        checks=[], check_count=0, screenshots=[], screenshot_details=[], module_identity={}, output_files=[],
        synthetic_only=True, part_count=8, live_ai_calls=0, hardware_calls=0, sdk_calls=0, network_calls=0,
        generated_code_executed=False, model_refresh_disabled=True,
        scope='Actual MainWindow print action, native controls, VTK picking and drag, real STL and ZIP output. '
              'Eight synthetic bodies include one imported BREP. File-picker results use only owned paths. '
              'An asymmetric native extrusion tests estimated support reduction and bed-contact recommendations. '
              'Name hints are selection aids; no real bolt identity, printer fit, strength, slicing, or hardware qualification.')
    with output.open('x', encoding='utf-8') as stream: json.dump(report, stream, ensure_ascii=False, indent=2)
    dialogs = []; timers = []; errors = []; release_export = threading.Event()
    original_show_error = window.show_error; original_picker = QFileDialog.getSaveFileName
    original_export = print_dialog.export_print_stls; progress = [time.monotonic()]
    original_path = output.with_name(output.stem + '-input.pcad')
    current_stl = output.with_name(output.stem + '-current.stl')
    all_zip = output.with_name(output.stem + '-plates.zip')
    cancel_zip = output.with_name(output.stem + '-cancel-existing.zip')
    validation_dir = output.with_name(output.stem + '-zip-validation')

    def write():
        report['check_count'] = len(report['checks'])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(condition, title, **details):
        report['checks'].append(dict(name=title, passed=bool(condition), **details)); progress[0] = time.monotonic(); write()
        if not condition: raise AssertionError(title)

    def wait(predicate, title, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            if errors: raise AssertionError('\n'.join(errors))
            if time.monotonic() >= deadline: raise TimeoutError(title)
            app.processEvents(); QTest.qWait(10)
        if errors: raise AssertionError('\n'.join(errors))
        progress[0] = time.monotonic()

    def ready(dialog, title, clear=True):
        wait(lambda: dialog.checked is not None and dialog.checked_batch is not None and not dialog.running and not dialog.timer.isActive(), title)
        if clear:
            check(dialog.apply_button.isEnabled() and dialog.current_stl_button.isEnabled(), title + ': both exports are enabled')
            check(not dialog.warnings and not any(r['blocked'] for r in dialog.checked_batch['reports']), title + ': all plates are clear')

    def ensure(dialog, widget):
        for scroll in dialog.findChildren(QScrollArea):
            if scroll.widget() and scroll.widget().isAncestorOf(widget): scroll.ensureWidgetVisible(widget)
        app.processEvents(); QTest.qWait(20)

    def click(dialog, text):
        target = next(w for w in dialog.findChildren(QPushButton) if w.text() == text)
        ensure(dialog, target); check(target.isEnabled() and target.isVisible(), 'Actual native button is available', button=text)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)

    def number(dialog, widget, value):
        ensure(dialog, widget)
        def state():
            return dict(value=widget.value(), text=widget.text(), enabled=widget.isEnabled(), visible=widget.isVisible(),
                focused=widget.hasFocus(), active_window=dialog.isActiveWindow(),
                active_part=dialog.active_part.currentData(), plate=dialog.plate_choice.currentData(),
                revision=dialog.revision, running=dialog.running, timer_active=dialog.timer.isActive())
        trace = dict(requested=value, before=state(), signals=[])
        report.setdefault('numeric_inputs', []).append(trace)
        changed = lambda observed: trace['signals'].append(dict(event='valueChanged', value=observed, text=widget.text()))
        finished = lambda: trace['signals'].append(dict(event='editingFinished', value=widget.value(), text=widget.text()))
        widget.valueChanged.connect(changed); widget.editingFinished.connect(finished)
        try:
            # setFocus on an inactive Windows dialog does not deliver FocusIn.
            # Tab then leaves an uncommitted spin-box edit. Prove focus first;
            # Return is deliberately avoided because it may activate a default button.
            dialog.raise_(); dialog.activateWindow(); widget.setFocus()
            wait(lambda: dialog.isActiveWindow() and widget.hasFocus(), 'Owned numeric control receives actual focus', seconds=3)
            trace['focused'] = state()
            check(widget.isEnabled() and widget.isVisible() and widget.hasFocus(),
                  'Actual numeric control is visible, enabled and focused', value=value, observed=trace['focused'])
            QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier); QTest.keyClicks(widget, str(value))
            trace['typed'] = state(); QTest.keyClick(widget, Qt.Key.Key_Tab); trace['committed'] = state()
            check(widget.value() == value, 'Actual keyboard edit reaches the numeric control', value=value, observed=trace['committed'])
        finally:
            trace['final'] = state(); widget.valueChanged.disconnect(changed); widget.editingFinished.disconnect(finished); write()

    def choose(dialog, combo, value):
        ensure(dialog, combo); index = combo.findData(value)
        check(index >= 0 and combo.isEnabled() and combo.isVisible(), 'Actual combo contains the requested value', value=value)
        combo.setCurrentIndex(index); app.processEvents()

    def settings(dialog):
        toggle = next(w for w in dialog.findChildren(QToolButton) if w.text().endswith('프린터 / 자동 배치 설정'))
        if not toggle.isChecked():
            ensure(dialog, toggle); QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)

    def members(dialog):
        return {p.id for plate in dialog.checked_batch['plates'] for p in plate.parts}

    def metadata(path, kind):
        return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size, kind=kind)

    def shot(dialog, suffix, focus=None):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.util.numpy_support import vtk_to_numpy
        import numpy as np
        if focus is not None: ensure(dialog, focus)
        view = dialog.viewport
        check(view.initialized and not view.closed and view.isVisible(), 'Actual VTK viewport is initialized and visible', capture=suffix)
        app.processEvents(); view.window.Render()
        capture = vtkWindowToImageFilter(); capture.SetInput(view.window); capture.SetInputBufferTypeToRGBA(); capture.ReadFrontBufferOff(); capture.Update()
        pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())[:, :3]
        dimensions = capture.GetOutput().GetDimensions()
        unique = len(np.unique(pixels, axis=0))
        check(dimensions[0] > 100 and dimensions[1] > 100 and unique > 4 and float(pixels.std()) > 2,
              'Genuine VTK framebuffer contains nonblank rendered pixels', capture=suffix, dimensions=list(dimensions), unique_rgb=unique)
        viewport_path = output.with_name(output.stem + '-' + suffix + '-viewport.png')
        ui_path = output.with_name(output.stem + '-' + suffix + '-ui.png')
        check(not viewport_path.exists() and not ui_path.exists(), 'Native capture paths are new', capture=suffix)
        writer = vtkPNGWriter(); writer.SetFileName(str(viewport_path)); writer.SetInputConnection(capture.GetOutputPort()); writer.Write()
        image = QImage(str(viewport_path)); check(not image.isNull(), 'Genuine VTK PNG is readable', capture=suffix)
        pixmap = dialog.grab(); painter = QPainter(pixmap)
        try:
            point = view.widget.mapTo(dialog, QPoint(0, 0))
            painter.drawImage(QRectF(point.x(), point.y(), view.widget.width(), view.widget.height()), image)
        finally: painter.end()
        check(pixmap.save(str(ui_path)), 'Qt controls and genuine VTK composite are saved', capture=suffix)
        for path, kind, width, height in [(viewport_path, 'Actual VTK back framebuffer', image.width(), image.height()),
                                         (ui_path, 'Actual Qt widget capture composited with its genuine VTK framebuffer', pixmap.width(), pixmap.height())]:
            report['screenshots'].append(str(path))
            report['screenshot_details'].append(dict(**metadata(path, kind), width=width, height=height,
                actor_ids=sorted(view.actors), plate_index=dialog.checked_batch['selected'], vtk_framebuffer_sha256=sha256(viewport_path.read_bytes()).hexdigest()))
        write()

    def stl_bounds(path, result, title):
        from vtkmodules.vtkIOGeometry import vtkSTLReader
        reader = vtkSTLReader(); reader.SetFileName(str(path)); reader.Update(); mesh = reader.GetOutput()
        actual = list(mesh.GetBounds()); expected = [v for pair in zip(result['stats']['min'], result['stats']['max']) for v in pair]
        check(mesh.GetNumberOfPoints() > 0 and mesh.GetNumberOfCells() > 0, title + ': genuine STL has vertices and triangles')
        check(max(abs(a - b) for a, b in zip(actual, expected)) < .05 and abs(actual[4]) < 1e-6,
              title + ': STL bounds agree with checked preview and bottom Z=0', actual=actual, expected=expected)
        return dict(**metadata(path, 'Actual exported STL'), bounds=actual, triangles=mesh.GetNumberOfCells())

    def modal(callback, title):
        state = dict(done=False, started=False, error=None); deadline = time.monotonic() + 12
        timer = QTimer(window); timers.append(timer); timer.setInterval(20)
        def handle():
            dialog = QApplication.activeModalWidget()
            if not isinstance(dialog, PrintDialog) or dialog.parentWidget() is not window:
                if time.monotonic() >= deadline:
                    timer.stop(); state.update(done=True, error='Owned PrintDialog did not open: ' + title); errors.append(state['error'])
                return
            if not dialog.isVisible() or state['started']: return
            state['started'] = True; timer.stop(); dialogs.append(dialog)
            try:
                callback(dialog); check(not dialog.alive, title + ': owned dialog is closed')
            except Exception:
                state['error'] = traceback.format_exc(); errors.append(state['error'])
                release_export.set()
                try:
                    if dialog.alive: dialog.reject()
                except RuntimeError: pass
            finally: state['done'] = True
        timer.timeout.connect(handle); timer.start(); window.actions['print_mode'].trigger()
        wait(lambda: state['done'], title)
        if state['error']: raise AssertionError(state['error'])
        wait(lambda: not window.busy, title + ': MainWindow is idle')

    def watchdog_tick():
        if time.monotonic() - progress[0] > 60:
            if not errors: errors.append('Owned printing smoke stopped progressing')
            release_export.set()
            for dialog in dialogs:
                try:
                    if dialog.alive: dialog.reject()
                except RuntimeError: pass
    watchdog = QTimer(window); watchdog.timeout.connect(watchdog_tick); watchdog.start(1000)
    try:
        app.setQuitOnLastWindowClosed(False); window.show_error = lambda message: errors.append(str(message))
        window.completion_notifier.enabled = False; window.resize(1240, 900)
        check(window.document.design is None, 'Private MainWindow starts without a user project')
        profile = output.parent / (output.stem + '-profile')
        check(Path(os.environ['CADSTUDIO_DATA_DIR']).resolve() == profile, 'Entry selected the print-smoke-owned private profile')
        report['private_profile'] = str(profile)
        check(window.language_service.language == 'ko', 'Fresh private print controls use Korean labels')
        for module in (models, printing, document_module, print_dialog, print_placement, sys.modules[__name__]):
            path = Path(module.__file__).resolve()
            report['module_identity'][module.__name__] = dict(path=str(path), file_sha256=sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                loader=type(module.__loader__).__name__, origin=module.__spec__.origin,
                function_code_sha256={name:sha256(marshal.dumps(value.__code__)).hexdigest() for name,value in vars(module).items()
                    if callable(value) and getattr(value,'__module__',None)==module.__name__ and hasattr(value,'__code__')},
                class_method_code_sha256={name:{method:sha256(marshal.dumps(value.__code__)).hexdigest() for method,value in vars(cls).items() if hasattr(value,'__code__')}
                    for name,cls in vars(module).items() if isinstance(cls,type) and cls.__module__==module.__name__})
        check(not any(path.exists() for path in (original_path,current_stl,all_zip,cancel_zip,validation_dir)), 'All synthetic project and output paths are new')
        synthetic = fixture(); document = Document(); document.commit(synthetic, 'Synthetic eight-body print fixture')
        second = synthetic.model_dump(); second['name'] += ' · source history'; document.commit(second, 'Synthetic metadata history entry')
        document.write(original_path); original_bytes = original_path.read_bytes()
        report.update(original_project=str(original_path), original_sha256=sha256(original_bytes).hexdigest(),
                      original_project_sha256=sha256(original_bytes).hexdigest(), phase='native-open')
        write(); window.open_project(original_path)
        wait(lambda: not window.busy and window.document.path == original_path, 'Actual synthetic fixture Open')
        check(window.document.project().model_dump(mode='json') == read_project(original_path).model_dump(mode='json'), 'Actual MainWindow opens the complete synthetic project and history')
        check(len(window.viewport.actors) == 8 and not window.result['stats']['collisions'], 'Eight spaced source bodies have actual actors and no volume overlap')
        check(window.document.design['parts'][1]['geometry']['kind'] == 'imported' and len(window.document.design['assets']) == 1,
              'Synthetic source contains a genuine embedded BREP part')
        baseline = deepcopy(window.document.project().model_dump(mode='json')); history = deepcopy(window.document.journal.data)
        report.update(source_project_fingerprint=sha256(json.dumps(baseline,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest(),
                      source_history_fingerprint=sha256(json.dumps(history,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest(),
                      fingerprint_format='SHA256 of UTF-8 JSON, ensure_ascii=False, sort_keys=True, separators=(comma,colon)')
        check(len(history['entries']) == 2, 'Synthetic fixture contains two real history entries')
        report.update(history_entries=2, original_cursor=history['cursor'], original_head=history['head'])
        window.select_parts(['big-a','big-b']); selection = list(window.selected_ids())
        check(selection == ['big-a','big-b'], 'Actual MainWindow selection contains two desired bodies')

        def exercise(dialog):
            dialog.resize(1240,900); ready(dialog,'Selected-part initial preview')
            check(members(dialog)==set(selection) and not dialog.exclude_fasteners.isChecked(), 'Print action starts with the actual current selection')
            shot(dialog,'selected',dialog.plate_choice)
            click(dialog,'전체 선택'); ready(dialog,'All-part preview'); check(len(members(dialog))==8,'Actual Select all includes all eight source bodies')
            click(dialog,'선택 해제'); wait(lambda:not dialog.running and not dialog.timer.isActive(),'Clear selection validation')
            check(dialog.checked is None and dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(),
                  'Empty selection blocks both native export controls')
            click(dialog,'현재 선택'); ready(dialog,'Restored current selection'); check(members(dialog)==set(selection),'Actual Current selection restores the two desired bodies')
            click(dialog,'전체 선택'); ready(dialog,'All-part restore'); settings(dialog)
            number(dialog,dialog.bed[0],70); number(dialog,dialog.bed[1],70); click(dialog,'전체 자동 배치 / 방향 초기화'); ready(dialog,'Split plate preview')
            check(len(dialog.checked_batch['plates'])>=3 and members(dialog)=={p['id'] for p in baseline['design']['parts']},
                  'Many selected bodies automatically split across multiple plates')
            check(all(abs(r['stats']['min'][2])<1e-6 and not r['stats']['collisions'] for r in dialog.checked_batch['results']),
                  'All checked plates sit at bottom Z=0 without collisions')
            shot(dialog,'split',dialog.plate_choice)
            ensure(dialog,dialog.exclude_fasteners)
            QTest.mouseClick(dialog.exclude_fasteners,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(10,dialog.exclude_fasteners.height()//2))
            check(dialog.exclude_fasteners.isChecked(), 'Actual indicator click enables bolt and nut exclusion')
            check(dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(),
                  'Exclusion change immediately invalidates both export controls')
            ready(dialog,'Bolt and nut exclusion preview')
            check(members(dialog)=={'big-a','big-b','small-a','small-b','washer','pin'}, 'Bolt and nut exclusion preserves washer and pin')
            check('bolt' in dialog.excluded_summary.toolTip() and 'nut' in dialog.excluded_summary.toolTip() and '미검증' in dialog.excluded_summary.text(),
                  'Excluded bodies show IDs and unverified name-hint reasons')
            shot(dialog,'excluded',dialog.exclude_fasteners)
            # Bad print baseline is entered through the actual controls. The
            # assembly transform is intentionally removed by print preparation.
            choose(dialog,dialog.plate_choice,dialog.plate_assignments['small-a'])
            choose(dialog,dialog.active_part,'small-a'); number(dialog,dialog.pose_inputs['rx'],90)
            ready(dialog,'Asymmetric upright print baseline')
            check(dialog.placements['small-a']['rx']==90 and not dialog.orientation_reports,
                  'Automatic orientation starts from an explicit manual overhang baseline')
            click(dialog,'자동 자세·배치 (서포트 최소)')
            check(dialog.auto_requested and dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(),
                  'Automatic orientation immediately invalidates both native export controls')
            ready(dialog,'Automatic support-minimizing orientation preview')
            diagnostic=deepcopy(dialog.orientation_reports['small-a']); recommended=diagnostic['recommended']; baseline_metric=diagnostic['baseline']
            report['orientation_method']=deepcopy(dialog.checked_batch['orientation_recommendation']['method'])
            check(baseline_metric['support_proxy_mm3']>recommended['support_proxy_mm3']+1,
                  'Automatic orientation reduces the asymmetric part support estimate', baseline=baseline_metric, recommended=recommended)
            check(recommended['stable_contact'] and recommended['contact_area_mm2']>0 and recommended['fits_bed'],
                  'Recommended asymmetric orientation has stable bed contact and fits the bed', recommended=recommended)
            check(all(abs(dialog.placements['small-a'][key]-diagnostic['chosen'][key])<1e-6 for key in ('rx','ry','rz')) and not dialog.warnings,
                  'Checked output uses the explicitly recommended rotations and repacked plates')
            check(members(dialog)=={'big-a','big-b','small-a','small-b','washer','pin'} and not {'bolt','nut'}&set(dialog.orientation_reports),
                  'Orientation recommendation honors selection and bolt-nut exclusion')
            details=dialog.orientation_details_button; ensure(dialog,details)
            if not details.isChecked(): QTest.mouseClick(details,Qt.MouseButton.LeftButton)
            check(details.isChecked() and dialog.orientation_metrics['support'].isVisible() and '→' in dialog.orientation_metrics['support'].text()
                  and dialog.orientation_state.text()=='추천 자세 적용',
                  'Native recommendation details expose estimated metrics and recommendation provenance')
            shot(dialog,'automatic-orientation',dialog.orientation_metrics['support'])
            chosen_rz=diagnostic['chosen']['rz']; manual_rz=chosen_rz-180 if chosen_rz>=0 else chosen_rz+180
            number(dialog,dialog.pose_inputs['rz'],manual_rz); ready(dialog,'Manual override after automatic orientation')
            check(dialog.placements['small-a']['rz']==manual_rz and dialog.orientation_reports['small-a']==diagnostic
                  and dialog.orientation_state.text()=='수동 자세 · 자동 추천 이후 변경됨',
                  'Manual rotation overrides automatic recommendation without relabeling previous metrics')
            pose_after_auto=dict(dialog.placements['small-a']); dialog.schedule(); ready(dialog,'Ordinary refresh after manual orientation')
            check(dialog.placements['small-a']==pose_after_auto and dialog.orientation_reports['small-a']==diagnostic,
                  'Ordinary layout refresh preserves the manual orientation without rescanning candidates')
            report['orientation_diagnostics']=deepcopy(dialog.orientation_reports)
            report['orientation_estimated_only']=True
            if details.isChecked(): QTest.mouseClick(details,Qt.MouseButton.LeftButton)
            choose(dialog,dialog.plate_choice,dialog.plate_assignments['big-b'])
            check(set(dialog.viewport.actors)=={p.id for p in dialog.checked.parts}, 'Plate selector renders exactly its checked members')
            choose(dialog,dialog.active_part,'big-b'); number(dialog,dialog.pose_inputs['x'],0)
            check(dialog.checked is None and dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(),
                  'Manual placement immediately blocks both stale export controls')
            number(dialog,dialog.pose_inputs['y'],0); number(dialog,dialog.pose_inputs['rx'],180); ready(dialog,'Individual print orientation preview')
            check(all(dialog.placements['big-b'][key]==value for key,value in {'x':0,'y':0,'rx':180}.items()), 'Per-part position and orientation survive checked preparation')
            dialog.top_plate(); app.processEvents(); view=dialog.viewport; view.window.Render()
            actor=view.actors['big-b'][0]; bounds=actor.GetBounds(); pose=dict(dialog.placements['big-b'])
            view.renderer.SetWorldPoint(pose['x'],pose['y'],bounds[5],1); view.renderer.WorldToDisplay(); point=view.renderer.GetDisplayPoint()
            from vtkmodules.vtkRenderingCore import vtkCellPicker
            picker=vtkCellPicker(); picker.PickFromListOn(); picker.SetTolerance(.003)
            for item,_ in view.actors.values():picker.AddPickList(item)
            check(picker.Pick(point[0],point[1],0,view.renderer) and view.actor_ids.get(picker.GetActor())=='big-b',
                  'Actual VTK ray pick resolves the imported print body')
            ratio=view.widget.devicePixelRatioF(); start=QPoint(round(point[0]/ratio),round((view.window.GetSize()[1]-1-point[1])/ratio)); end=start+QPoint(18,-10)
            QTest.mousePress(view.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
            check(dialog.placement_handle.drag is not None and dialog.placement_handle.drag[0]=='big-b', 'Actual mouse press enters PrintPlacementHandle for the picked body')
            QTest.mouseMove(view.widget,end,30); app.processEvents()
            check(dialog.checked_batch is None and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(), 'Actual drag invalidates both stale export controls')
            QTest.mouseRelease(view.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end); ready(dialog,'Actual drag revalidation')
            check(dialog.placements['big-b']['x']>pose['x'] and dialog.placements['big-b']['y']>pose['y'], 'Actual mouse drag changes world print placement')
            dragged=dict(dialog.placements['big-b']); requested=len(dialog.checked_batch['plates'])
            choose(dialog,dialog.target_plate,requested); ready(dialog,'Explicit new-plate membership preview')
            check(dialog.placements['big-b']==dragged and dialog.checked_batch['selected']==dialog.plate_assignments['big-b'],
                  'Moving a body to a new plate preserves its pose and uses normalized membership')
            shot(dialog,'manual',dialog.pose_inputs['x'])
            checked=dialog.checked_batch; revision=dialog.revision; QFileDialog.getSaveFileName=lambda *_a,**_k:('','')
            click(dialog,'현재 출력판 STL 저장')
            check(dialog.checked_batch is checked and dialog.revision==revision and not dialog.running and not current_stl.exists(),
                  'Save dialog cancellation leaves the checked batch and files unchanged')
            selected_index=checked['selected']; current_result=deepcopy(checked['results'][selected_index])
            QFileDialog.getSaveFileName=lambda *_a,**_k:(str(current_stl),'STL (*.stl)')
            click(dialog,'현재 출력판 STL 저장'); wait(lambda:not dialog.running,'Actual current STL export')
            check(current_stl.is_file() and current_stl.stat().st_size>84, 'Actual single-plate STL export uses current checked plate')
            record=stl_bounds(current_stl,current_result,'Current plate'); record['source_part_ids']=[p.id for p in checked['plates'][selected_index].parts]; report['output_files'].append(record)
            QFileDialog.getSaveFileName=lambda *_a,**_k:(str(all_zip),'ZIP (*.zip)')
            QTest.mouseClick(dialog.apply_button,Qt.MouseButton.LeftButton); wait(lambda:not dialog.running,'Actual all-plate ZIP export')
            check(all_zip.is_file(), 'Actual multi-plate ZIP export uses checked plates')
            check(dialog.status.text()=='STL 저장 완료 · '+str(all_zip), 'Completed batch export displays the selected ZIP path')
            validation_dir.mkdir()
            with ZipFile(all_zip) as archive:
                check(archive.testzip() is None,'Actual ZIP CRCs pass for every generated member')
                names=archive.namelist(); check(all(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts and '\\' not in name for name in names),
                                             'ZIP members use relative portable paths only')
                manifest=json.loads(archive.read('print-index.json')); check(manifest['units']=='mm' and manifest['format']=='stl' and manifest['schema_version']==1 and len(manifest['plates'])==len(checked['plates']),
                                                                         'ZIP index declares mm and every checked plate')
                check(set(names)=={'print-index.json',*(f'plate-{i+1:03d}.stl' for i in range(len(checked['plates'])))},
                      'ZIP contains only the declared plate STLs and portable index')
                exported=set()
                for index,item in enumerate(manifest['plates']):
                    expected_name=f'plate-{index+1:03d}.stl'; check(item['file']==expected_name and item['index']==index,'ZIP index maps the exact checked plate',plate=index)
                    data=archive.read(expected_name); check(sha256(data).hexdigest()==item['sha256'],'ZIP STL bytes match their index hash',plate=index)
                    expected_ids={p.id for p in checked['plates'][index].parts}; ids={v['source_part_id'] for v in item['instances']}
                    check(ids==expected_ids and item['placements']==checked['results'][index]['print_placements'],'ZIP index preserves exact selected IDs and checked placements',plate=index)
                    exported.update(ids); extracted=validation_dir/expected_name
                    with extracted.open('xb') as stream:stream.write(data)
                    report['output_files'].append(stl_bounds(extracted,checked['results'][index],f'ZIP plate {index+1}'))
                check(exported==members(dialog) and not {'bolt','nut'}&exported and {'washer','pin'}<=exported,
                      'All ZIP source IDs exactly match the checked filtered batch')
            report['output_files'].append(metadata(all_zip,'Actual atomic multi-plate ZIP')); report['export_manifest']=manifest
            settings(dialog); number(dialog,dialog.bed[0],45); click(dialog,'전체 자동 배치 / 방향 초기화'); ready(dialog,'Oversized body preview',clear=False)
            oversized=dialog.plate_assignments['big-b']; choose(dialog,dialog.plate_choice,oversized)
            check(dialog.warnings and not dialog.apply_button.isEnabled() and not dialog.current_stl_button.isEnabled(), 'Oversized individual part blocks export')
            check('자르지' in dialog.status.text() and 'big-b' in members(dialog), 'Oversized body remains intact with an explicit no-slicing warning')
            shot(dialog,'oversized',dialog.plate_choice)
            clear_index=next(i for i,result in enumerate(dialog.checked_batch['results']) if not result['print_warnings'])
            choose(dialog,dialog.plate_choice,clear_index)
            check(dialog.current_stl_button.isEnabled() and not dialog.apply_button.isEnabled(), 'A clear current plate remains exportable while another plate is oversized')
            click(dialog,'취소')

        report['phase']='native-print-workflow';write();modal(exercise,'Actual selected-parts print workflow')
        check(window.document.project().model_dump(mode='json')==baseline and window.document.journal.data==history,
              'Print cancellation preserves source design and complete history')
        check(window.selected_ids()==selection and original_path.read_bytes()==original_bytes, 'Print workflow preserves original selection and fixture bytes')
        QFileDialog.getSaveFileName=original_picker

        def cancel_export(dialog):
            dialog.resize(1240,900);ready(dialog,'Export-cancel initial preview');click(dialog,'전체 선택');ready(dialog,'Export-cancel all-part preview')
            settings(dialog);number(dialog,dialog.bed[0],70);number(dialog,dialog.bed[1],70);click(dialog,'전체 자동 배치 / 방향 초기화');ready(dialog,'Export-cancel split preview')
            with cancel_zip.open('xb') as stream:stream.write(b'previous-owned-output')
            previous=cancel_zip.read_bytes(); entered=threading.Event(); calls=[0]; captured=[]
            scratch_before={p.resolve() for p in output.parent.glob('promptcad-print-*')}
            def hold_after_mesh(*args,**kwargs):
                cancelled=kwargs['cancelled']
                def checkpoint():
                    calls[0]+=1
                    if calls[0]==3:
                        for folder in output.parent.glob('promptcad-print-*'):
                            if folder.resolve() not in scratch_before:
                                for path in folder.glob('plate-*.stl'):
                                    captured.append(metadata(path,'Real first-plate mesh at bounded cancellation checkpoint'))
                        entered.set()
                        if not release_export.wait(12):raise TimeoutError('Owned export cancellation checkpoint')
                    return cancelled()
                return original_export(*args,**{**kwargs,'cancelled':checkpoint})
            print_dialog.export_print_stls=hold_after_mesh;QFileDialog.getSaveFileName=lambda *_a,**_k:(str(cancel_zip),'ZIP (*.zip)')
            try:
                QTest.mouseClick(dialog.apply_button,Qt.MouseButton.LeftButton);wait(entered.is_set,'Actual first plate tessellation checkpoint')
                check(captured and captured[0]['bytes']>84,'Cancellation checkpoint follows a genuine plate STL tessellation')
                click(dialog,'취소');release_export.set();wait(lambda:not dialog.running,'Owned canceled export worker settles')
                check(cancel_zip.read_bytes()==previous,'Cancel during actual meshing preserves the prior output ZIP')
                check(not list(output.parent.glob(cancel_zip.name+'.*.tmp')) and not [p for p in output.parent.glob('promptcad-print-*') if p.resolve() not in scratch_before],
                      'Canceled export removes only its temporary ZIP and scratch meshes')
                report['export_cancellation']=dict(checkpoint_calls=calls[0],observed_meshes=captured,prior_and_final_sha256=sha256(previous).hexdigest(),
                    scope='A bounded QA callback pauses after genuine first-plate tessellation; normal dialog Cancel triggers the unchanged core cancellation check.')
                report['output_files'].append(metadata(cancel_zip,'Preserved owned prior output; canceled export did not replace it'))
            finally:
                release_export.set();print_dialog.export_print_stls=original_export;QFileDialog.getSaveFileName=original_picker
        report['phase']='actual-export-cancellation';write();modal(cancel_export,'Actual export cancellation')
        check(window.document.project().model_dump(mode='json')==baseline and window.document.journal.data==history and window.selected_ids()==selection,
              'Export cancellation preserves the complete source project, history and selection')
        check(original_path.read_bytes()==original_bytes,'Final synthetic source project bytes are unchanged')
        report['original_full_project_and_history_preserved']=True
        check(not errors,'Owned native printing actions produced no application errors')
        report.update(success=True,phase='complete')
    except Exception:
        report.update(success=False,phase='failed',error=traceback.format_exc())
    finally:
        release_export.set();watchdog.stop()
        for timer in timers:timer.stop()
        QFileDialog.getSaveFileName=original_picker;print_dialog.export_print_stls=original_export
        for dialog in reversed(dialogs):
            try:
                if dialog.alive:dialog.reject()
            except RuntimeError:pass
        drained=QThreadPool.globalInstance().waitForDone(10000);app.processEvents();report['owned_workers_drained']=bool(drained)
        if not drained or window.busy:report.update(success=False,phase='cleanup-failed',cleanup_error='Owned preview or export workers did not drain')
        for dialog in reversed(dialogs):
            try:dialog.deleteLater()
            except RuntimeError:pass
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        window.show_error=original_show_error;window.document.dirty=False;window.close();app.processEvents()
        report['owned_window_closed']=not window.isVisible()
        if not report['owned_window_closed']:report.update(success=False,phase='cleanup-failed',cleanup_error='Owned MainWindow refused closure')
        report['finished_utc']=datetime.now(timezone.utc).isoformat();write();app.exit(0 if report['success'] else 1)
