"""Owned open/save/undo flow for a locally supplied legacy project copy.

The fixture, project copies and screenshots stay in the private test folder.
No user profile, source fixture or other running CAD window is modified.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
import traceback


def run(app, window, path):
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from ..history import equivalent

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fixture = Path(os.environ['CADSTUDIO_HISTORY_FIXTURE']).resolve()
    original_bytes = fixture.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    raw = json.loads(original_bytes.decode('utf-8-sig'))
    report = {'checks': [], 'live_ai_calls': 0, 'private_fixture': True,
              'parts': len(raw['design']['parts']),
              'history_entries': len(raw['history']['entries'])}
    errors = []
    window.show_error = lambda message: errors.append(str(message))
    pulses = [0]
    timer = QTimer(window)
    timer.timeout.connect(lambda: pulses.__setitem__(0, pulses[0] + 1))
    timer.start(50)

    def check(value, title):
        if not value:
            raise AssertionError(title)
        report['checks'].append(title)
        path.write_text(json.dumps(dict(report, success=False, phase='running'),
                                   ensure_ascii=False, indent=2), encoding='utf-8')

    def wait():
        end = time.monotonic() + 900
        while window.busy:
            app.processEvents()
            QTest.qWait(10)
            if errors:
                raise AssertionError(errors[-1])
            if time.monotonic() > end:
                raise TimeoutError('Owned legacy project operation')
        app.processEvents()
        check(not errors, 'native operation completed without an error dialog')

    try:
        check(window.document.design is None, 'owned window starts with an empty project')
        window.open_project(fixture)
        wait()
        check(window.document.path == fixture, 'normal native open installs the requested copied project')
        check(equivalent(window.document.design, raw['design']), 'legacy current geometry and electrical values are preserved')
        check(window.result['stats']['valid'], 'all current CAD geometry builds successfully')
        check(len(window.result['meshes']) == len(raw['design']['parts']), 'every saved CAD body is present in the rendered result')
        journal = window.document.journal.data
        check(equivalent(journal['entries'], raw['history']['entries']), 'every history change, context, ID and branch is preserved')
        check(journal['cursor'] == raw['history']['cursor'], 'original history cursor is preserved')
        check(journal['head'] == raw['history']['head'], 'original history head is preserved')
        check(pulses[0] >= 20, 'event loop remains responsive while the large project loads')
        check(not window.document.dirty, 'opening does not create an unsaved edit')

        current = deepcopy(window.document.design)
        cursor = journal['cursor']
        parent = window.document.journal.index[cursor]['parent']
        check(parent is not None, 'fixture has an undoable final operation')
        previous = window.document.journal.at(parent)
        window.undo()
        wait()
        check(window.document.journal.data['cursor'] == parent, 'native undo restores the previous history cursor')
        check(equivalent(window.document.design, previous), 'native undo restores the full previous design')
        window.redo()
        wait()
        check(window.document.journal.data['cursor'] == cursor, 'native redo restores the original cursor')
        check(equivalent(window.document.design, current), 'native redo restores every electrical and geometric value')

        saved = path.parent / 'private-roundtrip.cad.json'
        window.document.write(saved)
        check(saved.is_file(), 'native document writes a separate roundtrip project')
        written = json.loads(saved.read_text(encoding='utf-8'))
        check(equivalent(written['history']['entries'], raw['history']['entries']), 'roundtrip file retains all original history changes')
        check(equivalent(written['design'], current), 'roundtrip file retains the complete current design')
        window.open_project(saved)
        wait()
        check(window.document.path == saved, 'normal native open reopens the roundtrip file')
        check(equivalent(window.document.design, current), 'roundtrip reopen preserves complete current design')
        check(len(window.document.journal.data['entries']) == len(raw['history']['entries']), 'roundtrip reopen retains the complete timeline')
        check(hashlib.sha256(fixture.read_bytes()).hexdigest() == original_sha, 'source fixture is unchanged')
        window.grab().save(str(path.parent / 'private-history-open.png'))
        window.document.dirty = False
        timer.stop()
        window.close()
        check(not window.isVisible(), 'owned verification window closes normally')
        report['success'] = True
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0)
    except Exception:
        timer.stop()
        report.update(success=False, error=traceback.format_exc())
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.document.dirty = False
        app.exit(1)
