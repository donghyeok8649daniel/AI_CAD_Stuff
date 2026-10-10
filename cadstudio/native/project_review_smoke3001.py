"""Review one exact, smoke-owned project copy through a normal private window.

This module creates no source project, generates no code, runs no SDK/compiler,
and never reads the research original. The launcher supplies an unchanged copy.
Only the new owned round-trip file and review receipts may be written.
"""
from copy import deepcopy
from datetime import datetime, timezone
import faulthandler
from functools import wraps
from hashlib import sha256
import json
import marshal
import os
from pathlib import Path
import sys
import threading
import time
import traceback

from PySide6.QtCore import QPointF, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton

from ..stack_observer import StackObserver


INPUT_SHA256 = '0bea836bc8e517997e1c617ef4187c06bcb78fa2723844bae3d2071e1885b2d5'
INPUT_BYTES = 13821761
NEW_PINS = ('PA11', 'PA12', 'PB10', 'PB11', 'PB12', 'PB8', 'PB9', 'PC6',
            'PA8', 'PA9', 'PC0', 'PC1', 'PC2', 'PC3', 'PB0', 'PB1')
LEGACY_PINS = ('PA5', 'PA6', 'PA7', 'PB6', 'PC7', 'PB5')


def _no_reparse(path):
    """Check original path components before resolving Windows junctions."""
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Symlink is not an owned review path: ' + str(item))
        if item.exists() and getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse point is not an owned review path: ' + str(item))
    return path.resolve()


def _owned(path, root):
    resolved = _no_reparse(path)
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError('Review file must stay inside the owned output parent')
    return resolved


def _file_identity(path):
    data = Path(path).read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=sha256(data).hexdigest())


def _runtime_observation():
    """Read only this QA process; no process inventory or third-party imports."""
    observation = dict(pid=os.getpid(), parent_pid=os.getppid(),
        observed_utc=datetime.now(timezone.utc).isoformat(),
        qt_threadpool_active=QThreadPool.globalInstance().activeThreadCount(),
        python_threads=[dict(name=thread.name, ident=thread.ident,
                            native_id=thread.native_id) for thread in threading.enumerate()])
    try:
        if os.name != 'nt':
            observation['memory_unavailable'] = 'Windows process counters only'
            return observation
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                *[(key, ctypes.c_size_t) for key in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]]
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        observation['memory'] = dict(working_set_bytes=counters.WorkingSetSize,
            peak_working_set_bytes=counters.PeakWorkingSetSize, private_commit_bytes=counters.PrivateUsage,
            page_file_bytes=counters.PagefileUsage, peak_page_file_bytes=counters.PeakPagefileUsage)
    except Exception:
        observation['memory_error'] = traceback.format_exc()
    return observation


