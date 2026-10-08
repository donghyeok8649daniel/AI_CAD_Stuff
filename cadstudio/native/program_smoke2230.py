"""Packaged native code upload, saved wiring, cancellation and Qt lifecycle QA.

Only synthetic fixtures in the caller's output directory are read/written.
No private source, CAD project, auth key or connected hardware is inspected.
"""
from __future__ import annotations

import gc
import json
from pathlib import Path
import time

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtGui import QFontDatabase
from shiboken6 import isValid

from ..electrical import ElectricalWorkspace
from .program_simulation_dialog import ProgramSimulationDialog
from .widgets import apply_theme


def run(output):
    app = QApplication.instance() or QApplication([])
    if Path('C:/Windows/Fonts/malgun.ttf').is_file(): QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')
    apply_theme(app)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    source = 'const int p=9; void setup(){pinMode(p,OUTPUT);}void loop(){analogWrite(p,128);delay(20);digitalWrite(p,LOW);delay(20);}'
    source_path = output.with_name(output.stem + '-controller.ino')
    source_path.write_text(source, encoding='utf-8')
    workspace = ElectricalWorkspace.model_validate({'nodes':['GND','PWR','OUT','DRIVER','MOTOR'],'components':[
        {'id':'battery','name':'Battery','kind':'battery','a':'PWR','b':'GND','voltage_v':5},
        {'id':'board','name':'Arduino','kind':'mcu','a':'PWR','b':'GND','catalog_id':'arduino_uno_r3',
         'analysis_enabled':False,'pinout_catalog_id':'arduino_uno_r3','signal_pins':{'D9':'OUT'}},
        {'id':'driver','name':'Driver','kind':'load','a':'MOTOR','b':'GND','analysis_enabled':False,'terminal_pins':{'PWM':'DRIVER'}},
        {'id':'cable','name':'Cable','kind':'wire','a':'OUT','b':'DRIVER','analysis_enabled':False}]})
    original = workspace.model_dump(); checks = []; saved = None
    def check(name, condition):
        checks.append({'name':name,'pass':bool(condition)})
        if not condition: raise AssertionError(name)
    def await_result(dialog):
        deadline = time.monotonic()+5
        while dialog._running and time.monotonic()<deadline: app.processEvents(); time.sleep(.005)
        check('Automatic worker returns before deadline',not dialog._running and dialog.result is not None)
    def dispose(dialog):
        dialog.deleteLater()
        QThreadPool.globalInstance().waitForDone(5000); app.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete); app.processEvents(); gc.collect()
        check('Qt widget lifetime released',not isValid(dialog))
    screenshot = output.with_suffix('.png')
    original_file_dialog = QFileDialog.getOpenFileName
    try:
        QFileDialog.getOpenFileName = staticmethod(lambda *args, **kwargs: (str(source_path),'Program source (*.ino)'))
        for index in range(12):
            dialog = ProgramSimulationDialog(workspace,language='en' if index%2 else 'ko')
            dialog.show(); dialog.upload_button.click()
            check(f'{index}: actual source file uploaded',dialog.attachments and dialog.attachments[0].source==source)
            if index%3==0:
                dialog.reject(); check(f'{index}: close cancels owned worker',dialog._cancel.is_set())
            else:
                await_result(dialog)
                check(f'{index}: exact board auto resolved',dialog.result.status=='ready' and dialog.result.board_component_id=='board')
                check(f'{index}: physical signal reaches saved receiver','driver/port:PWM' in dialog.result.events[0].targets)
                check(f'{index}: bounded trace table',0<dialog.events.rowCount()<=2000)
                check(f'{index}: resolved board binding retained',dialog.attachments[0].board_component_id=='board')
                check(f'{index}: automatic separate DC safety checked',dialog.safety_report is not None)
                if index==1: dialog.grab().save(str(screenshot))
                if index%2:
                    programs=[attachment.model_dump() for attachment in dialog.attachments]
                    dialog.apply_button.click();check(f'{index}: explicit attachment accepted',dialog.result is not None and dialog._closing)
                    saved_data=workspace.model_dump();saved_data['programs']=programs
                    saved=ElectricalWorkspace.model_validate(saved_data)
                    project_path=output.with_name(output.stem+'-workspace.json')
                    project_path.write_text(saved.model_dump_json(),encoding='utf-8')
                    restored=ElectricalWorkspace.model_validate_json(project_path.read_text(encoding='utf-8'))
                    check(f'{index}: source SHA and target survive reload',restored.programs==saved.programs)
                    reopen=ProgramSimulationDialog(restored,language='en')
                    await_result(reopen)
                    check(f'{index}: reopened attachment retraces automatically',reopen.result.status=='ready')
                    reopen.reject();dispose(reopen)
                else:
                    dialog.reject();check(f'{index}: cancelled attachment leaves original',workspace.model_dump()==original)
            dispose(dialog);check(f'{index}: original circuit unmodified',workspace.model_dump()==original)
        remove_view = ProgramSimulationDialog(saved,language='en')
        await_result(remove_view); remove_view.remove_button.click()
        check('Attachment removal clears draft only',not remove_view.attachments and bool(saved.programs))
        check('Removed source trace cleared',remove_view.result is None and remove_view.events.rowCount()==0)
        remove_view.reject(); dispose(remove_view)
        check('Cancel removal preserves saved program target',saved.programs[0].board_component_id=='board')
    finally: QFileDialog.getOpenFileName = original_file_dialog
    result={'success':True,'checks':checks,'passed':len(checks),'screenshot':str(screenshot),
        'scope':'Synthetic file upload -> exact board binding -> wiring trace and separate DC safety -> apply/reload/cancel/Qt lifetime.'}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'success':True,'passed':len(checks),'output':str(output)}))
    return result
