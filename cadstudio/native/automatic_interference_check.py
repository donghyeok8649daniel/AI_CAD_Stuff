from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import ast,hashlib,json,os,sys,time
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['PYTHONDONTWRITEBYTECODE']='1'
ROOT=Path(__file__).resolve().parent

from cadstudio.models import Design
from cadstudio.automatic_interference import automatic_separation,review_request,design_digest
from cadstudio.interference import exact_collisions
from cadstudio.native.part_display_controls import PartDisplayControls
from cadstudio.native.automatic_interference_dialog import AutomaticInterferenceDialog
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QPushButton,QPlainTextEdit
from PySide6.QtCore import QCoreApplication,QEvent
from vtkmodules.vtkRenderingCore import vtkActor
import cadstudio.native.workflows as workflows

checks=[]
def check(name,condition):
    checks.append(dict(name=name,passed=bool(condition)))
    if not condition:raise AssertionError(name)
def rejected(name,fn,kind=ValueError,contains=''):
    try:fn()
    except kind as exc:check(name,contains in str(exc))
    else:check(name,False)
def fixture(others=()):
    return Design.model_validate(dict(name='AUTO TEST',parts=[dict(id=i,name=i,geometry=dict(kind='plate',length=10,width=10,thickness=2,hole_count=0),transform=dict(x=x)) for i,x in [('a',0),('b',5),*others]])).model_dump()

