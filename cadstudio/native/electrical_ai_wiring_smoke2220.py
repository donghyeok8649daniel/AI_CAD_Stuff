"""Owned real native AI wiring review; plans are offline, no provider calls."""
from copy import deepcopy
import json
import time
import traceback

from PySide6.QtCore import QThreadPool,QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QInputDialog


def run(app,window,path):
    from ..models import Design,Part,DraftRequest
    from ..electrical import ElectricalWorkspace
    from ..electrical_catalog import catalog_counts
    from ..electrical_diff import electrical_changes
    from ..preview_metadata import reuse_preview
    from .cad_tools import execute_plan
    from .document import read_project
    from .draft_preview import DraftPreviewDialog

    path.parent.mkdir(parents=True,exist_ok=True)
    report=dict(checks=[],live_ai_calls=0,hardware_calls=0)
    errors=[];dialogs=[];last=[time.monotonic()]
    original_input=QInputDialog.getMultiLineText
    def check(condition,title):
        if not condition:raise AssertionError(title)
        report['checks'].append(title);last[0]=time.monotonic()
        path.write_text(json.dumps(dict(report,success=False,phase='running'),ensure_ascii=False,indent=2),encoding='utf-8')
    def wait(predicate):
        end=time.monotonic()+60
        while not predicate():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('Owned AI wiring flow')
        app.processEvents()
    def own_modal(callback):
        end=time.monotonic()+15;state={'done':False}
        def handle():
            dialog=QApplication.activeModalWidget()
            if not isinstance(dialog,DraftPreviewDialog) or not dialog.isVisible():
                if time.monotonic()<end:QTimer.singleShot(20,handle);return
                errors.append('Actual draft review did not open');state['done']=True
                if dialog is not None:dialog.reject()
                return
            dialogs.append(dialog)
            try:callback(dialog)
            except Exception:errors.append(traceback.format_exc());dialog.reject()
            state['done']=True
        QTimer.singleShot(20,handle)
        QTest.mouseClick(window.accept_draft,Qt.MouseButton.LeftButton)
        wait(lambda:state['done'])
    def watchdog_check():
        if time.monotonic()-last[0]>90:
            errors.append('Owned wiring verification stopped progressing')
            active=QApplication.activeModalWidget()
            if active is not None:active.reject()
    watchdog=QTimer(window);watchdog.timeout.connect(watchdog_check);watchdog.start(1000)
    try:
        app.setQuitOnLastWindowClosed(False);window.show_error=errors.append;window.resize(1500,960)
        before=Design(parts=[Part(id=identifier,name=name,color=color,
            geometry=dict(kind='plate',length=20,width=15,thickness=2,hole_count=0),transform=dict(x=index*100))
            for index,(identifier,name,color) in enumerate((('pi','Controller CAD','#113355'),
                ('driver','Motor driver CAD','#446688'),('motor','Motor envelope CAD','#778899'),
                ('supply','5 V source CAD','#AA8855')))],
            electrical=ElectricalWorkspace.model_validate(dict(nodes=['GND','BAT'],components=[
                dict(id='source',name='Declared 5 V bench source',kind='battery',a='BAT',b='GND',voltage_v=5)])))
        window.apply_design(before.model_dump(mode='json'),'Owned before circuit',fit=True)
        wait(lambda:not window.busy and window.document.design is not None)
        saved=deepcopy(window.document.design);initial_cursor=window.document.journal.data['cursor']
        actors={identifier:id(value[0]) for identifier,value in window.viewport.actors.items()}
        check(catalog_counts()['registerable']>=68,'expanded exact catalogue is available in the native runtime')

        def action(tool,target,**args):return dict(tool=tool,target=target,args=args)
        actions=[action('electrical_bind','supply',component_id='source'),
            action('electrical_register','pi',catalog_id='rpi4b'),
            action('electrical_register','driver',catalog_id='pololu_2130'),
            action('electrical_register','motor',kind='motor',analysis_enabled=False)]
        for source,terminal,target,other in [('supply','a','pi','supply:5V_2'),('supply','b','pi','supply:GND_6'),
                ('supply','a','driver','port:VIN'),('supply','b','driver','port:GND'),
                ('pi','pin:GPIO17','driver','port:AIN1'),('driver','port:AOUT1','motor','a'),
                ('driver','port:AOUT2','motor','b')]:
            actions.append(action('electrical_wire_add',source,source_terminal=terminal,target_id=target,
                target_terminal=other,name=terminal+' wire',wire_color='#12AB34'))
        content=json.dumps(dict(summary='Actual power, control and motor wires',actions=actions))
        reply=execute_plan(content,DraftRequest(prompt='기존 CAD 부품과 회로를 대응시키고 실제 전선을 그려',current=before))
        check(before.model_dump(mode='json')==saved,'offline AI plan leaves the current design unchanged')
        wires=[c for c in reply.design.electrical.components if c.kind=='wire']
        check(len(wires)==7 and all(len(c.wire_endpoints)==2 for c in wires),'AI creates seven real wires with physical source/target endpoint metadata')
        check(all(not c.analysis_enabled and c.length_mm==c.cross_section_mm2==0 for c in wires),'unknown cable dimensions stay pending and outside DC calculation')
        check([p.geometry for p in reply.design.parts]==[p.geometry for p in before.parts],'wiring plan preserves CAD geometry')
        check([p.color for p in reply.design.parts]==[p.color for p in before.parts],'wiring plan preserves user body colours')
        candidate=reply.design.model_dump(mode='json')
        new_preview=reuse_preview(reply.design,saved,window.result)
        check(new_preview is not None,'electrical-only draft reuses verified geometry without remeshing')
        check(bool(electrical_changes(before,reply.design)),'actual circuit edits appear in the before/after review data')
        response=reply.model_dump(mode='json')
        draft=dict(serial=window.operation_serial,provider='ollama',prompt='Owned offline wiring',
            response=response,design=candidate,preview=new_preview)
        window.last_draft=draft;window.accept_draft.setEnabled(True);window.ai_result.setPlainText(reply.summary)
        initial_project=deepcopy(window.document.project().model_dump(mode='json'))
        def cancel_review(dialog):
            check(dialog.tabs.currentIndex()==1,'native draft review opens the wiring tab for electrical edits')
            panel=dialog.electrical_panel
            check(panel is not None and panel.inspection_only,'actual wiring preview is inspection-only')
            QTest.qWait(25);app.processEvents()
            shown=[panel.view.mapFromScene(item.sceneBoundingRect()).boundingRect().height()
                   for item in panel.component_items.values() if item.isVisible()]
            check(panel.view.viewport().height()>=180 and max(shown,default=0)>=panel.view.viewport().height()*.2,
                  'wiring preview retains a usable native canvas and readable component scale')
            check(len(panel.branch_items)>=7,'real circuit scene contains the seven saved wire branches')
            check(panel.workspace.model_dump()==reply.design.electrical.model_dump(),'after view displays the exact AI draft circuit')
            check(dialog.change_table.rowCount()>7,'review lists registration, links, pins and wire changes')
            dialog.grab().save(str(path.with_name('ai-wiring-after2220.png')))
            dialog.mode.setCurrentIndex(dialog.mode.findData('before'));app.processEvents()
            check(panel.workspace.model_dump()==before.electrical.model_dump(),'before view displays the unchanged original circuit')
            dialog.grab().save(str(path.with_name('ai-wiring-before2220.png')))
            dialog.reject()
        own_modal(cancel_review)
        check(window.document.project().model_dump(mode='json')==initial_project,'cancelled review preserves the entire original document and history')
        check(window.last_draft is draft,'cancelled review retains its generated draft for further inspection')
        def apply_review(dialog):
            check(dialog.apply_button.isEnabled(),'validated wiring preview can be applied explicitly')
            dialog.tabs.setCurrentIndex(0);app.processEvents()
            check(dialog.viewport.result is not None and not dialog.viewport.closed,'switching to CAD geometry initializes a live owned renderer safely')
            dialog.tabs.setCurrentIndex(1);app.processEvents()
            QTest.mouseClick(dialog.apply_button,Qt.MouseButton.LeftButton)
        own_modal(apply_review)
        wait(lambda:not window.busy and window.document.design==candidate)
        check(window.last_draft is None,'explicit apply clears the consumed AI draft')
        check({identifier:id(value[0]) for identifier,value in window.viewport.actors.items()}==actors,'electrical apply keeps the existing CAD actors')
        check(len(window.document.design['electrical']['components'])==11,'all four linked devices and seven wires are committed')
        final_cursor=window.document.journal.data['cursor']
        check(final_cursor!=initial_cursor,'physical AI wiring is retained in normal operation history')
        output=path.with_name('owned-ai-wiring2220.cad.json');window.document.write(output)
        reopened=read_project(output)
        check(reopened.design.model_dump(mode='json')==candidate,'ordinary project save/reopen preserves actual wire endpoints and CAD links')
        count=0
        while window.document.journal.data['cursor']!=initial_cursor:
            window.undo();wait(lambda:not window.busy);count+=1
            if count>len(actions)+2:raise AssertionError('Unexpected undo path')
        check(window.document.design==saved,'undoing the AI operations restores the exact original circuit and bodies')
        for _ in range(count):window.redo();wait(lambda:not window.busy)
        check(window.document.journal.data['cursor']==final_cursor and window.document.design==candidate,'redo restores exact AI wires and component identities')

        circuit_action=window.actions['wiring_diagram'];button=window.toolbar.widgetForAction(circuit_action)
        check(button is not None and button.isVisible(),'direct circuit toolbar button is visible next to body colour')
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);wait(lambda:window.wiring_window.isVisible())
        panel=window.wiring_window;panel.focus_component('ereg_001');window.ai_mode.setCurrentIndex(window.ai_mode.findData('chat'))
        QInputDialog.getMultiLineText=lambda *_args,**_kwargs:('선택 보드의 GPIO17 제어 배선을 수정해줘',True)
        source_prompt=window.prompt.toPlainText();serial=window.operation_serial
        QTest.mouseClick(panel.ai_button,Qt.MouseButton.LeftButton);app.processEvents()
        check(window.ai_mode.currentData()=='design','circuit AI request prepares design mode even after chat mode')
        check(window.prompt.toPlainText()!=source_prompt and 'component_id=ereg_001' in window.prompt.toPlainText(),'AI handoff includes the selected actual component identity')
        check(window.ai_task is None and window.operation_serial==serial,'AI handoff starts no provider and changes no document')
        check(window.document.design==candidate,'preparing an AI wiring request preserves the saved circuit')
        check(not errors,'owned native wiring flow completes without application errors')
        report['success']=True
    except Exception:report.update(success=False,error=traceback.format_exc())
    finally:
        watchdog.stop();QInputDialog.getMultiLineText=original_input
        for dialog in reversed(dialogs):
            try:dialog.reject();dialog.deleteLater()
            except RuntimeError:pass
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty=False;window.close()
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
