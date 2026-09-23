"""Native inference, reference-boundary points, and sketch re-editing checks."""
import json,time,traceback
from pathlib import Path


def run(app,w,path):
    from PySide6.QtCore import Qt,QPointF
    from PySide6.QtTest import QTest
    from ..models import Design,Part,Extrusion
    from . import geometry as G
    from .sketch_guides import contact_candidates
    from .document import read_project
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);checks=[]
    def check(value,text):
        if not value:raise AssertionError(text)
        checks.append(text)
    def wait(fn):
        end=time.monotonic()+30
        while not fn() and time.monotonic()<end:app.processEvents();QTest.qWait(15)
        check(fn(),'background sketch computation completed')
    try:
        app.setQuitOnLastWindowClosed(False);w.activateWindow()
        for mode in ('tangent','normal'):
            w.start_sketch(g=Extrusion(sketch_mode='entities',entities=[G.circle(G.pt(0,0),10)]).model_dump());e=w.editor;e.free.setChecked(False);wait(lambda:not e.solving and e.preview is not None)
            e.guide_mode.setCurrentIndex(e.guide_mode.findData(mode));e.set_tool('line');e.input_point(G.pt(23,5))
            candidate=next(s for s in contact_candidates(json.dumps(e.g['entities'],sort_keys=True),23,5) if s['constraint']==mode)
            point=e.canvas.world(e.canvas.screen(candidate['p']));e.canvas.cursor=point;e.canvas.update();app.processEvents()
            check(e.canvas.snap and e.canvas.snap.get('constraint')==mode,mode+' contact is recommended')
            e.grab().save(str(path.with_name('sketch-'+mode+'.png')))
            e.input_point(point);e.finish_drawing();wait(lambda:not e.solving and not e.solve_timer.isActive());check(not e.conflicted and any(c['kind']==mode for c in e.g['entity_constraints']),mode+' is persisted without false overconstraint');w.cancel_sketch()
        d=Design(parts=[Part(id='plate',name='참조 면 시험',geometry=dict(kind='plate',length=30,width=30,thickness=10,hole_count=0))]);w.apply_design(d.model_dump(),'참조 부품');wait(lambda:not w.busy);w.select_part('plate')
        face=next(f for f in w.result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.9);w.viewport.face=('plate',face);w.start_face_sketch();e=w.editor;e.free.setChecked(False);e.set_tool('point');e.canvas.scale=20;wait(lambda:not e.solving)
        point=e.canvas.world(e.canvas.screen(G.pt(4.33,15))+QPointF(0,.1));check(e.canvas.snap and e.canvas.snap['ids'][0].startswith('ref-'),'face boundary recommends a point without manual projection')
        e.input_point(point);wait(lambda:not e.solving and not e.solve_timer.isActive());pid=next(p['id'] for p in e.g['entities'] if p['kind']=='point');check(any(c['kind']=='point_on' and c['a']==pid for c in e.g['entity_constraints']),'boundary point has a persistent point-on constraint');e.finish_sketch();wait(lambda:not w.sketching and not w.busy)
        sid=w.selected_sketch;check(bool(sid),'finishing an open point sketch saves it')
        w.activateWindow();w.viewport.widget.setFocus();app.processEvents();QTest.keyClick(w.viewport.widget,Qt.Key.Key_E,Qt.KeyboardModifier.ShiftModifier);check(w.sketching and w.editor.context.get('sketch_id')==sid,'Shift+E reopens the selected saved sketch')
        e=w.editor;wait(lambda:not e.solving and e.preview is not None);e.select_reference(pid,'start');e.refresh_selection()
        field=next(field for address,field,kind in e.property_inputs if address==('position','x'));field.setValue(6.33);e.apply_properties();wait(lambda:not e.solving and not e.solve_timer.isActive());e.grab().save(str(path.with_name('sketch-edit.png')));e.finish_sketch();wait(lambda:not w.sketching and not w.busy)
        sketch=next(s for s in w.document.design['sketches'] if s['id']==sid);point=next(p for p in sketch['geometry']['entities'] if p['id']==pid)
        check(abs(point['position']['x']-6.33)<1e-5 and abs(point['position']['y']-15)<1e-5,'edited point moves along its reference boundary')
        w.document.write(path.with_suffix('.cad.json'));project=read_project(path.with_suffix('.cad.json'));check(len(project.history.entries)>=3,'sketch creation and editing retain history')
        w.document.dirty=False;w.close();path.write_text(json.dumps(dict(success=True,checks=checks),ensure_ascii=False,indent=2),encoding='utf-8');app.quit()
    except Exception:
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc()),ensure_ascii=False,indent=2),encoding='utf-8');w.document.dirty=False
        if w.sketching:w.cancel_sketch()
        w.close();app.exit(1)
