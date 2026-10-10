"""Owned native motion-number and document persistence smoke.

Only three synthetic cylinders are used.  This exercises native controls and
typed end poses; it does not qualify screw lead, hardware, or continuous travel.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import marshal
import os
from pathlib import Path
import sys
import time
import traceback

from PySide6.QtCore import QEvent, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton, QScrollArea


def fixture():
    from ..models import Design, Part
    return Design(name='Motion precision synthetic fixture',
        parts=[Part(id=key, name=key, fixed=key == 'base',
                    geometry=dict(kind='cylinder', diameter=5, height=5))
               for key in ('base', 'screw', 'crosshead')],
        mates=[dict(id='screw-rotation', kind='revolute', parent='base',
                    child='screw', x=20),
               dict(id='crosshead-slider', kind='slider', parent='base',
                    child='crosshead', x=40, z=219.7,
                    limits={'z': [214.7, 224.7]})],
        motion_links=[dict(id='screw-lead', driver='screw-rotation',
                           driver_axis='rz', driven='crosshead-slider',
                           driven_axis='z', ratio=5 / 360, offset=219.7)])


def run(app, window, output):
    from .. import __version__, models, assembly_motion
    from . import document as document_module, motion_dialog
    from .document import Document, read_project
    from .motion_dialog import MotionDialog

    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(success=False, phase='starting', version=__version__,
        frozen=bool(getattr(sys, 'frozen', False)),
        runtime_executable=sys.executable, pid=os.getpid(),
        started_utc=datetime.now(timezone.utc).isoformat(), checks=[],
        check_count=0, screenshots=[], screenshot_details=[], module_identity={},
        synthetic_only=True, part_count=3, live_ai_calls=0, hardware_calls=0,
        sdk_calls=0, network_calls=0, generated_code_executed=False, model_refresh_disabled=True,
        scope='Actual MainWindow/MotionDialog controls, document history and '
              'persistence; typed synthetic end poses. No product lead, '
              'physical strength, hardware, or continuous-collision qualification.')
    # Never replace a receipt from an earlier run.
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    dialogs = []
    timers = []
    errors = []
    original_show_error = window.show_error
    progress = [time.monotonic()]
    original_path = output.with_name(output.stem + '-input.pcad')
    saved_path = output.with_name(output.stem + '-roundtrip.pcad')

    def write():
        report['check_count'] = len(report['checks'])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding='utf-8')

    def check(condition, title, **details):
        report['checks'].append(dict(name=title, passed=bool(condition), **details))
        progress[0] = time.monotonic()
        write()
        if not condition:
            raise AssertionError(title)

    def wait(predicate, title, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            if errors:
                raise AssertionError('\n'.join(errors))
            if time.monotonic() >= deadline:
                raise TimeoutError(title)
            app.processEvents()
            QTest.qWait(10)
        if errors:
            raise AssertionError('\n'.join(errors))
        progress[0] = time.monotonic()

    def ready(dialog, title):
        wait(lambda: dialog.checked is not None and not dialog.running
             and not dialog.timer.isActive(), title)
        check(dialog.apply_button.isEnabled(), title + ': Apply is enabled')
        check(not dialog.interference['blocked'], title + ': no new interference')

    def shot(widget, suffix):
        path = output.with_name(output.stem + '-' + suffix + '.png')
        check(not path.exists(), 'Screenshot destination is new', file=path.name)
        check(widget.grab().save(str(path)), 'Actual Qt screenshot saved', file=path.name)
        report['screenshots'].append(str(path))
        report['screenshot_details'].append(dict(path=str(path),
            sha256=sha256(path.read_bytes()).hexdigest(),
            kind='Actual Qt widget capture; not mechanical qualification'))
        write()

    def click(dialog, text):
        target = next(w for w in dialog.findChildren(QPushButton) if w.text() == text)
        for scroll in dialog.findChildren(QScrollArea):
            if scroll.widget() and scroll.widget().isAncestorOf(target):
                scroll.ensureWidgetVisible(target)
        QTest.qWait(20)
        check(target.isEnabled() and target.isVisible(), 'Actual button is available', button=text)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)

    def type_number(widget, text):
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(widget, text)
        check(widget.text() == text, 'QTest entered the exact numeric text', text=text)

    def modal(callback, title):
        state = dict(done=False, started=False, error=None)
        deadline = time.monotonic() + 12
        timer = QTimer(window)
        timers.append(timer)
        timer.setInterval(20)

        def handle():
            dialog = QApplication.activeModalWidget()
            if not isinstance(dialog, MotionDialog) or dialog.parentWidget() is not window:
                if time.monotonic() >= deadline:
                    timer.stop()
                    state.update(done=True, error='Owned MotionDialog did not open: ' + title)
                    errors.append(state['error'])
                return
            if not dialog.isVisible() or state['started']:
                return
            state['started'] = True
            timer.stop()
            dialogs.append(dialog)
            try:
                callback(dialog)
                check(not dialog.alive, title + ': QTest closed the owned dialog')
            except Exception:
                state['error'] = traceback.format_exc()
                errors.append(state['error'])
                try:
                    shot(dialog, 'failure-dialog-' + str(len(dialogs)))
                except Exception:
                    pass
                if dialog.alive:
                    dialog.reject()
            finally:
                state['done'] = True

        timer.timeout.connect(handle)
        timer.start()
        window.actions['motion_links'].trigger()
        wait(lambda: state['done'], title)
        if state['error']:
            raise AssertionError(state['error'])
        wait(lambda: not window.busy, title + ': MainWindow operation finished')

    def endpoints(raw, ratio, expected):
        rows = []
        for angle, z in zip((-360, 360), expected):
            moved = deepcopy(raw)
            assembly_motion.set_joint_motion(moved, 'screw-rotation', {'rz': angle})
            typed = models.Design.model_validate(moved)
            slider = next(m for m in typed.mates if m.id == 'crosshead-slider')
            crosshead = next(p for p in typed.parts if p.id == 'crosshead')
            check(slider.z == z, 'Typed linked end pose is exact',
                  driver_degrees=angle, ratio=ratio, slider_mm=slider.z, expected_mm=z)
            check(crosshead.transform.z == z and crosshead.transform.x == 40,
                  'Typed solver places the actual synthetic crosshead at its end pose',
                  driver_degrees=angle, transform=crosshead.transform.model_dump())
            rows.append(dict(driver_degrees=angle, slider_mm=slider.z,
                             crosshead_transform=crosshead.transform.model_dump()))
        return rows

    def watchdog_tick():
        if time.monotonic() - progress[0] > 60:
            if not errors:
                errors.append('Owned motion precision smoke stopped progressing')
            for dialog in dialogs:
                if dialog.alive:
                    dialog.reject()

    watchdog = QTimer(window)
    watchdog.timeout.connect(watchdog_tick)
    watchdog.start(1000)
    try:
        app.setQuitOnLastWindowClosed(False)
        window.show_error = lambda message: errors.append(str(message))
        window.completion_notifier.enabled = False
        check(window.document.design is None, 'Private MainWindow starts without a user project')
        expected_profile = output.parent / (output.stem + '-profile')
        check(Path(os.environ['CADSTUDIO_DATA_DIR']).resolve() == expected_profile,
              'Entry selected the smoke-owned private profile')
        report['private_profile'] = str(expected_profile)
        check(window.language_service.language == 'ko', 'Fresh private controls use Korean labels')
        for module in (models, assembly_motion, document_module, motion_dialog, sys.modules[__name__]):
            path = Path(module.__file__).resolve()
            report['module_identity'][module.__name__] = dict(path=str(path),
                file_sha256=sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                loader=type(module.__loader__).__name__, origin=module.__spec__.origin,
                function_code_sha256={name: sha256(marshal.dumps(value.__code__)).hexdigest()
                    for name, value in vars(module).items()
                    if callable(value) and getattr(value, '__module__', None) == module.__name__
                    and hasattr(value, '__code__')})
        check(not original_path.exists() and not saved_path.exists(), 'Owned fixture and roundtrip paths are new')
        synthetic = fixture()
        doc = Document()
        doc.commit(synthetic, 'Synthetic motion precision fixture')
        doc.write(original_path)
        original_bytes = original_path.read_bytes()
        report['original_project'] = str(original_path)
        report['original_sha256'] = sha256(original_bytes).hexdigest()
        report['phase'] = 'native-open'
        write()
        window.open_project(original_path)
        wait(lambda: not window.busy and window.document.path == original_path, 'Actual fixture Open')
        check(window.document.design == synthetic.model_dump(), 'Actual MainWindow opens the exact three-part fixture')
        check(len(window.viewport.actors) == 3, 'Actual native viewport contains three CAD actors')
        before = deepcopy(window.document.design)
        history = deepcopy(window.document.journal.data)
        old_cursor = history['cursor']
        check(len(history['entries']) == 1, 'Fixture has one real Document history entry')
        report['initial_endposes'] = endpoints(before, 5 / 360, (214.7, 224.7))

        def unchanged(dialog):
            dialog.links.setCurrentRow(0)
            check(dialog.ratio.value() == 5 / 360 and dialog.offset.value() == 219.7,
                  'Real controls retain full-precision 5/360 and 219.7',
                  ratio_text=dialog.ratio.text(), offset_text=dialog.offset.text())
            click(dialog, '선택한 연결 수정')
            ready(dialog, 'Unchanged link preview')
            shot(dialog, 'exact-controls')
            QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)

        report['phase'] = 'unchanged-acceptance'
        modal(unchanged, 'Unchanged actual Apply')
        check(window.document.design == before and window.document.journal.data == history,
              'Actual unchanged acceptance preserves complete design and history')
        check(original_path.read_bytes() == original_bytes, 'Unchanged Apply preserves input bytes')

        def cancel(dialog):
            dialog.links.setCurrentRow(0)
            type_number(dialog.ratio, repr(4 / 360))
            click(dialog, '선택한 연결 수정')
            ready(dialog, 'Changed link cancellation preview')
            check(dialog.checked.motion_links[0].ratio == 4 / 360,
                  'Cancellation preview contains the explicit precise edit')
            click(dialog, '취소')

        report['phase'] = 'cancellation'
        modal(cancel, 'Actual changed-link Cancel')
        check(window.document.design == before and window.document.journal.data == history,
              'Actual Cancel preserves complete design and history')
        check(original_path.read_bytes() == original_bytes, 'Actual Cancel preserves original project bytes')

        def incomplete(dialog):
            dialog.joint.setCurrentIndex(dialog.joint.findData('crosshead-slider'))
            ready(dialog, 'Slider limit preview')
            revision = dialog.revision
            type_number(dialog.limit_fields['z'][2], '1e')
            check(dialog.revision > revision and dialog.checked is None
                  and not dialog.apply_button.isEnabled(),
                  'Incomplete upper limit immediately invalidates checked preview and Apply')
            wait(lambda: not dialog.running and not dialog.timer.isActive(), 'Invalid limit settles')
            check(dialog.checked is None and not dialog.apply_button.isEnabled(),
                  'Incomplete limit remains blocked after asynchronous validation')
            shot(dialog, 'incomplete-limit-blocked')
            click(dialog, '취소')

        report['phase'] = 'incomplete-limit'
        modal(incomplete, 'Incomplete limit cancellation')
        check(window.document.design == before and window.document.journal.data == history,
              'Incomplete limit cancellation preserves original design and history')

        def explicit(dialog):
            dialog.links.setCurrentRow(0)
            type_number(dialog.ratio, repr(4 / 360))
            click(dialog, '선택한 연결 수정')
            ready(dialog, 'Explicit precise link preview')
            check(dialog.checked.motion_links[0].ratio == 4 / 360
                  and dialog.checked.motion_links[0].offset == 219.7,
                  'Actual checked candidate preserves precise edited ratio and offset')
            shot(dialog, 'edited-controls')
            QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)

        report['phase'] = 'explicit-acceptance'
        modal(explicit, 'Actual explicit Apply')
        changed = deepcopy(window.document.design)
        expected = deepcopy(before)
        expected['motion_links'][0]['ratio'] = 4 / 360
        check(changed == expected, 'Actual explicit Apply changes only the requested ratio')
        changed_history = deepcopy(window.document.journal.data)
        new_cursor = changed_history['cursor']
        check(new_cursor != old_cursor and len(changed_history['entries']) == 2,
              'Actual Document appends exactly one explicit edit entry')
        check(changed_history['base'] == history['base']
              and changed_history['entries'][:-1] == history['entries'],
              'Document preserves history base and prior entry bytes as typed data')
        check(window.document.journal.at(old_cursor) == before
              and window.document.journal.at(new_cursor) == changed,
              'Document history restores both precise link values')
        report['edited_endposes'] = endpoints(changed, 4 / 360, (215.7, 223.7))
        window.actions['undo'].trigger()
        wait(lambda: not window.busy, 'Actual MainWindow Undo')
        check(window.document.design == before and window.document.journal.data['cursor'] == old_cursor,
              'Actual MainWindow Undo restores exact 5/360')
        window.actions['redo'].trigger()
        wait(lambda: not window.busy, 'Actual MainWindow Redo')
        check(window.document.design == changed and window.document.journal.data == changed_history,
              'Actual MainWindow Redo restores exact 4/360 and full history')

        report['phase'] = 'save-and-reopen'
        previous = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *_a, **_k: (str(saved_path), 'Prompt CAD project (*.pcad)')
        try:
            window.actions['save_as'].trigger()
        finally:
            QFileDialog.getSaveFileName = previous
        check(saved_path.is_file() and window.document.path == saved_path,
              'Actual MainWindow Save As writes only the owned roundtrip project')
        saved = window.document.project().model_dump(mode='json')
        check(read_project(saved_path).model_dump(mode='json') == saved,
              'Saved typed project equals the complete native document')
        window.open_project(saved_path)
        wait(lambda: not window.busy and window.document.path == saved_path, 'Actual MainWindow Reopen')
        check(window.document.project().model_dump(mode='json') == saved,
              'Actual MainWindow reopen preserves full design, assets, prompt and history')
        check(window.document.design['motion_links'][0]['ratio'] == 4 / 360,
              'Actual reopen retains the full precise explicit ratio')
        check(original_path.read_bytes() == original_bytes, 'Final input project bytes are unchanged')
        report.update(roundtrip_project=str(saved_path),
            roundtrip_sha256=sha256(saved_path.read_bytes()).hexdigest(),
            history_entries=len(changed_history['entries']),
            original_cursor=old_cursor, edited_cursor=new_cursor)
        shot(window, 'main-window-roundtrip')
        rounded = deepcopy(before)
        rounded['motion_links'][0]['ratio'] = .01389
        rounded['mates'][0]['rz'] = 360
        try:
            models.Design.model_validate(rounded)
        except ValueError as exc:
            check('운동 한계' in str(exc), 'Legacy .01389 rejects the real slider end limit',
                  validation_error=str(exc))
        else:
            check(False, 'Legacy .01389 rejects the real slider end limit')
        report.update(success=True, phase='complete')
    except Exception:
        report.update(success=False, phase='failed', error=traceback.format_exc())
    finally:
        watchdog.stop()
        for timer in timers:
            timer.stop()
        for dialog in reversed(dialogs):
            try:
                if dialog.alive:
                    dialog.reject()
            except RuntimeError:
                pass
        # No unrelated native window or project is opened in this private process.
        drained = QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
        report['owned_workers_drained'] = bool(drained)
        if not drained or window.busy:
            report.update(success=False, phase='cleanup-failed',
                          cleanup_error='Owned preview or MainWindow worker did not finish')
        for dialog in reversed(dialogs):
            try:
                dialog.deleteLater()
            except RuntimeError:
                pass
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.show_error = original_show_error
        window.document.dirty = False
        window.close()
        app.processEvents()
        report['owned_window_closed'] = not window.isVisible()
        if not report['owned_window_closed']:
            report.update(success=False, phase='cleanup-failed',
                          cleanup_error='Owned MainWindow refused closure')
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write()
        app.exit(0 if report['success'] else 1)
