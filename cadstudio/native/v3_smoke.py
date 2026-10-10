"""Disposable native v3 verification. No network or generated code execution."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import threading
import time
import traceback

from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage,QColor


def run(app,window,output):
    from ..catalog import preset
    from ..models import Design
    from ..firmware_bundle import create_bundle,export_bundle_atomic
    from ..firmware_build import check_firmware_bundle
    from . import codex_ai
    from .document import read_project
    from .firmware_smoke2240 import fixture
    from .firmware_dialog import FirmwareDialog
    from .electrical_diagnostics_dialog import ElectricalDiagnosticsDialog
    from ..electrical_diagnostics import DiagnosticMeasurement

    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    report=dict(success=False,version=__import__('cadstudio').__version__,frozen=bool(getattr(sys,'frozen',False)),
        started_utc=datetime.now(timezone.utc).isoformat(),checks=[],screenshots=[],live_ai_calls=0,hardware_calls=0,
        generated_code_executed=False)
    original=codex_ai.generate;release=threading.Event();dialogs=[]
    def write():output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name);write()
    def wait(predicate):
        end=time.monotonic()+45
        while not predicate() and time.monotonic()<end:app.processEvents();QTest.qWait(10)
        check(predicate(),'Event loop completed owned asynchronous work')
    def shot(widget,name):
        path=output.with_name(name+'.png');check(widget.grab().save(str(path)),'Screenshot '+name)
        report['screenshots'].append(str(path));write()
    try:
        window.property_dock.show();window.property_dock.raise_();app.processEvents()
        window.toolbar.widgetForAction(window.actions['show_ai']).click();app.processEvents()
        check(window._ai_panel_active and window.prompt.hasFocus(),'Toolbar activates covered AI tab')
        catalog=[dict(model='gpt-6-astra',name='Astra fixture',efforts=['low','medium','high','xhigh','max','ultra']),
                 dict(model='gpt-6.1-sol',name='Sol fixture',efforts=['low','medium','high','xhigh','max','ultra'])]
        window.codex_catalog=catalog;window.codex_config={**window.codex_config,'model':'gpt-6-astra'}
        window.provider.setCurrentIndex(window.provider.findData('codex'))
        window.codex_models.set_catalog(catalog,'gpt-6-astra');window.update_codex_effort()
        check([window.cloud_effort.itemText(i) for i in range(window.cloud_effort.count())]==['Low','Medium','High','Extra high','Max','Ultra'],'Explicit catalog effort labels')
        entered=threading.Event();pairs=[]
        def mock_generate(request,model,**options):
            pairs.append(options['runtime_config'].snapshot());entered.set();release.wait(10)
            pairs.append(options['runtime_config'].snapshot())
            return dict(design=preset('cylinder').model_dump(),summary='Owned mock cylinder',assumptions=[],model=model,effort=options['effort'])
        codex_ai.generate=mock_generate
        window.prompt.setPlainText('Owned verification: cylinder diameter 30 mm, height 20 mm')
        window.generate_button.click();check(entered.wait(5),'Owned mock generation starts')
        check(window.codex_models.isEnabled() and window.cloud_effort.isEnabled(),'Settings selectable while response runs')
        window.codex_models.setCurrentIndex(window.codex_models.findData('gpt-6.1-sol'))
        window.cloud_effort.setCurrentIndex(window.cloud_effort.findData('ultra'));app.processEvents()
        shot(window,'v3-ai-settings')
        release.set();wait(lambda:window.ai_task is None)
        check(pairs==[('gpt-6-astra','medium'),('gpt-6.1-sol','ultra')],'Runtime next-stage pair changes atomically')
        check(window.last_draft is not None and window.accept_draft.isEnabled(),'Returned draft remains applicable')
        window.apply_draft();wait(lambda:not window.busy)
        check(window.document.design['parts'][0]['geometry']['diameter']==30,'Actual CAD cylinder applied after settings change')
        check(window.document.journal.data['entries'][-1]['context']['model_provenance']==dict(model='gpt-6-astra',effort='medium'),'Actual response provenance stored')
        window.select_parts([window.document.design['parts'][0]['id']]);app.processEvents()
        check(window._ai_panel_active,'CAD selection preserves AI panel')
        cad=fixture();workspace=cad.electrical;before=workspace.model_dump(mode='json')
        dialog=ElectricalDiagnosticsDialog(window,workspace,'board',codex_config=window.firmware_settings())
        dialogs.append(dialog);dialog.show();app.processEvents()
        check(not dialog._running and dialog.diagnostic_report is None,'Opening diagnosis does not send data')
        image=QImage(480,240,QImage.Format.Format_RGB32);image.fill(QColor('#d3e6ef'))
        photo=output.with_name('owned-diagnosis-fixture.png');check(image.save(str(photo)),'Owned synthetic photo created')
        dialog.add_photo(photo);dialog.symptoms.setPlainText('Synthetic fixture: unexplained motor stop; no actual hardware tested.')
        dialog.measurements=[DiagnosticMeasurement(id='reading1',quantity='current',value=3,component_id='wire',provenance='user_reported',power_state='unknown',isolated=False,note='Synthetic verification input; not actual hardware measurement.')]
        dialog.review_button.click();app.processEvents()
        check(dialog.diagnostic_report is not None and dialog.export_button.isEnabled(),'Local evidence diagnosis produces report')
        check(dialog.workspace.model_dump(mode='json')==before,'Diagnosis preserves original electrical workspace')
        check('미검증' in dialog.status.text() and bool(dialog.diagnostic_report.unknowns),'Diagnosis preserves hardware uncertainty')
        shot(dialog,'v3-electrical-diagnosis');dialog.reject()
        library=output.parent/'owned-library';library.mkdir(exist_ok=True)
        (library/'sensor.py').write_text('def parse(value):\n    return float(value)\n',encoding='utf-8')
        firmware=FirmwareDialog(workspace,window,'ko','board',codex_config=window.firmware_settings())
        dialogs.append(firmware);firmware.show();app.processEvents()
        firmware.import_library('directory',library,name='owned-parser',version='1.0.0')
        wait(lambda:firmware.task is None)
        check(len(firmware._libraries)==1 and firmware.libraries_table.rowCount()==1,'Native library folder imported with pinned metadata')
        firmware.tabs.setCurrentIndex(2);app.processEvents();shot(firmware,'v3-firmware-library')
        bundle=create_bundle('Owned source check','raspberry_python',workspace,'board',
            [dict(path='main.py',content='from sensor import parse\nvalue = parse("2.0")\n',role='source')],
            'main.py',libraries=firmware._libraries)
        checked=check_firmware_bundle(bundle,workspace=workspace)
        check(checked.status!='failed' and not checked.full_target_build,'Library syntax check remains separate from target build')
        raw=cad.model_dump(mode='json');raw['electrical']['firmware_bundles']=[bundle.model_dump(mode='json')]
        window.document.commit(Design.model_validate(raw),'Owned firmware with library')
        project=output.with_name('owned-v3.pcad');window.document.write(project)
        check(read_project(project).design.electrical.firmware_bundles[0]==bundle,'PCAD save/reopen preserves library source and hashes')
        destination=output.parent/'owned-export';export_bundle_atomic(bundle,destination)
        check((destination/'firmware-dependencies.json').is_file(),'Export includes dependency manifest')
        check((destination/'libraries'/bundle.libraries[0].id/'sensor.py').is_file(),'Export includes original library bytes')
        firmware.reject();report['success']=True
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        release.set();codex_ai.generate=original
        window.cancel_ai()
        for dialog in dialogs:dialog.reject();dialog.deleteLater()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty=False;window.close();app.processEvents()
        report['check_count']=len(report['checks']);report['finished_utc']=datetime.now(timezone.utc).isoformat();write()
        app.exit(0 if report['success'] else 1)