class _ReviewDiagnostics:
    """Temporary QA wrappers, preserving arguments, results and exceptions."""
    MAX_TIMINGS = 4096

    def __init__(self, report, output, root, lock):
        self.report, self.output, self.root, self.lock = report, output, root, lock
        self.started = time.monotonic()
        self.patches, self.active = [], {}
        self.sequence, self.closed = 0, False
        self.trace_path = _owned(output.with_name(output.stem + '-stages.jsonl'), root)
        self.stack_path = _owned(output.with_name(output.stem + '-stacks.txt'), root)
        if self.trace_path.exists() or self.stack_path.exists():
            raise ValueError('Preserve existing diagnostic files; no overwrite')
        self.fatal_previously_enabled = faulthandler.is_enabled()
        if not self.fatal_previously_enabled:
            raise RuntimeError('Normal native fatal handler must be active before QA')
        self.fatal_changed = False
        self.trace = self.trace_path.open('x', encoding='utf-8')
        report.update(stage_timings=[], stage_summary={}, active_stages={}, stage_timings_omitted=0)
        report['diagnostics'] = dict(timing_events=str(self.trace_path), thread_stacks=str(self.stack_path),
            stack_interval_seconds=60, stack_mode='python-source-free',
            maximum_recorded_timings=self.MAX_TIMINGS,
            note='QA wrappers only. Nested wall times overlap; instrumentation adds overhead. This single run is not a benchmark or a product fix.')
        # Retain the normal entry's fatal handler and unknown descriptor. A
        # Python observer owns its separate file; no native periodic stackwalk.
        report['diagnostics'].update(fatal_handler_previously_enabled=self.fatal_previously_enabled,
            fatal_handler_enabled=faulthandler.is_enabled(), fatal_handler_changed=self.fatal_changed,
            fatal_handler_destination='Existing entry handler retained; owned profile/native-desktop.log',
            native_entry_fatal_log=str(_owned(root / (output.stem + '-profile') / 'native-desktop.log', root)),
            memory_scope='Current QA process only; Python registry may retain dummy thread entries, so it is not a native live-thread inventory.')
        self.observer = StackObserver(self.stack_path, shared_lock=self.lock, interval=60)
        try:
            self.observer.start()
        except BaseException:
            self.trace.close()
            raise

    def event(self, kind, row):
        self.trace.write(json.dumps(dict(event=kind, **row), ensure_ascii=False, separators=(',', ':')) + '\n')
        self.trace.flush()

    def patch(self, owner, name, stage):
        original = getattr(owner, name)
        timed = self.wrap(original, stage)
        setattr(owner, name, timed)
        self.patches.append((owner, name, original, timed))
        return timed

    def call(self, stage, callback, detail=None):
        return self.wrap(callback, stage, detail)()

    def wrap(self, original, stage, detail=None):
        if not callable(original):
            raise TypeError('Diagnostic target is not callable: ' + stage)

        @wraps(original)
        def timed(*args, **kwargs):
            thread_id = threading.get_ident()
            with self.lock:
                if self.closed:
                    row = None
                else:
                    self.sequence += 1
                    identifier = self.sequence
                    parent = self.active.get(thread_id, [])
                    row = dict(id=identifier, stage=stage, parent_id=parent[-1] if parent else None,
                        thread_id=thread_id, thread_name=threading.current_thread().name,
                        started_utc=datetime.now(timezone.utc).isoformat(),
                        start_elapsed_seconds=time.monotonic() - self.started, status='running')
                    if stage == 'kernel.local_shape' and len(args) > 1:
                        row['part_id'] = getattr(args[1], 'id', None)
                    else:
                        row['runtime_start'] = _runtime_observation()
                    if detail is not None:
                        row['detail'] = detail
                    recorded = len(self.report['stage_timings']) < self.MAX_TIMINGS
                    if recorded:
                        self.report['stage_timings'].append(row)
                        self.event('start', row)
                    else:
                        self.report['stage_timings_omitted'] += 1
                    self.active.setdefault(thread_id, []).append(identifier)
                    self.report['active_stages'][str(identifier)] = dict(row)
            if row is None:
                return original(*args, **kwargs)
            began = time.monotonic()
            failure = None
            try:
                return original(*args, **kwargs)
            except BaseException as exc:
                failure = type(exc).__name__
                raise
            finally:
                seconds = time.monotonic() - began
                with self.lock:
                    if not self.closed:
                        row.update(status='failed' if failure else 'complete', seconds=seconds,
                            finished_utc=datetime.now(timezone.utc).isoformat())
                        if failure:
                            row['exception_type'] = failure
                        if stage != 'kernel.local_shape':
                            row['runtime_end'] = _runtime_observation()
                        self.report['active_stages'].pop(str(identifier), None)
                        self.active[thread_id].remove(identifier)
                        if not self.active[thread_id]:
                            self.active.pop(thread_id)
                        summary = self.report['stage_summary'].setdefault(stage,
                            dict(calls=0, failures=0, total_seconds=0.0, max_seconds=0.0))
                        summary['calls'] += 1
                        summary['failures'] += bool(failure)
                        summary['total_seconds'] += seconds
                        summary['max_seconds'] = max(summary['max_seconds'], seconds)
                        if recorded:
                            self.event('end', row)
        return timed

    def finish(self):
        with self.lock:
            self.closed = True
        failure = None
        try:
            cleanup = self.observer.stop(join_timeout=10)
            if not cleanup['success']:
                raise RuntimeError('Owned stack observation was incomplete')
        except Exception as exc:
            failure = exc
        # Joining under the shared writer lock would deadlock a pending sample.
        # On a failed join the observer retains its file until this process exits.
        with self.lock:
            self.report['diagnostics']['stack_observer_cleanup'] = self.observer.status()
            self.report['diagnostics']['fatal_handler_retained'] = faulthandler.is_enabled()
            self.report['diagnostics']['fatal_handler_restored'] = (
                faulthandler.is_enabled() == self.fatal_previously_enabled)
            for owner, name, original, timed in reversed(self.patches):
                if getattr(owner, name) is timed:
                    setattr(owner, name, original)
            self.trace.close()
            self.report['diagnostics']['timing_events_identity'] = _file_identity(self.trace_path)
            if self.observer.status()['cleaned']:
                self.report['diagnostics']['thread_stacks_identity'] = _file_identity(self.stack_path)
            self.report['diagnostics']['wrappers_restored'] = all(
                getattr(owner, name) is original for owner, name, original, _ in self.patches)
        if failure is not None:
            raise failure


