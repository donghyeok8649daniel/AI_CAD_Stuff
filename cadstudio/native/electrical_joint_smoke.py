"""Owned native regression for editable wiring and sampled physical joint travel."""
from copy import deepcopy
import json
import time
import traceback

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog


def run(app, window, path):
    from .document import read_project
    from .electrical_dialog import CatalogDialog, ComponentDialog, ElectricalDialog
    from ..electrical_catalog import get_catalog_entry
    from .workflows import JointDriveDialog
    from ..gears import add_gear_pair
    from ..models import Design

    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'live_ai_calls': 0}
    dialogs = []
    errors = []

    def check(value, description):
        if not value:
            raise AssertionError(description)
        report['checks'].append(description)

    def wait(predicate, seconds=75):
        limit = time.monotonic() + seconds
        while not predicate():
            app.processEvents()
            QTest.qWait(10)
            if errors:
                raise AssertionError(errors[-1])
            if time.monotonic() >= limit:
                raise TimeoutError('electrical / joint native flow')
        app.processEvents()

    try:
        window.show_error = errors.append
        app.setQuitOnLastWindowClosed(False)
        check(window.document.design is None, 'starts with a blank design')
        check('electrical' in window.actions, 'electrical command is in native menu')
        wiring = ElectricalDialog(window, None)
        dialogs.append(wiring)
        wiring.show()
        wiring.demo()
        check(wiring.table.rowCount() == 4, 'example contains a battery, switch, wire, and motor')
        check('모터 기동' in wiring.report.toPlainText(), 'explicit startup current is checked separately')
        check('공급 / 소비 전력' in wiring.report.toPlainText(), 'DC report presents measured dimensions and results')
        wiring.grab().save(str(path.with_name('electrical2140.png')))
        wiring.accept()
        check(wiring.workspace.components[0].a == 'VPLUS', 'example nodes are valid identifiers')

        raw = Design().model_dump()
        raw['electrical'] = wiring.workspace.model_dump()
        window.apply_design(raw, 'electrical smoke', {'tool': 'electrical'})
        wait(lambda: not window.busy)
        check(len(window.document.design['electrical']['components']) == 4,
              'electrical workbench is committed to the CAD document')
        target = path.with_name('electrical2140.cad.json')
        window.document.write(target)
        reopened = read_project(target)
        check(reopened.design.electrical.components[3].kind == 'motor',
              'motor and wiring survive project save and reload')

        fault = ElectricalDialog(window, None)
        dialogs.append(fault)
        fault.show()
        fault.components = [
            dict(id='fault-source', name='5 V source', kind='battery', a='VPLUS', b='GND', voltage_v=5),
            dict(id='fault-lead', name='VCC lead', kind='wire', a='VPLUS', b='MCU_VCC',
                 length_mm=100, cross_section_mm2=.5, closed=False),
            dict(id='fault-mcu', name='controller', kind='mcu', a='MCU_VCC', b='GND',
                 rated_voltage_v=5, rated_current_a=.1, signal_pins={'GPIO1': 'SIGNAL'}),
            dict(id='fault-signal', name='GPIO lead', kind='wire', a='SIGNAL', b='LOAD_SIGNAL',
                 length_mm=100, cross_section_mm2=.5, closed=False),
            dict(id='fault-receiver', name='sensor input model', kind='resistor',
                 a='LOAD_SIGNAL', b='GND', resistance_ohm=1000),
        ]
        fault.refresh(); fault.calculate()
        report_text = fault.report.toPlainText()
        check('FAIL · VCC lead: 전선 단선' in report_text and 'FAIL · GPIO lead: 전선 단선' in report_text,
              'native report identifies both named broken wires')
        check('FAIL · controller: VCC → DC 전원 양극 경로' in report_text,
              'native report identifies missing MCU supply path')
        check('PASS · controller: GND/리턴 → DC 전원 음극 경로' in report_text,
              'native report distinguishes connected MCU return path')
        check('FAIL · controller GPIO1 (SIGNAL)' in report_text,
              'native report identifies open MCU signal path')
        fault.components[1]['closed'] = True
        fault.components[3]['closed'] = True
        fault.refresh(); fault.calculate()
        report_text = fault.report.toPlainText()
        check('PASS · controller: VCC → DC 전원 양극 경로' in report_text and
              'PASS · controller GPIO1 (SIGNAL)' in report_text,
              'native report changes to connected after both leads are repaired')
        fault.grab().save(str(path.with_name('electrical-fault2141.png')))

        catalog = CatalogDialog(window, 'Raspberry Pi 4')
        dialogs.append(catalog)
        catalog.show()
        check(catalog.entries and catalog.entries[0].catalog_id == 'rpi4b' and
              catalog.use_button.isEnabled() and catalog.open_button.isEnabled(),
              'native catalog finds the exact Raspberry Pi 4 and its official source')
        catalog.grab().save(str(path.with_name('electrical-catalog2141.png')))
        catalog.query.setText('STM32 Nucleo')
        catalog.search()
        check(catalog.entries and catalog.entries[0].reference_only and
              not catalog.use_button.isEnabled() and catalog.open_button.isEnabled(),
              'native catalog keeps the unidentified STM32 family reference-only')

        original_exec = CatalogDialog.exec
        def choose_pi(self):
            self.entry = get_catalog_entry('rpi4b')
            return QDialog.DialogCode.Accepted
        try:
            CatalogDialog.exec = choose_pi
            selected = ComponentDialog(window, [])
            dialogs.append(selected)
            selected.select_catalog()
            candidate = selected.candidate()
        finally:
            CatalogDialog.exec = original_exec
        check(candidate['kind'] == 'mcu' and candidate['catalog_id'] == 'rpi4b' and
              candidate['rated_voltage_v'] == 5 and candidate['rated_current_a'] == 0 and
              candidate['source_url'].startswith('https://www.raspberrypi.com/'),
              'exact-model prefill keeps the documented voltage without inventing current')

        gears = add_gear_pair(prefix='native2140-').model_dump()
        gears['mates'][0]['limits'] = {'rz': [-4, 4]}
        gears['electrical'] = deepcopy(window.document.design['electrical'])
        window.apply_design(gears, 'gear and circuit smoke', {'tool': 'gear-pair'}, fit=True)
        wait(lambda: not window.busy)
        check(window.document.design['electrical'] == raw['electrical'],
              'changing mechanical geometry preserves electrical workspace')
        drive = JointDriveDialog(window, window.document.design, 'native2140-drive')
        dialogs.append(drive)
        drive.show()
        wait(lambda: drive.checked is not None)
        check(drive.range_axis.count() > 0 and drive.survey_button.isEnabled(),
              'joint drive offers a motion-range control')
        drive.survey_button.click()
        wait(lambda: not drive.range_running and '개 자세 검사' in drive.range_report.text(), 120)
        check('음의 방향' in drive.range_report.text() and '양의 방향' in drive.range_report.text(),
              'both travel directions show sampled geometric clearance')
        check('표본 검사 결과' in drive.range_report.text(),
              'travel result discloses sampling and safety limit')
        drive.grab().save(str(path.with_name('joint-drive2140.png')))
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        drive.viewport.window.Render()
        capture = vtkWindowToImageFilter()
        capture.SetInput(drive.viewport.window)
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtkPNGWriter()
        writer.SetFileName(str(path.with_name('joint-viewport2140.png')))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        check(path.with_name('joint-viewport2140.png').stat().st_size > 1000,
              'rendered joint solids are captured from the real VTK viewport')
        check(window.document.design == gears,
              'read-only range survey preserves document and joint limits')
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        for dialog in dialogs:
            if dialog.isVisible():
                dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty = False
        window.close()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0 if report['success'] else 1)
