"""Native reference/reconnect/rename integration with real CAD and offline transport."""
import asyncio,base64,hashlib,json,time,traceback
from copy import deepcopy
import httpx
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtWidgets import QInputDialog
from PySide6.QtTest import QTest


def run_checks(app,w,path,check):
    from ..github_reference import GitHubReader
    from ..references import extract_reference
    from .reference_dialog import ReferenceDialog
    from . import codex_ai
    from .codex_reconnect import RecoveringSession,ConnectionInterrupted
    from ..catalog import preset
    from .document import read_project
    def wait(predicate):
        end=time.monotonic()+40
        while not predicate():
            if time.monotonic()>end:raise TimeoutError('Native reference integration timed out')
            app.processEvents();time.sleep(.01)
        app.processEvents()
    text=b'# Research fixture\nGauge diameter 8 mm. Model time is not physical seconds.\n'
    sha=hashlib.sha1(b'blob '+str(len(text)).encode()+b'\0'+text).hexdigest();revision='a'*40;requests=[]
    def response(request):
        requests.append(request);route=request.url.path
        if route=='/user':data={'login':'demo-researcher'}
        elif route=='/repos/demo/research':data={'default_branch':'main','private':True}
        elif '/commits/' in route:data={'sha':revision}
        elif '/git/trees/' in route:data={'truncated':False,'tree':[dict(path='README.md',mode='100644',type='blob',size=len(text),sha=sha)]}
        elif '/git/blobs/' in route:data={'encoding':'base64','content':base64.b64encode(text).decode()}
        else:raise AssertionError(route)
        return httpx.Response(200,json=data)
    dialog=ReferenceDialog(w);dialog.show();app.processEvents()
    full_size=dialog.size();dialog.resize(680,560);app.processEvents()
    check(dialog.rect().contains(dialog.use_button.mapTo(dialog,QPoint(0,dialog.use_button.height()))),'Reference apply button stays visible in a compact 680 by 560 window')
    check(dialog.scroll.verticalScrollBar().maximum()>0,'Long reference content remains reachable by scrolling')
    dialog.resize(full_size);app.processEvents()
    reader=GitHubReader('test_token',httpx.MockTransport(response))
    try:
        dialog.start(lambda control,progress:(reader,reader.connect('demo/research','main',control)),dialog.connected)
        wait(lambda:dialog.task is None)
        check(dialog.connection['revision']==revision and dialog.files.count()==1,'GitHub connection lists pinned research documents in native UI')
        check('✓' in dialog.status.toPlainText(),'Connection success visibly marked')
        dialog.files.item(0).setSelected(True);dialog.fetch_selected();wait(lambda:dialog.task is None)
        check(len(dialog.refs)==1 and 'diameter 8 mm' in dialog.preview.toPlainText(),'Selected GitHub file content is visible before AI transmission')
        check(dialog.refs[0].revision==revision,'Source commit is preserved')
        check(all(r.method=='GET' and r.url.host=='api.github.com' for r in requests),'GitHub integration is read-only with fixed API host')
        settings=json.loads(dialog.settings_path.read_text(encoding='utf-8'))
        check(set(settings)=={'repo','branch'} and 'test_token' not in json.dumps(settings),'Only repository selection is persisted, never token or body')
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
        from io import BytesIO
        writer=PdfWriter();page=writer.add_blank_page(300,300);stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 250 Td (Specimen diameter 8 mm) Tj ET')
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})});page[NameObject('/Contents')]=stream
        data=BytesIO();writer.write(data);pdf=extract_reference('specimen.pdf',data.getvalue());dialog.add_references([pdf])
        check('diameter 8 mm' in pdf.text and len(dialog.refs)==2,'Bundled PDF reader extracts text with page provenance')
        dialog.scroll.ensureWidgetVisible(dialog.preview);app.processEvents();dialog.grab().save(str(path.with_name('references2130.png')))
        w.set_references(dialog.refs);dialog.accept()
        check(len(w.reference_materials)==2 and '2' in w.reference_status.text(),'AI panel exposes active references')
        w.provider.setCurrentIndex(w.provider.findData('codex'));w.codex_config={'model':'test-model','executable':''};w.prompt.setPlainText('연구 자료의 시편 지름을 설명해줘');w.ai_mode.setCurrentIndex(w.ai_mode.findData('chat'))
        # Read-only chat uses real request assembly, with only transport replaced.
        from . import ai_chat
        original_answer=ai_chat.answer;calls=[]
        class Session:
            def __init__(self):self.closed=False
            async def __aenter__(self):return self
            async def __aexit__(self,*a):self.closed=True
            async def account(self):return {'plan':'test'}
            async def models(self):return [{'model':'test-model','efforts':['medium']}]
            async def content(self,model,messages,*args):calls.append(deepcopy(messages));return json.dumps({'answer':'README.md / specimen.pdf: gauge diameter 8 mm.'})
        ai_chat.answer=lambda *a,**kw:original_answer(*a,**kw,session_factory=lambda _:Session())
        try:w.generate_draft();wait(lambda:w.ai_task is None)
        finally:ai_chat.answer=original_answer
        check('diameter 8 mm' in w.ai_result.toPlainText() and w.document.design is None,'Question answering reads references without changing geometry')
        check(len(json.loads(calls[0][-2]['content'])['reference_materials'])==2,'Actual Codex chat request contains both reviewed snapshots')
        # Names change independently of geometry, joint IDs and grouping.
        w.apply_design(preset('robot_arm').model_dump(),'rename fixture',fit=True);wait(lambda:not w.busy)
        before=deepcopy(w.document.design);part_id=before['parts'][0]['id'];w.select_parts([part_id])
        old=QInputDialog.getText
        QInputDialog.getText=lambda *a,**kw:('상부 고정 프레임',True)
        try:
            w.activateWindow();w.viewport.widget.setFocus();app.processEvents();QTest.keyClick(w.viewport.widget,Qt.Key.Key_F2);wait(lambda:not w.busy)
        finally:QInputDialog.getText=old
        after=deepcopy(w.document.design);expected=deepcopy(before);expected['parts'][0]['name']='상부 고정 프레임'
        check(after==expected,'F2 renames only display name and preserves geometry, IDs, joints and groups')
        w.undo();wait(lambda:not w.busy);check(w.document.design==before,'Rename supports undo')
        w.redo();wait(lambda:not w.busy);check(w.document.design==after,'Rename supports redo')
        project_file=path.with_name('renamed.cad.json');w.document.write(project_file)
        check(read_project(project_file).design.parts[0].name=='상부 고정 프레임','Renamed part survives project save/load')
        check('reference_materials' not in project_file.read_text(encoding='utf-8') and 'test_token' not in project_file.read_text(encoding='utf-8'),'Project does not include private reference body or GitHub token')
        from .search_dialog import SearchDialog,activate_result
        finder=SearchDialog(w);finder.kind.setCurrentIndex(finder.kind.findData('part'));finder.query.setText('상부 고정 프레임')
        check(finder.items.count()==1,'Ctrl+F search finds renamed part by all query words')
        finder.activate();activate_result(w,finder.result_row)
        check(w.selected_parts==[part_id],'Search selects exactly the matching part')
        finder=SearchDialog(w);finder.kind.setCurrentIndex(finder.kind.findData('command'));finder.query.setText('연구');finder.activate()
        check(finder.result_row[0]=='command','Search includes CAD commands with type filtering')
        finder.deleteLater()
        check(w.actions['find'].shortcut().toString()=='Ctrl+F','Part/function search is bound to Ctrl+F')
        w.chat_history=[{'role':'assistant','content':'old research'}];w.set_references([])
        check(not w.chat_history and not w.reference_materials,'Removing references clears stale chat context')
        w.set_references([pdf]);w.document.dirty=False;w.new_document()
        check(not w.reference_materials and w.document.design is None,'New document clears attached research context')
        check(w.actions['rename_part'].text() and w.actions['references'].text(),'Rename and research references are discoverable in menus')
        # Complete a real native AI draft with one simulated network interruption.
        w.set_references([pdf]);w.ai_mode.setCurrentIndex(w.ai_mode.findData('design'));w.prompt.setPlainText('자료를 참고해 지름 8 mm 원통을 만들어줘')
        sequence=[dict(intent='part',tools=['create'],shapes=['cylinder'],new_parts=['specimen'],connections=[]),ConnectionInterrupted('offline'),
            dict(summary='Reference cylinder',construction=['Solid cylinder: diameter 8 mm, height 20 mm'],name=None,assumptions=None,base=dict(tool='create',target='specimen',args=dict(name='연구 시편',geometry=dict(kind='cylinder',diameter=8,height=20,bore_diameter=0),color=None,transform=None)),actions=[])]
        recorded=[];sessions=[];notices=[]
        class Recoverable(Session):
            async def content(self,model,messages,*args):
                recorded.append(deepcopy(messages));value=sequence.pop(0)
                if isinstance(value,Exception):raise value
                return json.dumps(value)
        def factory(_):session=Recoverable();sessions.append(session);return session
        original_generate=codex_ai.generate;original_init=RecoveringSession.__init__;original_notify=w.completion_notifier.notify
        async def fast_wait(_):await asyncio.sleep(.02)
        RecoveringSession.__init__=lambda self,*a,**kw:original_init(self,*a,**kw,sleep=fast_wait)
        codex_ai.generate=lambda *a,**kw:original_generate(*a,**kw,session_factory=factory)
        w.completion_notifier.notify=lambda needs_review=False:notices.append(needs_review)
        try:
            w.generate_draft();wait(lambda:w.ai_task is None)
            check(w.last_draft is not None and w.last_draft['response']['validation']['status']=='ready','Native design resumes after network interruption and produces validated geometry: '+w.ai_result.toPlainText()[:1200])
            check(len(sessions)==2 and all(s.closed for s in sessions) and recorded[1]==recorded[2],'Reconnect closes owned session and resends exactly the interrupted stage')
            check('specimen.pdf' in recorded[-1][1]['content'],'Reconnect preserves attached research snapshot')
            check(notices==[False],'Successful design emits exactly one completion notification')
            check(w.document.design is None,'Completion notification does not auto-apply the draft')
            w.apply_draft();wait(lambda:not w.busy)
            check(w.document.design['parts'][0]['geometry']['diameter']==8,'Reconnected result applies real researched 8 mm cylinder')
        finally:
            codex_ai.generate=original_generate;RecoveringSession.__init__=original_init;w.completion_notifier.notify=original_notify
    finally:
        if dialog.isVisible():dialog.reject()
        dialog.deleteLater();w.document.dirty=False


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);report={'checks':[],'live_ai_calls':0}
    def check(condition,message):
        if not condition:raise AssertionError(message)
        report['checks'].append(message)
    try:run_checks(app,w,path,check);report['passed']=True
    except Exception:report.update(passed=False,error=traceback.format_exc())
    finally:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        QTimer.singleShot(100,lambda:app.exit(0 if report.get('passed') else 1))
