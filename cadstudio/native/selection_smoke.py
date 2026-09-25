"""Real Qt/VTK checks for selection, grouping, clipboard and joint visibility."""
import json,time,traceback,math
from copy import deepcopy
from PySide6.QtCore import Qt,QPoint,QRectF,QEvent,QPointF
from PySide6.QtGui import QPainter,QImage,QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QTreeWidgetItemIterator
from ..models import Design,Part,Extrusion
from .document import read_project
from . import geometry as G


def run(app,w,path):
    path.parent.mkdir(parents=True,exist_ok=True);checks=[];errors=[]
    def check(ok,title):
        if not ok:raise AssertionError(title)
        checks.append(title)
    def wait(predicate,timeout=40):
        deadline=time.monotonic()+timeout
        while not predicate():
            app.processEvents();QTest.qWait(15);time.sleep(.001)  # Yield to Python AI/network worker threads too.
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>deadline:raise TimeoutError('UI wait')
        app.processEvents()
    def apply(data):w.apply_design(data,'선택 테스트',fit=True);wait(lambda:not w.busy)
    def key(code,mods=Qt.KeyboardModifier.ControlModifier):
        w.activateWindow();w.viewport.widget.setFocus();app.processEvents();QTest.keyClick(w.viewport.widget,code,mods);app.processEvents();wait(lambda:not w.busy)
    def snapshot(name,target=None):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        target=target or w;app.processEvents();v=target.viewport;v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update();writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=target.grab();p=QPainter(pix);pos=v.widget.mapTo(target,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(path.with_name(name+'-viewport.png'))));p.end();pix.save(str(path.with_name(name+'.png')))
    def screen(point):
        v=w.viewport;v.renderer.SetWorldPoint(*point,1);v.renderer.WorldToDisplay();return v.renderer.GetDisplayPoint()[:2]
    def click_world(point,shift=False):
        v=w.viewport;x,y=screen(point);scale=v.widget.devicePixelRatioF();pos=QPoint(round(x/scale),round((v.window.GetSize()[1]-1-y)/scale))
        QTest.mouseClick(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,pos);app.processEvents()
    try:
        app.setQuitOnLastWindowClosed(False);w.show_error=lambda text:errors.append(text);w.resize(1180,780);w.activateWindow();app.processEvents()
        raw=Design(parts=[Part(id=i,name=n,geometry={'kind':'plate','length':20,'width':20,'thickness':12,'hole_count':0},transform={'x':x},fixed=(i=='a')) for i,n,x in [('a','베이스',-45),('b','축 지지대',0),('c','링크',45)]],mates=[dict(id='ab',kind='revolute',parent='a',child='b',x=45),dict(id='bc',kind='rigid',parent='b',child='c',x=45)]).model_dump()
        apply(raw);v=w.viewport;v.filter.setCurrentIndex(v.filter.findData('body'));v.set_view('top');app.processEvents()
        click_world((-45,0,12));check(w.selected_parts==['a'],'actual viewport click selects one part')
        click_world((0,0,12),True);check(set(w.selected_parts)=={'a','b'},'Shift click adds a second part')
        click_world((-45,0,12),True);check(w.selected_parts==['b'],'Shift click removes selected part')
        lo=screen((-58,-15,0));hi=screen((13,15,0));v.box_pick(lo,hi);check(set(w.selected_parts)=={'a','b'},'containment box selects two complete bodies')
        w.select_parts([]);scale=v.widget.devicePixelRatioF();height=v.window.GetSize()[1]
        start=QPoint(round(lo[0]/scale),round((height-1-lo[1])/scale));end=QPoint(round(hi[0]/scale),round((height-1-hi[1])/scale))
        QTest.mousePress(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,start)
        QApplication.sendEvent(v.widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(end),QPointF(v.widget.mapToGlobal(end)),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier));app.processEvents();check(v.rubber.isVisible(),'Shift drag displays native selection rectangle')
        QTest.mouseRelease(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,end);app.processEvents();check(set(w.selected_parts)=={'a','b'} and not v.rubber.isVisible(),'Shift drag selects bodies without orbiting')
        v.box_pick(screen((47,2,12)),screen((43,-2,12)),True);check(set(w.selected_parts)=={'a','b','c'},'crossing box adds intersected body')
        v.visibility('b',False);v.box_pick(lo,hi);check(w.selected_parts==['a'],'box excludes hidden bodies');v.visibility('b',True)
        w.select_parts(['a','b']);key(Qt.Key.Key_G);check(len(w.document.design.get('part_groups',[]))==1,'Ctrl G creates a persistent part group')
        check(len(w.selected_parts)==2,'group operation preserves multi selection')
        click_world((-45,0,12));check(set(w.selected_parts)=={'a','b'},'group selection picks complete group')
        w.actions['group_select'].setChecked(False);click_world((-45,0,12));check(w.selected_parts==['a'],'group selection can be disabled to pick individual members')
        key(Qt.Key.Key_G,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier);check(not w.document.design.get('part_groups'),'Ctrl Shift G ungroups from any member')
        key(Qt.Key.Key_Z);check(bool(w.document.design.get('part_groups')),'Ctrl Z restores group')
        key(Qt.Key.Key_Y);check(not w.document.design.get('part_groups'),'Ctrl Y redoes ungroup')
        # The tree's selection signal must not be collapsed by itemClicked.
        items={};it=QTreeWidgetItemIterator(w.tree)
        while it.value():
            item=it.value();data=item.data(0,Qt.ItemDataRole.UserRole)
            if data and data[0]=='part':items[data[1]]=item
            it+=1
        w.tree.scrollToItem(items['a']);QTest.mouseClick(w.tree.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.tree.visualItemRect(items['a']).center())
        w.tree.scrollToItem(items['c']);QTest.mouseClick(w.tree.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,w.tree.visualItemRect(items['c']).center());app.processEvents();check(set(w.selected_parts)=={'a','b','c'},'tree Shift range keeps multiple parts selected')
        key(Qt.Key.Key_C)
        from .part_ui import PART_MIME
        from . import clipboard
        check(bool(clipboard.read(PART_MIME)),'Ctrl C retains the native part clipboard even when the system clipboard is unavailable')
        key(Qt.Key.Key_V);check(len(w.document.design['parts'])==6 and len(w.selected_parts)==3,'Ctrl C V copies selected assembly')
        copied=set(w.selected_parts);check(all({m['parent'],m['child']}<=copied for m in w.document.design['mates'][2:]),'pasted joints refer only to new parts')
        key(Qt.Key.Key_X);check(len(w.document.design['parts'])==3,'Ctrl X cuts only selected copies')
        key(Qt.Key.Key_Z);check(len(w.document.design['parts'])==6,'Ctrl Z restores cut parts and joints')
        key(Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier);check(len(w.document.design['parts'])==3,'Ctrl Shift Z redoes cut')
        w.ai_dock.show();w.ai_dock.raise_();w.prompt.setFocus();w.prompt.clear();QTest.keyClicks(w.prompt,'abcdef');before=deepcopy(w.document.design)
        QTest.keyClick(w.prompt,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClick(w.prompt,Qt.Key.Key_X,Qt.KeyboardModifier.ControlModifier);check(not w.prompt.toPlainText(),'Ctrl X cuts prompt text')
        QTest.keyClick(w.prompt,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);check(w.prompt.toPlainText()=='abcdef' and w.document.design==before,'text undo leaves CAD history unchanged')
        key(Qt.Key.Key_J,Qt.KeyboardModifier.NoModifier);check(v.joints.enabled and len(v.joints.records)==2 and len(v.joints.pickables)==4,'J displays all rigid and moving joints')
        v.set_view('iso');app.processEvents();row=v.joints.records[0];x,y=screen(row['origin']);check(v.joints.pick(x,y),'occluded joint marker is pickable')
        check(set(w.selected_parts)=={'a','b'},'joint click highlights connected pair')
        w.connection_overview();snapshot('selection250-workbench')
        w.resize(820,560);app.processEvents();check(w.width()==820 and v.widget.width()>=250 and v.widget.height()>=180,'compact layout retains usable viewport')
        joint_button=w.selection_toolbar.widgetForAction(w.joint_toolbar_action);check(joint_button.isVisible() and w.selection_toolbar.rect().contains(joint_button.geometry()),'joint toggle remains visible at 820 pixels');snapshot('selection250-compact')
        w.resize(1180,780);w.select_parts(['a','b']);w.group_parts();wait(lambda:not w.busy);w.document.write(path.with_suffix('.cad.json'));saved=read_project(path.with_suffix('.cad.json'));check(len(saved.design.part_groups)==1 and len(saved.design.mates)==2,'groups and joints survive project save/reopen')
        key(Qt.Key.Key_A);key(Qt.Key.Key_Delete,Qt.KeyboardModifier.NoModifier);check(not w.document.design['parts'],'delete all parts yields valid empty design');key(Qt.Key.Key_Z);check(len(w.document.design['parts'])==3,'undo empty design restores assembly')
        from .placement_dialog import PlacementDialog
        original_exec=PlacementDialog.exec;before_move=deepcopy(w.document.design)
        def automatic_move(dialog):
            dialog.show();wait(lambda:dialog.checked is not None);check(not dialog.apply_button.isEnabled(),'zero placement does not create a history entry')
            dialog.fields['x'].setValue(25);wait(lambda:not dialog.timer.isActive() and not dialog.running)
            check(dialog.checked is None and not dialog.apply_button.isEnabled(),'grounded selection cannot move accidentally')
            dialog.grounded.setChecked(True);dialog.fields['rz'].setValue(90);dialog.center.setCurrentIndex(dialog.center.findData('world'));wait(lambda:dialog.checked is not None)
            check(len(dialog.moved_ids)==3 and dialog.apply_button.isEnabled(),'move includes constrained components and previews valid placement')
            check(dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect()),'placement apply button stays reachable')
            snapshot('placement260-preview',dialog);dialog.accept();return 1
        PlacementDialog.exec=automatic_move
        try:w.select_parts(['c']);key(Qt.Key.Key_M,Qt.KeyboardModifier.NoModifier)
        finally:PlacementDialog.exec=original_exec
        check(len(w.selected_parts)==3 and w.document.design['parts'][0]['fixed'],'M moves whole assembly and preserves grounding')
        check(abs(w.document.design['parts'][0]['transform']['x']-25)<1e-6 and abs(w.document.design['parts'][0]['transform']['y']+45)<1e-6,'move uses world pivot and exact entered coordinates')
        after_move=deepcopy(w.document.design);key(Qt.Key.Key_Z);check(w.document.design==before_move,'undo restores complete assembly placement');key(Qt.Key.Key_Y);check(w.document.design==after_move,'redo restores moved assembly')
        from .workflows import JointDriveDialog
        w.show_mate('ab');w.ai_dock.show();w.ai_dock.raise_();app.processEvents()
        check(w.selected_joint=='ab' and 'ab' in w.ai_target.text(),'selected joint is identified visibly in AI panel')
        w.ai_scroll.verticalScrollBar().setValue(0);app.processEvents()
        check(w.prompt.visibleRegion().contains(w.prompt.rect()) and not w.ai_settings.isVisible(),'AI prompt is immediately visible with settings collapsed')
        snapshot('joint260-ai-target')
        w.resize(820,560);app.processEvents();w.ai_scroll.verticalScrollBar().setValue(0);app.processEvents();snapshot('ai260-compact')
        check(w.prompt.visibleRegion().contains(w.prompt.rect()),'AI prompt remains fully visible at minimum window size')
        # Exercise account setup without opening a browser or making API requests.
        from .openai_setup import OpenAISetupDialog, QDesktopServices, API_KEYS_URL, BILLING_URL
        original_setup=OpenAISetupDialog.exec;original_open=QDesktopServices.openUrl
        prior_provider=w.provider.currentData();prior_key=w.key.text();prior_prompt=w.prompt.toPlainText();before_setup=deepcopy(w.document.design);opened=[]
        def setup_flow(dialog):
            dialog.show();app.processEvents()
            check(dialog.key.echoMode()==dialog.key.EchoMode.Password,'account setup masks API key')
            check(dialog.use_button.visibleRegion().contains(dialog.use_button.rect()),'account setup apply remains visible')
            dialog.grab().save(str(path.with_name('openai261-setup.png')))
            dialog.key.setText('test-only-not-a-real-api-key')
            dialog.keys_button.click();dialog.billing_button.click()
            check(opened==[API_KEYS_URL,BILLING_URL],'account setup opens only fixed official pages without credentials')
            check(w.ai_task is None and w.key.text()==prior_key,'browser setup does not start AI or apply credentials early')
            QDesktopServices.openUrl=lambda url:False
            dialog.keys_button.click();check(API_KEYS_URL in dialog.status.toPlainText(),'browser failure gives a copyable official address')
            dialog.reject();return 0
        try:
            QDesktopServices.openUrl=lambda url:opened.append(url.toString()) or True
            OpenAISetupDialog.exec=setup_flow;w.openai_setup()
            check(w.provider.currentData()==prior_provider and w.key.text()==prior_key,'cancelled setup preserves provider and key')
            def apply_setup(dialog):
                dialog.key.setText('  test-only-not-a-real-api-key  ');dialog.use_button.click();return dialog.result()
            OpenAISetupDialog.exec=apply_setup;w.openai_setup()
            check(w.provider.currentData()=='openai' and w.key.text()=='test-only-not-a-real-api-key' and w.ai_task is None,'setup applies key and provider without a paid request')
            check(w.document.design==before_setup and w.prompt.toPlainText()==prior_prompt,'account setup preserves CAD design and prompt')
        finally:
            OpenAISetupDialog.exec=original_setup;QDesktopServices.openUrl=original_open
            w.key.setText(prior_key);w.provider.setCurrentIndex(w.provider.findData(prior_provider));w.ai_settings_toggle.setChecked(False)
        from . import cloud_connection
        import httpx,asyncio,threading
        original_check=cloud_connection.check_access;requests=[];probe=None
        def model_lookup(request):
            requests.append((request.method,str(request.url),len(request.content)))
            return httpx.Response(200,json=dict(id='gpt-6-astra',object='model',created=1,owned_by='openai'))
        try:
            cloud_connection.check_access=lambda api_key,model,**kw:original_check(api_key,model,transport=httpx.MockTransport(model_lookup),**kw)
            probe=OpenAISetupDialog(w,'test-only-not-a-real-api-key','gpt-6-astra');probe.show();app.processEvents();probe.check_button.click()
            check(probe.task is not None and not probe.key.isEnabled(),'connection check runs off the UI thread and freezes checked inputs')
            wait(lambda:probe.task is None)
            check(requests==[('GET','https://api.openai.com/v1/models/gpt-6-astra',0)] and '조회에 성공' in probe.status.toPlainText(),'native connection check retrieves model without generating a design')
            check(probe.use_button.visibleRegion().contains(probe.use_button.rect()) and probe.status.visibleRegion().contains(probe.status.rect()),'connection result keeps result and apply/close controls reachable')
            probe.key.clear();probe.grab().save(str(path.with_name('openai262-check.png')))
            probe.key.setText('test-only-not-a-real-api-key');entered=threading.Event();closed=threading.Event()
            async def stalled(request):
                entered.set()
                try:await asyncio.sleep(60)
                finally:closed.set()
            cloud_connection.check_access=lambda api_key,model,**kw:original_check(api_key,model,transport=httpx.MockTransport(stalled),**kw)
            probe.check_button.click();wait(entered.is_set);probe.reject();wait(closed.is_set)
            check(probe.task is None and w.document.design==before_setup,'closing connection check cancels blocked request and preserves CAD')
        finally:
            cloud_connection.check_access=original_check
            if probe:probe.reject();probe.key.clear();probe.deleteLater()
        w.resize(1180,780);app.processEvents()
        original_drive=JointDriveDialog.exec;before_drive=deepcopy(w.document.design)
        def automatic_drive(dialog):
            dialog.resize(820,600);dialog.show();wait(lambda:dialog.checked is not None)
            check(dialog.joint_filter.currentData()=='ab' and not dialog.apply_button.isEnabled(),'joint drive focuses selection without changing original pose')
            dialog.inputs[('ab','rz')].setValue(30.123456);wait(lambda:dialog.checked is not None)
            check(dialog.checked.mates[0].rz==30.123456,'joint drive keeps entered precision')
            check(dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect()),'joint drive apply remains reachable in compact layout')
            snapshot('joint260-drive-preview',dialog);dialog.accept();return 1
        JointDriveDialog.exec=automatic_drive
        try:w.drive_joints();wait(lambda:not w.busy)
        finally:JointDriveDialog.exec=original_drive
        check(w.document.design['mates'][0]['x']==before_drive['mates'][0]['x'] and w.document.design['parts'][0]==before_drive['parts'][0],'joint motion preserves fixed parent and joint offsets')
        check(len(w.document.journal.path()[-1]['context']['joint_values'])==1,'joint history records only changed motion values')
        key(Qt.Key.Key_Z);check(w.document.design==before_drive,'undo restores original joint pose')
        from .cad_tools import execute_plan
        from ..models import DraftRequest
        from ..kernel import build
        def replay(actions):
            reply=execute_plan(json.dumps(dict(summary='offline CAD tool verification',actions=actions)),DraftRequest(prompt='offline native verification',current=w.document.design))
            w.apply_design(reply.design.model_dump(),'검증된 CAD 작업',{'journal_steps':reply.journal_steps});wait(lambda:not w.busy);return reply
        reply=replay([dict(tool='edit_joint',target='ab',args=dict(rz=45))])
        check(reply.design.mates[0].rz==45 and len(reply.design.mates)==2,'offline AI joint action preserves assembly relationships')
        replay([dict(tool='hole',target='a',args=dict(face='+Z',diameter=8))]);before_hole_edit=deepcopy(w.document.design)
        feature=w.document.design['parts'][0]['features'][-1]['id']
        reply=replay([dict(tool='edit_feature',target='a',args=dict(feature_id=feature,diameter=6))])
        check(abs(build(reply.design)[0].Volume()-(20*20*12-3.141592653589793*9*12))<1e-5,'offline AI feature edit shrinks existing hole to exact requested volume')
        check(len(reply.design.parts[0].features)==1 and reply.design.parts[0].features[0].id==feature,'hole edit retains original feature identity')
        key(Qt.Key.Key_Z);check(w.document.design==before_hole_edit,'undo restores pre-edit hole and assembly')
        from PySide6.QtWidgets import QLineEdit,QPushButton
        precise=deepcopy(w.document.design);precise['parts'][0]['transform']['x']=25.1234567890123;precise['parts'][0]['transform']['rz']=90.1234567890123
        apply(precise);w.select_parts(['a']);app.processEvents();before_properties=deepcopy(w.document.design)
        w.properties.findChild(QLineEdit,'partName').setText('정밀 배치 유지')
        w.properties.findChild(QPushButton,'applyPartProperties').click();wait(lambda:not w.busy)
        check(w.document.design['parts'][0]['transform']==before_properties['parts'][0]['transform'],'renaming preserves untouched full precision placement')
        check(w.document.design['parts'][0]['geometry']==before_properties['parts'][0]['geometry'],'renaming preserves untouched geometry and feature settings')
        key(Qt.Key.Key_Z);check(w.document.design==before_properties,'undo property edit restores original name and precise pose')
        w.start_sketch(g=Extrusion(sketch_mode='entities',entities=[G.line(G.pt(0,0),G.pt(20,0)),G.line(G.pt(20,0),G.pt(20,20))]).model_dump());e=w.editor;wait(lambda:e.preview is not None);e.canvas.setFocus();e.selected={i['id'] for i in e.g['entities']};QTest.keyClick(e.canvas,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier);QTest.keyClick(e.canvas,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);check(len(e.g['entities'])==4,'sketch Ctrl C V duplicates selected geometry');e.create_group('스케치 그룹');e.canvas.setFocus();QTest.keyClick(e.canvas,Qt.Key.Key_G,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier);check(not e.g.get('groups'),'sketch Ctrl Shift G ungroups selected elements');QTest.keyClick(e.canvas,Qt.Key.Key_X,Qt.KeyboardModifier.ControlModifier);check(len(e.g['entities'])==2,'sketch Ctrl X removes selected geometry');w.cancel_sketch()
        from .work_plane import WorkPlaneDialog
        from .extrude import ExtrudeDialog
        original_plane=WorkPlaneDialog.exec;original_extrude=ExtrudeDialog.exec
        def choose_plane(dialog):
            dialog.offset.setValue(80);dialog.fields['ry'].setValue(30);dialog.resize(820,600);dialog.show();wait(lambda:dialog.checked is not None)
            check(dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect()),'work plane apply is reachable in compact native dialog')
            snapshot('workplane260-preview',dialog);dialog.accept();return 1
        WorkPlaneDialog.exec=choose_plane
        try:w.actions['work_plane'].trigger()
        finally:WorkPlaneDialog.exec=original_plane
        check(w.sketching and w.editor.context['work_plane']['offset']==80,'native work plane starts an offset angled sketch')
        plane_context=deepcopy(w.editor.context);geometry=Extrusion(sketch_mode='entities',entities=[G.circle(G.pt(0,0),5)],thickness=8).model_dump()
        w.finish_sketch(geometry,plane_context,'add');wait(lambda:not w.busy);saved=w.document.design['sketches'][-1];plane_sketch=saved['id']
        check(len(saved['geometry']['entities'])==1 and not saved['context'].get('face'),'plane sketch persists without display grid or false face reference')
        volume=w.result['stats']['volume']
        def extrude_plane(dialog):
            dialog.show();wait(lambda:dialog.checked is not None);source=dialog.result['sketches'][0]
            check(abs(source['normal'][0]-.5)<1e-8 and abs(source['origin'][2]-80)<1e-8,'extrusion handle shares exact angled sketch frame')
            dialog.accept();return 1
        ExtrudeDialog.exec=extrude_plane
        try:w.select_sketch(plane_sketch);key(Qt.Key.Key_E,Qt.KeyboardModifier.NoModifier)
        finally:ExtrudeDialog.exec=original_extrude
        shape=build(Design.model_validate(w.document.design))[-1];center=shape.Center()
        check(abs(w.result['stats']['volume']-volume-math.pi*25*8)<1e-5 and abs(center.x-2)<1e-6 and abs(center.z-(80+math.sqrt(3)*2))<1e-6,'angled native extrusion has expected world center and volume')
        snapshot('workplane260-extruded');before_plane_edit=deepcopy(w.document.design)
        def shift_plane(dialog):
            dialog.offset.setValue(100);wait(lambda:dialog.checked is not None);dialog.accept();return 1
        WorkPlaneDialog.exec=shift_plane
        try:w.work_plane_dialog(plane_sketch);wait(lambda:not w.busy)
        finally:WorkPlaneDialog.exec=original_plane
        check(abs(w.document.design['parts'][-1]['transform']['z']-100)<1e-8 and w.document.design['parts'][-1]['geometry']==before_plane_edit['parts'][-1]['geometry'],'plane editing moves dependent extrusion and retains its geometry')
        key(Qt.Key.Key_Z);check(w.document.design==before_plane_edit,'undo restores sketch plane and dependent body together')
        plane_file=path.with_name('work-plane.cad.json');w.document.write(plane_file);loaded=read_project(plane_file)
        check(loaded.design.model_dump()==before_plane_edit,'angled plane and full history reopen with exact geometry')
        check(not errors,'no CAD/UI errors');w.document.dirty=False;w.close();path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc(),ui_errors=errors),ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False
        if w.sketching:w.cancel_sketch()
        w.close();app.exit(1)
