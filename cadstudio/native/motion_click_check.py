"""Narrow real Qt signal regression; inert viewport, no CAD kernel or windows."""
from copy import deepcopy
from pathlib import Path
import json, os, sys, threading

def run(report_path, *, baseline=False):
    from PySide6.QtWidgets import QApplication,QWidget,QPushButton
    from PySide6.QtCore import QEvent,Qt
    from PySide6.QtTest import QTest
    from ..models import Design,Part
    from ..automatic_interference import design_digest
    from . import motion_playback_dialog as module
    from .. import __version__,__build_id__
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    class InertViewport(QWidget):
        def __init__(self):
            super().__init__();self.closed=False;self.actors={};self.loads=[]
        def render(self):pass
        def shutdown(self):self.closed=True
        def load(self,data):self.loads.append(data)
    original_viewport=module.CADViewport
    original_hook=sys.excepthook
    module.CADViewport=InertViewport
    errors=[];checks=[];dialog=None
    sys.excepthook=lambda kind,value,tb:errors.append(dict(type=kind.__name__,message=str(value)))
    def check(name,condition,**details):
        checks.append(dict(name=name,passed=bool(condition),**details))
        if not condition:raise AssertionError(name)
    starts=(0,0,0,0)
    raw=Design(name='Owned four joint signal fixture',
        parts=[Part(id=key,name=key,fixed=key=='base',geometry=dict(kind='cylinder',diameter=5,height=5))
               for key in ['base','rotor1','rotor2','rotor3','rotor4']],
        mates=[dict(id='D_rev_'+str(i+1),kind='revolute',parent='base',child='rotor'+str(i+1),
                    x=20*(i+1),rz=angle,limits={'rz':[-360,360]}) for i,angle in enumerate(starts)]).model_dump()
    current=deepcopy(raw);before=deepcopy(raw)
    try:
        dialog=module.MotionPlaybackDialog(None,raw,document_provider=lambda:current)
        controls=[b for b in dialog.findChildren(QPushButton) if b.text() in ('CW −360°','CCW +360°')]
        check('exact_four_joints_eight_real_QPushButtons',len(dialog.rows)==4 and len(controls)==8)
        check('open_starts_idle_RPM0_no_worker_no_playback',dialog.rpm.value()==0 and dialog.compiled is None and not dialog.runner.busy and not dialog.timer.isActive() and not dialog.play_button.isEnabled())
        def reset():
            for mid,(selected,field,start) in dialog.rows.items():selected.setChecked(False);field.setValue(start)
            errors.clear()
        if baseline:
            failures=[]
            for index,target in enumerate(controls):
                reset();target.click();app.processEvents()
                failures.append(dict(mate_id='D_rev_'+str(index//2+1),button=target.text(),errors=deepcopy(errors),
                                     unchanged=all(not selected.isChecked() and field.value()==start for selected,field,start in dialog.rows.values())))
            check('baseline_all_eight_real_clicks_reproduce_KeyErrorFalse',all(row['errors']==[{'type':'KeyError','message':'False'}] and row['unchanged'] for row in failures))
            result=dict(success=True,baseline=True,failures=failures,checks=checks)
        else:
            for signal_kind in ('click_false','click_checked_true'):
                for index,target in enumerate(controls):
                    reset();mid='D_rev_'+str(index//2+1);delta=-360 if index%2==0 else 360
                    if signal_kind=='click_false':target.click()
                    else:
                        target.setCheckable(True);target.setChecked(False);target.click();target.setCheckable(False)
                    app.processEvents()
                    selected,field,start=dialog.rows[mid]
                    check(signal_kind+'_'+mid+'_'+('CW' if delta<0 else 'CCW'),not errors and selected.isChecked() and field.value()==start+delta
                          and all(not s.isChecked() and f.value()==v for key,(s,f,v) in dialog.rows.items() if key!=mid)
                          and not dialog.runner.busy and not dialog.timer.isActive() and dialog.compiled is None,
                          end_degrees=field.value(),signal_bool=signal_kind=='click_checked_true')
            for index,(mid,(selected,field,start)) in enumerate(dialog.rows.items()):
                reset();selected.setChecked(True);target=start+360
                field.lineEdit().selectAll();QTest.keyClicks(field.lineEdit(),str(target));QTest.keyClick(field.lineEdit(),Qt.Key.Key_Return)
                app.processEvents();manual=field.value();reset();controls[index*2+1].click();app.processEvents()
                check('manual_keyboard_matches_CCW_'+mid,manual==target==field.value() and not errors and not dialog.runner.busy)
            reset();selected,field,start=dialog.rows['D_rev_1'];field.setRange(-90,90)
            controls[0].click();app.processEvents()
            check('full_turn_respects_existing_limit_without_unlock',not errors and field.minimum()==-90 and field.maximum()==90 and field.value()==start and not selected.isChecked())
            field.setRange(-360,360)
            current['name']='Changed during owned review';selected.setChecked(True);dialog.compile()
            check('stale_document_blocks_explicit_compile_without_worker',dialog.ticket is None and dialog.compiled is None and not dialog.runner.busy and not dialog.timer.isActive())
            ticket=module._Ticket(dialog.revision,deepcopy(raw),[],threading.Event());dialog.ticket=ticket
            dialog.ready(ticket,{'samples':1,'step_degrees':2,'preview':{'must_not_load':True}})
            check('stale_result_discarded_without_viewport_load',dialog.compiled is None and not dialog.viewport.loads)
            check('buttons_and_manual_fields_preserve_document',raw==before and dialog.base==before and design_digest(raw)==dialog.input_digest)
            if getattr(sys,'frozen',False):
                from ..program_drive_provenance import assert_trace_producer
                from .. import program_simulation
                binding=assert_trace_producer(program_simulation,program_simulation.simulate_program)
                check('new_frozen_signed_proof_matches_exact_build',binding['mode']=='verified_frozen_bundle' and binding['build_id']==__build_id__)
            result=dict(success=True,checks=checks)
        result.update(count=len(checks),version=__version__,build_id=__build_id__,frozen=bool(getattr(sys,'frozen',False)),
                      pid=os.getpid(),offscreen_real_Qt_signals=True,inert_viewport=True,native_mainwindow_acceptance=False,
                      geometry_calls=0,worker_runs=0,hardware_IO=False,live_AI=0,document_writes=0)
    finally:
        if dialog is not None:
            dialog.reject();check('owned_runner_pool_quiescent',dialog.runner.pool.activeThreadCount()==0)
            dialog.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
        module.CADViewport=original_viewport;sys.excepthook=original_hook
    result['count']=len(checks)
    with Path(report_path).open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    return 0
