"""Owned native repair integration. Uses real geometry and offline model replies."""
import json,time,traceback
from copy import deepcopy
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ..models import Design
from . import codex_ai
from .draft_preview import DraftPreviewDialog


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);report=dict(checks=[],live_ai_calls=0);original=codex_ai.generate;dialogs=[]
    def check(value,message):
        if not value:raise AssertionError(message)
        report['checks'].append(message)
    def wait(predicate):
        start=time.monotonic()
        while not predicate():
            if time.monotonic()-start>90:raise TimeoutError('Native repair operation timed out')
            app.processEvents();time.sleep(.01)
        app.processEvents()
    def plan(clear=False):
        actions=[dict(tool='create',target='frame',args=dict(name='클램프 지지 프레임',color='#ffffff',geometry=dict(kind='plate',length=30,width=20,thickness=10,hole_count=0))),dict(tool='create',target='specimen',args=dict(name='시편',geometry=dict(kind='plate',length=60,width=4,thickness=2,hole_count=0),transform=dict(z=6)))]
        if clear:actions.append(dict(tool='pocket',target='frame',args=dict(face='+Z',profile=dict(rectangle=dict(width=31,height=4.4)),depth=4.2)))
        return dict(summary='시편 치수 유지 · 클램프에 조립 여유 홈',actions=actions)
    calls=[]
    class Session:
        def __init__(self,replies):self.replies=replies
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def account(self):return dict(plan='offline')
        async def models(self):return [dict(model='fixture',efforts=['medium'])]
        async def content(self,model,messages,schema,effort,progress):calls.append(messages);return json.dumps(self.replies.pop(0))
    selection=dict(intent='assembly',tools=['create'],shapes=['plate'],new_parts=['frame','specimen'],connections=[])
    def generate(request,model,**kwargs):
        session=Session([plan(True)] if kwargs.get('repair') else [selection]+[plan()]*6)
        return original(request,model,**kwargs,session_factory=lambda _:session)
    try:
        codex_ai.generate=generate;w.codex_config=dict(model='fixture',executable='offline');w.provider.setCurrentIndex(w.provider.findData('codex'));w.provider_changed();w.ai_dock.show();w.ai_dock.raise_();w.prompt.setPlainText('시편 치수 유지하고 클램프 프레임 설계');before=deepcopy(w.document.design)
        w.generate_button.click();wait(lambda:w.ai_task is None)
        check(w.last_draft is not None,'Rejected but renderable draft retained')
        draft=w.last_draft;check(draft['response']['validation']['status']=='needs_repair','Interference flagged as needing repair')
        check(w.document.design==before,'Rejected draft leaves current document unchanged')
        check(w.accept_draft.isEnabled(),'Pending draft has accessible preview')
        check('✓' in w.codex_status.text(),'CAD validation is not a lost account connection')
        check('overlap_local_mm' in calls[-1][-1]['content'],'Real local overlap coordinates reach repair prompt')
        check('pocket' in calls[-1][0]['content'],'Repair tool instructions include missing pocket operation')
        w.apply_draft();check(w.document.design==before and not w.busy,'Direct apply cannot bypass pending review')
        dialog=DraftPreviewDialog(w,w.result,draft['preview'],w.ai_result.toPlainText(),validation=draft['response']['validation'],repairable=True);dialogs.append(dialog);dialog.show();app.processEvents()
        check(not dialog.apply_button.isEnabled() and dialog.repair_button.isVisible(),'Repair button replaces blocked apply action')
        dialog.accept();check(dialog.isVisible(),'Accept call cannot bypass guard')
        dialog.issues.setCurrentIndex(1);app.processEvents();check(set(dialog.viewport.selected_ids)=={'frame','specimen'},'Conflict pair highlights both actual bodies')
        dialog.grab().save(str(path.with_name('repair2111-pending.png')))
        dialog.mode.setCurrentIndex(1);check(not dialog.viewport.actors,'Before mode displays original empty workspace')
        dialog.mode.setCurrentIndex(0);dialog.reject();check(w.document.design==before,'Review dismiss preserves original')
        # Exercise actual modal -> repair handler, not only the provider function.
        def repair_dialog():
            modal=QApplication.activeModalWidget()
            if not isinstance(modal,DraftPreviewDialog):raise AssertionError('Expected repair preview modal')
            modal.repair_note.setText('시편 치수는 유지하고 프레임에 홈을 추가해');modal.repair_button.click()
        QTimer.singleShot(350,repair_dialog);w.preview_draft();wait(lambda:w.ai_task is None)
        check(w.last_draft['response']['validation']['status']=='ready','Continue repair obtains clear geometry')
        check(len(calls)==8,'Resume uses one plan call without repeating capability selection')
        check('사용자 추가 수정 지시' in calls[-1][-1]['content'],'Extra repair instruction reaches provider')
        check(not w.last_draft['preview']['stats']['collisions'],'Real corrected solids have zero overlap')
        check(w.document.design==before,'Repaired preview still requires explicit apply')
        w.apply_draft();wait(lambda:not w.busy)
        check(len(w.document.design['parts'])==2,'Validated corrected draft applies once')
        check(w.document.design['parts'][1]['geometry']['thickness']==2,'Specimen dimensions retained')
        check(len(w.document.design['parts'][0]['features'])==1,'Clamp has an actual editable clearance cut')
        w.grab().save(str(path.with_name('repair2111-applied.png')))
        check(w.document.journal is not None and len(w.document.journal.data['entries'])>=4,'Repair history recorded')
        from .research_upgrade_smoke import run_checks
        run_checks(app,w,path,check,wait,original)
        report['passed']=True
    except Exception:report.update(passed=False,error=traceback.format_exc())
    finally:
        codex_ai.generate=original
        for dialog in dialogs:
            if dialog.isVisible():dialog.reject()
        w.document.dirty=False;path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');QTimer.singleShot(200,lambda:app.exit(0 if report['passed'] else 1))
