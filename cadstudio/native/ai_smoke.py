"""Real Ollama and native UI verification, isolated by the CLI's test profile."""
import json,time,traceback
from pathlib import Path


def run(app,w,path):
    from PySide6.QtTest import QTest
    from .document import read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);report={'checks':[],'phase':'starting'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(value,name):
        if not value:raise AssertionError(name)
        report['checks'].append(name);save()
    def wait(condition,timeout=30):
        end=time.monotonic()+timeout;notice=0
        while not condition() and time.monotonic()<end:
            app.processEvents();QTest.qWait(20)
            if time.monotonic()-notice>10:
                report['ai_status']=w.ai_result.toPlainText();save();notice=time.monotonic()
        check(condition(),'native operation completes')
    def generate(prompt):
        report['phase']='generating';report['current_prompt']=prompt;save()
        w.prompt.setPlainText(prompt);started=time.monotonic();w.generate_button.click()
        check(w.ai_task is not None and not w.busy and w.toolbar.isEnabled(),'CAD remains editable during local AI')
        wait(lambda:w.ai_task is None,900);check(w.last_draft is not None,w.ai_result.toPlainText())
        report.setdefault('drafts',[]).append(w.last_draft['response']);save()
        return round(time.monotonic()-started,3)
    try:
        app.setQuitOnLastWindowClosed(False);w.resize(1260,820);w.ai_dock.show();w.ai_dock.raise_()
        check(w.document.design is None and w.result is None,'native app starts with an empty design')
        wait(lambda:bool(w.ollama_models.model_name()),15)
        report['model']=w.ollama_models.model_name();index=w.ai_timeout.findData(None)
        check(index>=0,'unlimited option exists in the wait menu');w.ai_timeout.setCurrentIndex(index)
        check(w.ai_timeout.currentData() is None and '무제한' in w.ai_timeout.currentText(),'unlimited wait is selectable')
        report['create_seconds']=generate('가로 80 mm 세로 50 mm 높이 25 mm이고 벽과 바닥 두께 2 mm인 위가 열린 상자 하나 만들어줘.')
        check(abs(w.last_draft['preview']['stats']['volume']-19592)<.01,'real model creates an open box with exact wall and floor dimensions')
        from ..models import Design
        from ..kernel import local_shape,exact_bounds
        design=Design.model_validate(w.last_draft['design']);shape=local_shape(design,design.parts[0]);bounds=exact_bounds(shape)
        x=(bounds.xmin+bounds.xmax)/2;y=(bounds.ymin+bounds.ymax)/2
        check(shape.isInside((x,y,bounds.zmin+1)) and not shape.isInside((x,y,bounds.zmax-1)),
              'exact solid has a floor below and an opening above')
        check(w.ai_result.toPlainText().startswith('CAD 계산 결과'),'actual measurements precede model prose in the draft panel')
        check(len(w.last_draft['response']['tool_actions'])>=2,'draft shows a validated multi-step CAD plan')
        w.apply_draft();wait(lambda:not w.busy);before=w.document.design['parts'][0]
        report['edit_seconds']=generate('기존 상자의 형상과 치수는 그대로 두고 색상을 #2266CC로 바꾸고 X 위치를 100 mm로 옮겨줘.')
        after=w.last_draft['design']['parts'][0]
        check(after['geometry']==before['geometry'] and after['features']==before['features'],'AI edit preserves validated geometry and features')
        check(after['color'].lower()=='#2266cc' and after['transform']['x']==100,'real AI respects requested appearance and placement')
        w.apply_draft();wait(lambda:not w.busy)
        file=path.with_suffix('.cad.json');w.document.write(file);reopened=read_project(file)
        check(len(reopened.history.entries)>=2,'AI creation and edit history save and reopen')
        check(all(e.context.get('tool_actions') for e in reopened.history.entries[1:]),'per-step tools and arguments remain in saved history')
        from PySide6.QtCore import QPoint,QRectF
        from PySide6.QtGui import QPainter,QImage
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        w.ai_dock.raise_();w.fit();QTest.qWait(150);view=w.viewport;view.window.Render();image=vtkWindowToImageFilter();image.SetInput(view.window);image.ReadFrontBufferOff();image.Update();writer=vtkPNGWriter();writer.SetInputConnection(image.GetOutputPort());png=path.with_name('ai241-viewport.png');writer.SetFileName(str(png));writer.Write();pix=w.grab();painter=QPainter(pix);pos=view.widget.mapTo(w,QPoint(0,0));painter.drawImage(QRectF(pos.x(),pos.y(),view.widget.width(),view.widget.height()),QImage(str(png)));painter.end();pix.save(str(path.with_name('ai241-native.png')))
        w.prompt.setPlainText('새로운 로봇 부품을 설계해줘');w.generate_button.click();task=w.ai_task;QTest.qWait(300);started=time.monotonic();w.cancel_ai_button.click();wait(lambda:not task.thread.is_alive(),5);report['cancel_seconds']=round(time.monotonic()-started,3)
        check(w.ai_task is None and w.generate_button.isEnabled(),'unlimited generation cancels and permits retry')
        w.generate_button.click();task=w.ai_task;QTest.qWait(300);w.document.dirty=False;started=time.monotonic();w.close();report['close_seconds']=round(time.monotonic()-started,3)
        check(not w.isVisible() and task.control.cancelled.is_set(),'closing the app interrupts unlimited AI');wait(lambda:not task.thread.is_alive(),5)
        report['success']=True;report['phase']='complete';save();app.quit()
    except Exception:
        report.update(success=False,error=traceback.format_exc());path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.cancel_ai();w.document.dirty=False;app.exit(1)