def run(path):
    raw=fixture([('c',40)]);before=design_digest(raw)
    proposal=automatic_separation(raw,['a','b'])
    check('shortest_tested_axis_selected',abs(proposal['distance_mm']-2.2)<1e-6)
    check('actual_solids_selected_pair_clear_no_new_overlap',proposal['exact_selected_pair_clear'] and not proposal['collisions'] and not exact_collisions(Design.model_validate(proposal['candidate'])))
    check('input_unmodified',before==design_digest(raw))
    check('all_nonplacement_fields_preserved',all({k:v for k,v in a.items() if k!='transform'}=={k:v for k,v in b.items() if k!='transform'} for a,b in zip(raw['parts'],proposal['candidate']['parts'])))
    fixed=deepcopy(raw);fixed['parts'][0]['fixed']=True
    p=automatic_separation(fixed,['a','b'])
    check('fixed_side_auto_selects_other',p['part_id']=='b' and p['candidate']['parts'][0]==fixed['parts'][0])
    fixed['parts'][1]['fixed']=True
    rejected('both_fixed_not_unlocked',lambda:automatic_separation(fixed,['a','b']),contains='고정')
    attached=deepcopy(raw);attached['mates']=[dict(id='ac',kind='rigid',parent='a',child='c',x=40)]
    attached=Design.model_validate(attached).model_dump();p=automatic_separation(attached,['a','b'],moving='a')
    check('connected_component_preserved',p['moved_ids']==['a','c'] and p['candidate']['mates']==attached['mates'] and p['candidate']['parts'][2]['transform']['x']-p['candidate']['parts'][0]['transform']['x']==40)
    linked=deepcopy(raw);linked['mates']=[dict(id='ab',kind='rigid',parent='a',child='b',x=5)]
    rejected('internal_assembly_not_separated',lambda:automatic_separation(linked,['a','b']),contains='같은 조립')
    obstacle=fixture([('c',-10)])
    p=automatic_separation(obstacle,['a','b'],moving='a',axes='x')
    check('closer_candidate_causing_third_overlap_rejected',p['translation'][0]>15 and any(a['status']=='rejected' and a['blocked'] for a in p['attempts']))
    blocked=fixture([('c',-10),('d',15)])
    rejected('all_candidates_blocked_keep_original',lambda:automatic_separation(blocked,['a','b'],moving='a',axes='x'),contains='設計' if False else '설계는 그대로')
    rejected('max_distance_respected',lambda:automatic_separation(raw,['a','b'],max_distance=1),contains='최대 이동')
    rejected('nan_limit_rejected',lambda:automatic_separation(raw,['a','b'],max_distance=float('nan')))
    rejected('boolean_clearance_rejected',lambda:automatic_separation(raw,['a','b'],clearance=True))
    rejected('missing_pair_rejected',lambda:automatic_separation(raw,['a','none']))
    rejected('same_pair_rejected',lambda:automatic_separation(raw,['a','a']))
    counts=[0]
    def cancel():
        counts[0]+=1
        if counts[0]==4:raise RuntimeError('cancelled')
    rejected('cooperative_cancel_no_candidate',lambda:automatic_separation(raw,['a','b'],check=cancel),RuntimeError,'cancelled')
    request=review_request(raw,proposal['candidate'],proposal)
    check('advice_request_exact_candidate_binding',request.current.model_dump()==proposal['candidate'] and proposal['candidate_digest'] in request.prompt)
    bad=deepcopy(proposal['candidate']);bad['parts'][0]['name']='changed'
    rejected('stale_advice_request_rejected',lambda:review_request(raw,bad,proposal))
    app=QApplication.instance() or QApplication([])
    class View(QWidget):
        def __init__(self):
            super().__init__();QVBoxLayout(self);self.actors={i:(vtkActor(),vtkActor()) for i in 'abc'};self.hidden=set();self.part_opacities={};self.closed=False
        def set_hidden_parts(self,ids,*args):self.hidden=set(ids)
        def set_part_opacity(self,ids,value,**kwargs):
            for i in ids:
                if value==1:self.part_opacities.pop(i,None)
                else:self.part_opacities[i]=value
        def reset_part_opacity(self,**kwargs):self.part_opacities={}
        def load(self,result,*args):self.actors={m['id']:(vtkActor(),vtkActor()) for m in result['meshes']}
        def select_many(self,ids):pass
        def render(self):pass
        def shutdown(self):self.closed=True
    class Window(QWidget,PartDisplayControls):
        def __init__(self):
            super().__init__();self.viewport=View();self.chosen=['a'];self.busy=False;self.sketching=False;self.document=SimpleNamespace(design=deepcopy(raw));self.codex_config=dict(model='test-model',executable='test-exe');self.codex_catalog=[]
            self.make_display_strip()
        def selected_ids(self):return self.chosen
        def select_parts(self,ids):self.chosen=ids;self.update_display_strip()
        def reset_role_view(self):pass
        def sync_tree_visibility(self):pass
        def sync_tree_selection(self):pass
        def message(self,text):pass
    window=Window();strip=window.display_strip;window.viewport.show();strip.resize(460,40);strip.show();app.processEvents()
    check('hide_opacity_restore_visible_strip',all(strip.findChild(QWidget,n).isVisible() for n in ('selectedPartHide','selectedPartOpacity','selectedPartRestore','hiddenPartsPicker')))
    strip.findChild(QPushButton,'selectedPartHide').click()
    check('one_click_hide_and_hidden_count',window.viewport.hidden=={'a'} and '1' in window.display_hidden_button.text())
    window.set_selected_opacity(.35);window.chosen=['b'];window.set_selected_opacity(.6);window.chosen=['a'];window.restore_selected_part_display()
    check('selection_restore_preserves_other_opacity',not window.viewport.hidden and window.viewport.part_opacities=={'b':.6})
    window.viewport.hidden.add('c');window.restore_temporary_part_display()
    check('restore_all_only_touched_unrelated_manual_hidden_kept',window.viewport.hidden=={'c'} and not window.viewport.part_opacities)
    check('display_controls_do_not_change_document',window.document.design==raw)
    window.busy=True;window.update_display_strip();check('display_busy_inputs_disabled',all(not w.isEnabled() for w in window.display_strip_buttons))
    window.busy=False;window.select_parts([]);check('no_selection_controls_disabled',not window.display_strip_buttons[0].isEnabled())
    old=workflows.CADViewport;workflows.CADViewport=View
    try:
        dialog=AutomaticInterferenceDialog(window,raw,'a',['a','b'])
        check('opening_dialog_never_auto_starts_search',not dialog.running and dialog.checked is None and not dialog.timer.isActive())
        result=dialog.checked_compute(dialog.candidate(),dialog.revision)
        dialog.checked,dialog.result,dialog.interference,dialog.travel=result;dialog.viewport.load(dialog.result);dialog.apply_button.setEnabled(True);dialog.present();dialog.present_interference()
        check('automatic_result_exact_preview_allows_apply',dialog.apply_button.isEnabled() and dialog.proposal and not dialog.interference['blocked'])
        # Exercise actual subscribed review routing with a fake transport function,
        # avoiding account/network usage in validation.
        import cadstudio.native.ai_chat as chat
        old_answer=chat.answer;calls=[]
        def answer(request,provider,model,**kwargs):
            calls.append(dict(provider=provider,model=model,request=request,kwargs=kwargs));return '자문: 장착 위치와 전체 구동 범위를 확인하세요.'
        chat.answer=answer
        try:
            dialog.review();end=time.monotonic()+5
            while dialog.advice_task and time.monotonic()<end:app.processEvents();time.sleep(.01)
            check('AI_double_check_uses_codex_subscription_only',len(calls)==1 and calls[0]['provider']=='codex' and 'api_key' not in calls[0]['kwargs'] and calls[0]['request'].current.model_dump()==dialog.checked.model_dump())
            check('AI_advisory_visible_plain_text_no_geometry_mutation','장착 위치' in dialog.advice.toPlainText() and window.document.design==raw)
        finally:chat.answer=old_answer
        dialog.max_distance.setValue(1)
        check('changed_search_settings_invalidate_checked_and_advice',dialog.checked is None and dialog.proposal is None and not dialog.apply_button.isEnabled() and not dialog.advice.toPlainText())
        check('stale_timer_does_not_restart_search',not dialog.search_requested and not dialog.running)
        dialog.reject();dialog.deleteLater()
    finally:workflows.CADViewport=old
    from cadstudio.native.window import MainWindow
    work_code=next(c for c in MainWindow.apply_design.__code__.co_consts if hasattr(c,'co_name') and c.co_name=='work')
    check('commit_requires_full_and_selected_pair_recheck',{'require_clear','require_selected_clear'}<=set(work_code.co_names))
    if getattr(sys,'frozen',False):
        from cadstudio import program_simulation
        from cadstudio.program_drive_provenance import assert_trace_producer
        check('fresh_frozen_motor_provenance_preserved',assert_trace_producer(program_simulation,program_simulation.simulate_program)['mode']=='verified_frozen_bundle')
    window.close();window.deleteLater();strip.close();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    Path(path).write_text(json.dumps(dict(success=True,count=len(checks),checks=checks,scope='new small exact CAD and offscreen widget delta; no native MainWindow/VTK GPU acceptance, no actual Codex call'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(success=True,count=len(checks))))

if __name__=='__main__':
    try:run(sys.argv[1] if len(sys.argv)>1 else ROOT/'source-check.json')
    except BaseException:
        raise
