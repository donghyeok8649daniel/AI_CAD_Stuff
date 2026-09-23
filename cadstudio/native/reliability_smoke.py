"""Run the actual frozen GUI, including its installed local AI and cancellation."""
import json
import math
import time
import traceback
from pathlib import Path


def run(app,w,path):
    from PySide6.QtCore import Qt,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QTest
    from ..models import Extrusion
    from ..catalog import preset
    from . import geometry as G
    from .document import read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);checks=[];report={}
    def check(value,message):
        if not value:raise AssertionError(message)
        checks.append(message)
    def wait(condition,timeout=20):
        end=time.monotonic()+timeout
        while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(15)
        check(condition(),'operation completes within deadline')
    try:
        app.setQuitOnLastWindowClosed(False);w.resize(1200,780)
        w.start_sketch(g=Extrusion(sketch_mode='entities',entities=[G.circle(G.pt(-10,0),3),G.circle(G.pt(10,0),3)]).model_dump())
        e=w.editor;wait(lambda:e.preview is not None);e.canvas.fit();app.processEvents()
        pos=e.canvas.screen(G.pt(10,1));app.sendEvent(e.canvas,QMouseEvent(QEvent.Type.MouseMove,pos,e.canvas.mapToGlobal(pos),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
        check(e.canvas.hover_region==1,'hover recommends the second profile')
        e.selected={item['id'] for item in e.g['entities']};e.create_group('두 구멍');wait(lambda:e.preview is not None);e.use_group('add')
        check(e.g['profiles']==[0,1],'named group resolves both closed regions');e.grab().save(str(path.with_name('group-hover.png')))
        e.finish_sketch();wait(lambda:not w.busy);saved=w.document.design['sketches'][0]
        raw=preset('plate').model_dump();raw['parts'][0]['geometry']['hole_count']=0;raw['sketches']=[saved];w.apply_design(raw,'블록 재사용 확인');wait(lambda:not w.busy)
        before=w.result['stats']['volume'];face=next(f for f in w.result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99)
        w.viewport.face=(w.selected,face);w.reuse_sketch_on_face(saved['id']);wait(lambda:e.preview is not None);e.groups.setCurrentIndex(1);e.use_group('cut');e.depth.setValue(2);e.finish();wait(lambda:not w.busy)
        check(not w.sketching,'group pocket returns to the workbench');check(abs(before-w.result['stats']['volume']-2*math.pi*9*2)<1e-4,'group cuts the exact two-cylinder volume')
        check(any(s['id']==saved['id'] for s in w.document.design['sketches']),'source sketch remains reusable');w.document.write(path.with_suffix('.cad.json'));read_project(path.with_suffix('.cad.json'));check(True,'groups and reuse history reopen')
        QTest.qWait(100);app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
        check(any(b.isVisible() for b in w.findChildren(QPushButton,'partColorButton')),'color control visible at top of properties');check(w.actions['color'] in w.toolbar.actions(),'color action in top toolbar')
        # The actual user-facing generation button, not just the provider function.
        w.ai_dock.show();w.ai_dock.raise_();w.provider.setCurrentIndex(w.provider.findData('ollama'));wait(lambda:bool(w.ollama_models.model_name()),12)
        # Start from a blank document, as the prompt requests a new simple part.
        from .document import Document
        w.document=Document();w.selected=None;w.operation_serial+=1
        w.prompt.setPlainText('직경 20 mm, 높이 10 mm인 구멍 없는 원통 1개를 만들어줘.');start=time.monotonic();w.generate_button.click()
        check(w.ai_task is not None and not w.busy and w.toolbar.isEnabled(),'CAD stays responsive during real Ollama generation')
        ticks=0
        while w.ai_task and time.monotonic()-start<320:app.processEvents();QTest.qWait(50);ticks+=1
        check(w.ai_task is None and w.last_draft is not None,w.ai_result.toPlainText());report['generation_seconds']=round(time.monotonic()-start,3);report['ui_event_cycles']=ticks
        g=w.last_draft['design']['parts'][0]['geometry'];check(g['kind']=='cylinder' and g['diameter']==20 and g['height']==10,'real AI returns requested dimensions');w.grab().save(str(path.with_name('ollama-complete.png')))
        w.apply_draft();wait(lambda:not w.busy);check(w.document.design['parts'][0]['geometry']['height']==10,'verified draft applies to the CAD document')
        w.prompt.setPlainText('이 원통의 높이만 25 mm로 바꿔줘. 지름과 나머지 설정은 유지해.');start=time.monotonic();w.generate_button.click();wait(lambda:w.ai_task is None,320)
        check(w.last_draft is not None,w.ai_result.toPlainText());g=w.last_draft['design']['parts'][0]['geometry'];check(g['diameter']==20 and g['height']==25,'real AI edits height and preserves diameter');report['edit_seconds']=round(time.monotonic()-start,3)
        w.apply_draft();wait(lambda:not w.busy)
        w.prompt.setPlainText('높이를 30 mm로 바꿔줘.');w.generate_button.click();task=w.ai_task;QTest.qWait(500);start=time.monotonic();w.cancel_ai_button.click();wait(lambda:not task.thread.is_alive(),5)
        report['cancel_seconds']=round(time.monotonic()-start,3);check(w.ai_task is None and w.generate_button.isEnabled(),'cancel permits a new request')
        w.generate_button.click();task=w.ai_task;QTest.qWait(400);w.document.dirty=False;start=time.monotonic();w.close();report['close_seconds']=round(time.monotonic()-start,3)
        check(not w.isVisible() and task.control.cancelled.is_set(),'closing the window cancels AI without waiting for its answer');wait(lambda:not task.thread.is_alive(),5)
        report.update(success=True,checks=checks);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        report.update(success=False,checks=checks,error=traceback.format_exc());path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.cancel_ai();w.editor.stop();w.viewport.shutdown();app.exit(1)