def run(app, window, input_path, output):
    from .. import __version__, board_pins, circuit_connections, electrical, mcu_connections
    from ..electrical import ElectricalWorkspace
    from ..firmware_bundle import bundle_source_files, verify_bundle_binding
    from . import document, firmware_dialog, mcu_pin_dialog
    from .bom_design_dialog import BomDesignDialog
    from .document import read_project
    from .firmware_dialog import FirmwareDialog
    from .mcu_pin_dialog import McuPinDialog

    # Establish the receipt's safe destination before allowing any file write.
    output = _no_reparse(output)
    root = _no_reparse(output.parent)
    if root.name != 'fatigue-renewal-exe-review3001' or not root.is_dir():
        raise ValueError('Launcher must create the designated owned review folder')
    output = _owned(output, root)
    if output.exists():
        raise ValueError('A review receipt already exists; no automatic repeat')
    saved = _owned(output.with_name(output.stem + '-roundtrip.pcad'), root)
    if saved.exists():
        raise ValueError('Owned round-trip file already exists; no overwrite')
    report = dict(success=False, phase='starting', version=__version__,
        frozen=bool(getattr(sys, 'frozen', False)), runtime_executable=sys.executable,
        runtime_pid=os.getpid(), runtime_parent_pid=os.getppid(),
        started_utc=datetime.now(timezone.utc).isoformat(), checks=[], findings=[],
        screenshots=[], module_identity={}, actual_Open_count=0, Save_As_count=0,
        live_ai_calls=0, network_calls=0, hardware_calls=0, SDK_checks=0,
        generation_calls=0, generated_code_executed=False, original_project_reads=0,
        user_file_writes=0, owned_profile_autosave_possible=True,
        scope='Exact owned-copy load, cancel-only native reviews, separate Save As and reopen. No strength, electronic operation, firmware build, solver modification or hardware certification.',
        qt_capture_limit='Qt widget grabs may show a black WGL viewport. The independent VTK capture is the actual full unmodified framebuffer.')
    errors, dialogs = [], []
    original_show_error = window.show_error
    input_path_checked = None
    input_identity = None
    close_started = False
    report_lock = threading.RLock()
    diagnostics = None
    diagnostic_timer = None

    def write():
        with report_lock:
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(value, title):
        if not value:
            raise AssertionError(title)
        report['checks'].append(title)
        write()

    def condition(value, title):
        if value:
            report['checks'].append(title)
        else:
            report['findings'].append(title)
        write()

    def wait(predicate, title, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate():
            app.processEvents()
            QTest.qWait(10)
            if errors:
                raise AssertionError(errors[-1])
            if time.monotonic() >= deadline:
                raise TimeoutError(title)
        app.processEvents()
        if errors:
            raise AssertionError(errors[-1])

    def shot(widget, name):
        target = _owned(output.with_name(output.stem + '-' + name + '.png'), root)
        check(not target.exists(), 'New owned screenshot destination: ' + name)
        check(widget.grab().save(str(target)), 'Actual native screenshot: ' + name)
        report['screenshots'].append({**_file_identity(target), 'capture': 'Qt widget grab'})
        write()

    def framebuffer(name):
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.util.numpy_support import vtk_to_numpy
        view = window.viewport
        wait(lambda: view.initialized, 'Owned VTK viewport initialization')
        view.window.Render()
        capture = vtkWindowToImageFilter()
        capture.SetInput(view.window)
        capture.ReadFrontBufferOff()
        capture.Update()
        pixels = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
        target = _owned(output.with_name(output.stem + '-' + name + '.png'), root)
        check(not target.exists(), 'New owned VTK screenshot destination')
        writer = vtkPNGWriter()
        writer.SetInputConnection(capture.GetOutputPort())
        writer.SetFileName(str(target))
        writer.Write()
        check(target.is_file() and pixels.size and int(pixels.max()) - int(pixels.min()) > 80,
              'Actual unmodified full VTK framebuffer has rendered pixel variation')
        report['screenshots'].append({**_file_identity(target), 'capture': 'VTK framebuffer',
            'dimensions': list(capture.GetOutput().GetDimensions()),
            'visible_actors': sum(actor[0].GetVisibility() for actor in view.actors.values()),
            'whole_unmodified_framebuffer': True})
        write()

    def unchanged(title):
        report['phase'] = 'comparing-full-typed-project'
        report['comparison_label'] = title
        write()
        def compare():
            return window.document.project().model_dump(mode='json') == baseline
        same = diagnostics.call('review.full_typed_project_comparison', compare, dict(label=title))
        check(same,
              title + ': full typed Project, attachments and327-entry history preserved')
        check(not window.document.dirty, title + ': document is clean')
        check(_file_identity(input_path_checked) == input_identity,
              title + ': owned input bytes unchanged')

    def modal(expected, callback, action):
        state = {'done': False}
        deadline = time.monotonic() + 20

        def parent_chain(child):
            chain = []
            current = child
            seen = set()
            while current is not None and id(current) not in seen and len(chain) < 32:
                seen.add(id(current))
                chain.append(type(current).__name__)
                if current is window:
                    return True, chain
                current = current.parentWidget()
            return False, chain

        def describe_widget(child):
            if child is None:
                return None
            owned, chain = parent_chain(child)
            return dict(type=type(child).__name__, visible=child.isVisible(),
                        owned_by_parent_widget_chain=owned, parent_widget_chain=chain)

        def owned_dialogs():
            widgets = [*QApplication.topLevelWidgets(), *window.findChildren(QDialog)]
            active = QApplication.activeModalWidget()
            if active is not None:
                widgets.append(active)
            unique = {}
            for child in widgets:
                if isinstance(child, QDialog) and parent_chain(child)[0]:
                    unique[id(child)] = child
            return list(unique.values())

        receipt = dict(expected_type=expected.__name__, state='waiting',
                       ownership='Actual Qt parentWidget chain to this private MainWindow')
        report.setdefault('modal_diagnostics', []).append(receipt)
        report['phase'] = 'reviewing-' + expected.__name__
        write()
        watchdog = QTimer(window)
        watchdog.setInterval(20)

        def handle():
            if state['done']:
                return
            candidates = owned_dialogs()
            matches = [child for child in candidates if isinstance(child, expected) and child.isVisible()]
            # Qt top-level dialogs can have a parentWidget while isAncestorOf is
            # false. Visibility and the actual parent chain bind this QA action.
            if len(matches) != 1:
                if not matches and time.monotonic() < deadline:
                    return
                watchdog.stop()
                receipt.update(state='failed', active_modal=describe_widget(QApplication.activeModalWidget()),
                               owned_dialogs=[describe_widget(child) for child in candidates])
                errors.append('Expected one visible owned modal: ' + expected.__name__)
                state['done'] = True
                # Unwind this action's nested exec even when activeModalWidget
                # does not identify it. Never reject a dialog outside the chain.
                for child in candidates:
                    child.reject()
                write()
                return
            watchdog.stop()
            child = matches[0]
            receipt.update(state='callback', selected=describe_widget(child),
                           active_modal=describe_widget(QApplication.activeModalWidget()))
            write()
            dialogs.append(child)
            try:
                callback(child)
                receipt['state'] = 'complete'
            except Exception:
                receipt['state'] = 'callback-failed'
                errors.append(traceback.format_exc())
                try:
                    shot(child, 'failed-' + expected.__name__)
                except Exception:
                    pass
                child.reject()
            finally:
                state['done'] = True
                write()

        watchdog.timeout.connect(handle)
        watchdog.start()
        try:
            action.trigger()
        finally:
            watchdog.stop()
            watchdog.deleteLater()
        wait(lambda: state['done'], 'Owned modal callback completion')

    def inspect_mcu(dialog):
        choice = dialog.mcu_combo.findData(board.id)
        check(choice >= 0, 'Actual MCU dropdown contains the registered selected G474')
        dialog.mcu_combo.setCurrentIndex(choice)
        app.processEvents()
        check(dialog.current_mcu().id == board.id,
              'Actual MCU dropdown selects the exact registered CAD board')
        check(dialog.current_mcu().part_id == board.part_id and dialog.current_mcu().part_registration,
              'MCU modal retains physical CAD-part registration')
        check(dialog.pin_table.rowCount() == 32 and set(NEW_PINS) <= set(dialog.pin_view.pin_items),
              'Actual G474 table and diagram contain all32 documented rows')
        report['pin_clicks'] = []
        for key in NEW_PINS:
            row = next(i for i, pin in enumerate(dialog.connections) if pin.key == key)
            pin = dialog.connections[row]
            check(not pin.legacy and pin.node == board.signal_pins[key],
                  'Saved canonical pin/net is retained: ' + key)
            branch_ids = {wire.id for wire in wires if any(
                end.component_id == board.id and end.terminal == 'pin:' + key
                for end in wire.wire_endpoints)}
            check(branch_ids and any(target.component_id in branch_ids for target in pin.targets),
                  'Pin resolves the actual saved physical wire endpoint: ' + key)
            dialog.pin_table.scrollToItem(dialog.pin_table.item(row, 0))
            app.processEvents()
            rect = dialog.pin_table.visualItemRect(dialog.pin_table.item(row, 0))
            check(rect.isValid(), 'Actual table row is visible: ' + key)
            QTest.mouseClick(dialog.pin_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            app.processEvents()
            check(dialog.selected_pin == key and dialog.pin_table.currentRow() == row,
                  'Actual table click selects canonical GPIO: ' + key)
            dialog.pin_view.fit()
            app.processEvents()
            QTest.qWait(20)
            point = dialog.pin_view.mapFromScene(QPointF(*dialog.pin_view.pin_positions[key]))
            hits = dialog.pin_view.items(point)
            hit_keys = [item.data(0) for item in hits]
            check(dialog.pin_view.viewport().rect().contains(point) and any(item.data(0) == key for item in hits),
                  'Actual rendered centre contains requested pin item: ' + key)
            QTest.mouseClick(dialog.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
            app.processEvents()
            check(dialog.selected_pin == key and dialog.pin_table.currentRow() == row,
                  'Actual diagram centre click selects canonical GPIO: ' + key)
            check('CN' in dialog.pin_table.item(row, 0).text(), 'Native connector label is visible: ' + key)
            report['pin_clicks'].append(dict(pin=key, node=pin.node, table_row=row,
                viewport_x=point.x(), viewport_y=point.y(), physical_wire_ids=sorted(branch_ids),
                centre_hit_item_keys=hit_keys))
        for key, tokens in (('PC0', ('SB36', 'SB37')), ('PC1', ('SB35', 'SB34')),
                            ('PB8', ('BOOT0', 'JP7', 'SB4')),
                            ('PA9', ('PB6', 'PWR_CR3.UCPD1_DBDIS=1')),
                            ('PB6', ('PA9', 'PWR_CR3.UCPD1_DBDIS=1'))):
            dialog.select_pin(key)
            app.processEvents()
            visible = dialog.pin_caption.text()
            check(all(token in visible for token in tokens),
                  'Actual selected-pin caption shows bridge/chip condition: ' + key)
            report.setdefault('visible_pin_conditions', {})[key] = visible
            shot(dialog, 'g474-condition-' + key)
        protected = next(pin for pin in dialog.connections if pin.kind != 'signal')
        dialog.select_pin(protected.key)
        check(not dialog.connect_button.isEnabled() and not dialog.node_button.isEnabled(),
              'Native supply/reset/reference row remains protected from GPIO assignment')
        check(dialog.workspace.model_dump(mode='json') == workspace.model_dump(mode='json'),
              'All MCU review interactions leave private workspace unchanged')
        button = next(button for button in dialog.findChildren(QPushButton)
                      if button.isVisible() and button.text() in ('취소', 'Cancel'))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    def inspect_bom(dialog):
        check(dialog.document is not None and dialog.table.rowCount() == len(design.bom.items),
              'Actual BOM modal displays the loaded project BOM')
        check(dialog.document.model_dump(mode='json') == design.bom.model_dump(mode='json'),
              'BOM review starts from the exact stored source document')
        report['bom'] = dict(document_id=design.bom.id, rows=len(design.bom.items),
            CAD_parts=len(design.parts), bound_parts=len([part for part in design.parts if part.bom]),
            items=[dict(id=item.id, name=item.name, quantity=item.quantity, model=item.model,
                        dimensions_mm=item.dimensions_mm, issues=list(item.issues))
                   for item in dialog.document.items],
            main_window_status=window.bom_status.text(),
            main_window_details=window.bom_status.toolTip(),
            scope='Bindings and stored/visible unresolved inputs; not manufacturer geometry, strength or purchased-part certification')
        unresolved = [i for i, item in enumerate(dialog.document.items) if item.issues or
                      item.quantity is None or not item.model or not item.dimensions_mm]
        report['bom']['visible_unresolved_row_indices'] = unresolved
        condition(report['bom']['bound_parts'] == 146, 'All146CAD parts have explicit BOM bindings')
        selected = unresolved[0] if unresolved else 0
        if dialog.table.rowCount():
            dialog.table.selectRow(selected)
            dialog.table.scrollToItem(dialog.table.item(selected, 0))
            app.processEvents()
            report['bom']['selected_pending_text'] = dialog.pending.toPlainText()
            report['bom']['selected_source_text'] = dialog.source_details.toPlainText()
        shot(dialog, 'bom-unresolved-review')
        dialog.details.setCurrentWidget(dialog.source_details)
        app.processEvents()
        shot(dialog, 'bom-source-details')
        QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)

    def inspect_firmware(dialog):
        check(dialog.task is None, 'Opening native firmware review starts no worker or generation')
        check(dialog.workspace.model_dump(mode='json') == workspace.model_dump(mode='json'),
              'Firmware modal uses exact copied loaded workspace')
        for bundle in workspace.firmware_bundles:
            index = dialog.board.findData(bundle.binding.board_component_id)
            check(index >= 0, 'Native firmware board selector contains saved bundle board: ' + bundle.id)
            dialog.board.setCurrentIndex(index)
            saved_index = dialog.saved_bundles.findData(bundle.id)
            check(saved_index >= 0, 'Native saved-code selector contains stored bundle: ' + bundle.id)
            dialog.saved_bundles.setCurrentIndex(saved_index)
            app.processEvents()
            check(dialog.bundle.id == bundle.id and dialog.bundle.model_dump(mode='json') == bundle.model_dump(mode='json'),
                  'Native firmware preview loads the complete stored bundle: ' + bundle.id)
            expected_files = {file.path: file for file in bundle.files}
            check(len(dialog._editors) == len(expected_files), 'Native source preview includes every saved file: ' + bundle.id)
            for i, (path, editor, role) in enumerate(dialog._editors):
                file = expected_files[path]
                dialog.files.setCurrentIndex(i)
                app.processEvents()
                check(editor.toPlainText() == file.content and role == file.role,
                      'Native source preview preserves file bytes and role: ' + bundle.id + '/' + path)
            check(dialog._libraries == bundle.libraries and dialog.libraries_table.rowCount() == len(bundle.libraries),
                  'Native library preview retains exact saved snapshots: ' + bundle.id)
            for row, library in enumerate(bundle.libraries):
                dialog.libraries_table.selectRow(row)
                app.processEvents()
                check(dialog.library_files.count() == len(library.files), 'Native library lists every saved file: ' + library.id)
                for file in library.files:
                    index = dialog.library_files.findData(file.path)
                    check(index >= 0, 'Native library file selector retains path: ' + file.path)
                    dialog.library_files.setCurrentIndex(index)
                    app.processEvents()
                    check(dialog.library_source.toPlainText() == file.content,
                          'Native library preview preserves stored bytes: ' + library.id + '/' + file.path)
            for tab, suffix in ((0, 'source'), (1, 'pins'), (2, 'libraries'), (3, 'binding-review')):
                dialog.tabs.setCurrentIndex(tab)
                app.processEvents()
                shot(dialog, 'firmware-' + bundle.id + '-' + suffix)
            report.setdefault('firmware_visible_reviews', {})[bundle.id] = dialog.details.toPlainText()
            check(verify_bundle_binding(bundle, workspace).status in dialog.details.toPlainText(),
                  'Native firmware details show actual binding status: ' + bundle.id)
        check(dialog.task is None and dialog.accepted_workspace is None,
              'Preview-only native firmware review performs no save, SDK check or generation')
        dialog.reject()

    try:
        app.setQuitOnLastWindowClosed(False)
        window.show_error = lambda message: errors.append(str(message))
        window.completion_notifier.enabled = False
        profile = _no_reparse(root / (output.stem + '-profile'))
        check(_no_reparse(os.environ['CADSTUDIO_DATA_DIR']) == profile,
              'Actual window uses the forced private owned review profile')
        report['private_profile'] = str(profile)
        check(window.document.design is None and not window.busy, 'Normal private window starts without a user project')
        report['execution_kind'] = 'packaged frozen executable' if report['frozen'] else 'source QA runtime'
        report['runtime_node_limit'] = electrical.MAX_ELECTRICAL_NODES
        check(electrical.MAX_ELECTRICAL_NODES == circuit_connections.MAX_ELECTRICAL_NODES == mcu_connections.MAX_ELECTRICAL_NODES == 512,
              'Actual loaded schema and both editing gates share512node capacity')
        for module in (electrical, circuit_connections, mcu_connections, board_pins,
                       document, firmware_dialog, mcu_pin_dialog, sys.modules[__name__]):
            source = Path(module.__file__)
            report['module_identity'][module.__name__] = dict(path=str(source),
                file_sha256=sha256(source.read_bytes()).hexdigest() if source.is_file() else None,
                loader=type(module.__loader__).__name__, origin=module.__spec__.origin,
                function_code_sha256={name: sha256(marshal.dumps(value.__code__)).hexdigest()
                    for name, value in vars(module).items() if callable(value)
                    and getattr(value, '__module__', None) == module.__name__ and hasattr(value, '__code__')})
        from .. import interference, joint_readiness, kernel
        from . import window as window_module
        diagnostics = _ReviewDiagnostics(report, output, root, report_lock)
        read_project = diagnostics.patch(document, 'read_project', 'document.read_project')
        diagnostics.patch(window_module, 'read_project', 'native.open.read_project')
        diagnostics.patch(kernel, 'preview', 'kernel.preview')
        diagnostics.patch(window_module, 'preview', 'native.open.preview')
        diagnostics.patch(kernel, 'build', 'kernel.build')
        diagnostics.patch(kernel, 'local_shape', 'kernel.local_shape')
        diagnostics.patch(interference, 'exact_collisions', 'kernel.exact_collisions')
        diagnostics.patch(joint_readiness, 'joint_readiness', 'kernel.joint_readiness')
        diagnostics.patch(document.Document, 'load', 'document.load')
        diagnostics.patch(document.Document, 'project', 'document.project')
        diagnostics.patch(document.Document, 'write', 'document.write')
        diagnostics.patch(window.viewport, 'load', 'viewport.load')
        diagnostics.patch(window.viewport.joints, 'set_design', 'viewport.joints.set_design')
        for name in ('rebuild_tree', 'rebuild_timeline', 'show_properties'):
            diagnostics.patch(window, name, 'native.' + name)
        diagnostic_timer = QTimer(window)
        diagnostic_timer.timeout.connect(write)
        diagnostic_timer.start(15000)
        write()
        input_path_checked = _owned(input_path, root)
        check(input_path_checked.is_file() and input_path_checked not in (output, saved),
              'Input is an existing separate file inside the owned review folder')
        input_identity = _file_identity(input_path_checked)
        report['owned_input'] = input_identity
        check(input_identity['sha256'] == INPUT_SHA256 and input_identity['bytes'] == INPUT_BYTES,
              'Owned input is the exact unchanged requested project copy')
        typed = read_project(input_path_checked)
        baseline = deepcopy(typed.model_dump(mode='json'))
        design = typed.design
        workspace = ElectricalWorkspace.model_validate(design.electrical)
        wires = [component for component in workspace.components if component.kind == 'wire']
        counts = dict(history=len(typed.history.entries) if typed.history else 0,
            parts=len(design.parts), nodes=len(workspace.nodes), components=len(workspace.components),
            physical_wires=len(wires), electrically_registered_components=sum(c.part_registration for c in workspace.components),
            electrically_registered_part_ids=len({c.part_id for c in workspace.components if c.part_registration and c.part_id}),
            BOM_bound_parts=sum(part.bom is not None for part in design.parts),
            firmware_bundles=len(workspace.firmware_bundles),
            direct_bundle_files=sum(len(bundle.files) for bundle in workspace.firmware_bundles),
            materialized_source_and_library_files=sum(len(bundle_source_files(bundle)) for bundle in workspace.firmware_bundles))
        report['counts'] = counts
        for key, number in dict(history=327, parts=146, nodes=298, components=164, physical_wires=129).items():
            check(counts[key] == number, 'Exact requested project count: ' + key + '=' + str(number))
        check(all(len(wire.wire_endpoints) == 2 for wire in wires), 'All129physical wires retain two owned endpoint references')
        boards = [c for c in workspace.components if c.kind == 'mcu' and c.catalog_id == 'st_nucleo_g474re']
        check(len(boards) == 1, 'Exact loaded project has one canonical G474 board')
        board = boards[0]
        check(board.part_registration and board.part_id in {part.id for part in design.parts},
              'Loaded G474 is registered to an actual saved CAD part')
        check(set(board.signal_pins) == set((*LEGACY_PINS, *NEW_PINS)), 'Loaded G474 retains six legacy and16new canonical signal pins')
        report['selected_G474'] = dict(component_id=board.id, part_id=board.part_id,
            catalog_id=board.catalog_id, pinout_catalog_id=board.pinout_catalog_id,
            signal_pins=dict(board.signal_pins))
        report['firmware_bundles'] = []
        for bundle in workspace.firmware_bundles:
            binding = verify_bundle_binding(bundle, workspace)
            condition(binding.status == 'current', 'Saved firmware binding is actually current: ' + bundle.id + ' [' + binding.status + ']')
            files = bundle_source_files(bundle)
            for file in files:
                check(sha256(file.content.encode('utf-8')).hexdigest() == file.sha256,
                      'Saved source/library SHA matches UTF-8 bytes: ' + bundle.id + '/' + file.path)
            report['firmware_bundles'].append(dict(id=bundle.id, target=bundle.target,
                board_component_id=bundle.binding.board_component_id, binding_status=binding.model_dump(mode='json'),
                direct_files=len(bundle.files), materialized_files=len(files),
                libraries=[dict(id=lib.id, version=lib.version, origin=lib.origin,
                    source_sha256=lib.source_sha256, files=len(lib.files)) for lib in bundle.libraries],
                files=[dict(path=file.path, role=file.role, bytes=len(file.content.encode('utf-8')), sha256=file.sha256) for file in files],
                pin_bindings=[pin.model_dump(mode='json') for pin in bundle.pin_bindings]))
        report['firmware_file_count_basis'] = 'Materialized source plus library files; direct bundle files are reported separately'
        condition(counts['materialized_source_and_library_files'] == 16,
                  'Stored project has16materialized firmware source/library files')
        report['phase'] = 'opening-owned-input'
        report['actual_Open_count'] += 1
        write()
        started = time.monotonic()
        window.open_project(input_path_checked)
        wait(lambda: not window.busy and window.document.path == input_path_checked and window.document.design is not None,
             'Actual owned project Open did not finish within600seconds; inspect actual stage timing and thread snapshots', 600)
        report['initial_load_seconds_once_not_benchmark'] = time.monotonic() - started
        unchanged('Initial native Open')
        check(set(window.viewport.actors) == {part.id for part in design.parts}, 'Native viewport owns every146saved CAD actors')
        report['native_actors'] = len(window.viewport.actors)
        shot(window, 'loaded-main-window')
        framebuffer('loaded-VTK-fullview')
        window.select_parts([board.part_id])
        app.processEvents()
        check(window.selected == board.part_id, 'Actual MainWindow CAD selection is the registered G474 part')
        modal(McuPinDialog, inspect_mcu, window.actions['mcu_pins'])
        unchanged('Cancel native MCU review')
        modal(BomDesignDialog, inspect_bom, window.actions['bom'])
        unchanged('Cancel native BOM review')
        modal(FirmwareDialog, inspect_firmware, window.actions['firmware'])
        unchanged('Cancel native firmware review')
        previous = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *_args, **_kwargs: (str(saved), 'Prompt CAD project (*.pcad)')
        try:
            report['Save_As_count'] += 1
            window.actions['save_as'].trigger()
        finally:
            QFileDialog.getSaveFileName = previous
        check(saved.is_file() and window.document.path == saved, 'Actual MainWindow Save As writes only the separate owned round-trip file')
        check(read_project(saved).model_dump(mode='json') == baseline, 'Owned saved bytes preserve full typed Project and every history/attachment/wire')
        report['saved_roundtrip'] = _file_identity(saved)
        report['phase'] = 'reopening-owned-roundtrip'
        report['actual_Open_count'] += 1
        write()
        reopened_started = time.monotonic()
        window.open_project(saved)
        wait(lambda: not window.busy and window.document.path == saved,
             'Actual owned round-trip reopen did not finish within600seconds; inspect actual stage timing and thread snapshots', 600)
        report['roundtrip_load_seconds_once_not_benchmark'] = time.monotonic() - reopened_started
        unchanged('Actual native round-trip reopen')
        check(_file_identity(saved) == report['saved_roundtrip'], 'Reopen leaves separate saved bytes unchanged')
        check(window.ai_task is None and window.codex_probe_task is None, 'Review starts no model/provider task')
        shot(window, 'roundtrip-main-window')
        report['review_completed'] = True
        report['success'] = not report['findings']
        report['phase'] = 'complete' if report['success'] else 'complete-with-findings'
    except Exception:
        report.update(success=False, phase='failed', error=traceback.format_exc())
    finally:
        report['cleanup_observations'] = [dict(phase='start', **_runtime_observation())]
        if diagnostic_timer is not None:
            diagnostic_timer.stop()
        for dialog in reversed(dialogs):
            try:
                dialog.reject()
                dialog.deleteLater()
            except RuntimeError:
                pass
        report['cleanup_observations'].append(dict(phase='after-owned-dialogs', **_runtime_observation()))
        pool_done = QThreadPool.globalInstance().waitForDone(30000)
        report['cleanup_observations'].append(dict(phase='after-threadpool-wait', **_runtime_observation()))
        report['owned_threadpool_done_within30s'] = bool(pool_done)
        window.show_error = original_show_error
        # Only this private window is closed. Never suppress a user window prompt.
        if not window.busy:
            window.document.dirty = False
            close_started = True
            window.close()
            app.processEvents()
        report['cleanup_observations'].append(dict(phase='after-owned-window-close', **_runtime_observation()))
        report['owned_window_close_requested'] = close_started
        report['owned_window_closed'] = close_started and not window.isVisible()
        if input_path_checked is not None and input_identity is not None:
            try:
                report['input_copy_unchanged_after_close'] = _file_identity(input_path_checked) == input_identity
            except Exception:
                report['input_copy_unchanged_after_close'] = False
                report['cleanup_input_error'] = traceback.format_exc()
            if not report['input_copy_unchanged_after_close']:
                report['success'] = False
                report['findings'].append('Owned input copy bytes changed')
        if not pool_done or not report['owned_window_closed']:
            report['success'] = False
            report['findings'].append('Owned asynchronous work or window cleanup did not finish')
            report['phase'] = 'failed-cleanup'
        report['check_count'] = len(report['checks'])
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if diagnostics is not None:
            try:
                diagnostics.finish()
            except Exception:
                report['success'] = False
                report['diagnostic_cleanup_error'] = traceback.format_exc()
                report['findings'].append('Owned diagnostic wrapper/file cleanup did not finish')
        write()
        app.exit(0 if report['success'] else 1)
