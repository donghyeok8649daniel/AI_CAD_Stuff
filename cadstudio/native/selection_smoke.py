"""Real Qt/VTK checks for selection, grouping, clipboard and joint visibility."""
import json,time,traceback
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
            app.processEvents();QTest.qWait(15)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>deadline:raise TimeoutError('UI wait')
        app.processEvents()
    def apply(data):w.apply_design(data,'선택 테스트',fit=True);wait(lambda:not w.busy)
    def key(code,mods=Qt.KeyboardModifier.ControlModifier):
        w.activateWindow();w.viewport.widget.setFocus();app.processEvents();QTest.keyClick(w.viewport.widget,code,mods);app.processEvents();wait(lambda:not w.busy)
    def snapshot(name):
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        app.processEvents();v=w.viewport;v.window.Render();capture=vtkWindowToImageFilter();capture.SetInput(v.window);capture.ReadFrontBufferOff();capture.Update();writer=vtkPNGWriter();writer.SetFileName(str(path.with_name(name+'-viewport.png')));writer.SetInputConnection(capture.GetOutputPort());writer.Write()
        pix=w.grab();p=QPainter(pix);pos=v.widget.mapTo(w,QPoint(0,0));p.drawImage(QRectF(pos.x(),pos.y(),v.widget.width(),v.widget.height()),QImage(str(path.with_name(name+'-viewport.png'))));p.end();pix.save(str(path.with_name(name+'.png')))
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
        key(Qt.Key.Key_C);key(Qt.Key.Key_V);check(len(w.document.design['parts'])==6 and len(w.selected_parts)==3,'Ctrl C V copies selected assembly')
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
        w.start_sketch(g=Extrusion(sketch_mode='entities',entities=[G.line(G.pt(0,0),G.pt(20,0)),G.line(G.pt(20,0),G.pt(20,20))]).model_dump());e=w.editor;wait(lambda:e.preview is not None);e.canvas.setFocus();e.selected={i['id'] for i in e.g['entities']};QTest.keyClick(e.canvas,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier);QTest.keyClick(e.canvas,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);check(len(e.g['entities'])==4,'sketch Ctrl C V duplicates selected geometry');e.create_group('스케치 그룹');e.canvas.setFocus();QTest.keyClick(e.canvas,Qt.Key.Key_G,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier);check(not e.g.get('groups'),'sketch Ctrl Shift G ungroups selected elements');QTest.keyClick(e.canvas,Qt.Key.Key_X,Qt.KeyboardModifier.ControlModifier);check(len(e.g['entities'])==2,'sketch Ctrl X removes selected geometry');w.cancel_sketch()
        check(not errors,'no CAD/UI errors');w.document.dirty=False;w.close();path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc(),ui_errors=errors),ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False
        if w.sketching:w.cancel_sketch()
        w.close();app.exit(1)
