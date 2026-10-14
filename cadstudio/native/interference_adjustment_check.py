"""New pair-adjustment checks with three small solids and offscreen widgets.
No prior large CAD/kernel/CG/electrical check suite is repeated.
"""
from pathlib import Path
import ast,json,os,sys,hashlib
from copy import deepcopy
from types import SimpleNamespace
from contextlib import contextmanager
import importlib
class patch:
    def __init__(self,target,value):
        module,name=target.rsplit('.',1);self.obj=importlib.import_module(module);self.name=name;self.value=value
    def __enter__(self):self.prior=getattr(self.obj,self.name);setattr(self.obj,self.name,self.value);return self
    def __exit__(self,*args):setattr(self.obj,self.name,self.prior)
    @staticmethod
    @contextmanager
    def object(obj,name,value):
        prior=getattr(obj,name);setattr(obj,name,value)
        try:yield
        finally:setattr(obj,name,prior)
OWN=Path('C:\\Users\\keidi\\Documents\\Codex\\2026-09-22\\prompt-cad-studio\\work\\interference-adjust317')
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QDialog,QLabel
from PySide6.QtCore import QCoreApplication,QEvent
from cadstudio.models import Design
from cadstudio.interference_adjustment import separation_suggestion,selected_overlap,require_selected_clear
from cadstudio.interference import exact_collisions
from cadstudio.placement import move_selection
from cadstudio.kernel import build,exact_bounds,KERNEL_LOCK
from cadstudio.native.interference_adjustment import InterferenceMoveDialog,InterferenceDimensionDialog
from cadstudio.native.inspect_tools import InterferenceDialog
from cadstudio.native.window import MainWindow
from vtkmodules.vtkRenderingCore import vtkActor

def run(report_path=None):
    report_path=Path(report_path or OWN/'source-check.json');report=[]
    def check(name,ok):
        report.append(dict(name=name,passed=bool(ok)))
        if not ok:raise AssertionError(name)
    def rejects(name,fn,text=None):
        try:fn()
        except ValueError as exc:check(name,text is None or text in str(exc))
        else:check(name,False)
    def fingerprint(v):return hashlib.sha256(json.dumps(v,sort_keys=True,allow_nan=False).encode()).hexdigest()
    raw=Design.model_validate({'name':'SYNTHETIC INTERFERENCE','parts':[
       {'id':pid,'name':pid,'geometry':{'kind':'plate','length':10,'width':10,'thickness':2,'hole_count':0},'transform':{'x':x}}
       for pid,x in [('a',0),('b',5),('c',40)]]}).model_dump()
    before=fingerprint(raw)
    with KERNEL_LOCK:
        shapes=build(Design.model_validate(raw));bounds={}
        for p,s in zip(raw['parts'],shapes):
            box=exact_bounds(s);bounds[p['id']]={'min':[getattr(box,k+'min') for k in 'xyz'],'max':[getattr(box,k+'max') for k in 'xyz']}
    check('small_fixture_actual_overlap100',abs(selected_overlap(exact_collisions(Design.model_validate(raw),shapes),['a','b'])-100)<1e-6)
    for axis in 'xyz':
        for direction in (-1,1):
            proposal=separation_suggestion(raw,bounds,'a','b',axis,direction)
            moved,ids=move_selection(raw,['a'],proposal['translation'])
            collisions=exact_collisions(Design.model_validate(moved))
            check('six_directions_exact_clear_'+axis+str(direction),selected_overlap(collisions,['a','b'])==0 and ids==['a'])
    zero=separation_suggestion(raw,bounds,'a','b','x',-1,0)
    check('zero_clearance_means_contact_candidate',zero['translation'][0]==-5 and not zero['exact_clearance_verified'])
    rejects('boolean_clearance_rejected',lambda:separation_suggestion(raw,bounds,'a','b','x',1,True))
    bad=deepcopy(bounds);bad['a']['min'][0]=float('nan')
    rejects('nonfinite_bounds_rejected',lambda:separation_suggestion(raw,bad,'a','b','x',1))
    rejects('same_target_rejected',lambda:separation_suggestion(raw,bounds,'a','a','x',1))
    linked=deepcopy(raw);linked['mates']=[{'id':'ab','kind':'rigid','parent':'a','child':'b','x':5}]
    rejects('same_connected_pair_not_unlocked',lambda:separation_suggestion(linked,bounds,'a','b','x',-1),'같은 조립')
    rejects('crossing_mates_connected_off_rejected',lambda:separation_suggestion(linked,bounds,'a','b','x',-1,connected=False),'구속')
    group=deepcopy(raw);group['part_groups']=[{'id':'group','name':'same group','part_ids':['a','b']}]
    check('group_does_not_hide_overlap',selected_overlap(exact_collisions(Design.model_validate(group)),['a','b'])>0)
    attached=deepcopy(raw);attached['mates']=[{'id':'ac','kind':'rigid','parent':'a','child':'c','x':40}]
    p=separation_suggestion(attached,bounds,'a','b','y',-1)
    moved,ids=move_selection(attached,['a'],p['translation'])
    check('connected_members_and_mates_preserved',ids==['a','c'] and moved['mates']==Design.model_validate(attached).model_dump()['mates'])
    check('connected_internal_offset_preserved',abs(moved['parts'][2]['transform']['x']-moved['parts'][0]['transform']['x']-40)<1e-7)
    fixed=deepcopy(raw);fixed['parts'][0]['fixed']=True
    rejects('fixed_part_never_auto_unlocked',lambda:move_selection(fixed,['a'],[-5.2,0,0]),'고정')
    rejects('selected_partial_overlap_cannot_commit',lambda:require_selected_clear([{'a':'a','b':'b','volume':1}],['a','b']))
    rejects('invalid_overlap_volume_cannot_commit',lambda:require_selected_clear([{'a':'a','b':'b','volume':float('nan')}],['a','b']))
    app=QApplication.instance() or QApplication([])
    class View(QWidget):
        def __init__(self):
            super().__init__();QVBoxLayout(self);self.actors={};self.renderer=SimpleNamespace(AddActor=lambda a:None);self.closed=False
        def load(self,result,*args):self.actors={m['id']:(vtkActor(),vtkActor()) for m in result['meshes']}
        def select_many(self,ids):pass
        def render(self):pass
        def shutdown(self):self.closed=True
    def evaluate(dialog):
        dialog.timer.stop();out=dialog.checked_compute(dialog.candidate(),dialog.revision)
        dialog.checked,dialog.result,dialog.interference,dialog.travel=out
        dialog.viewport.load(dialog.result);dialog.apply_button.setEnabled(True);dialog.present();dialog.present_interference();return out
    with patch('cadstudio.native.workflows.CADViewport',View):
        d=InterferenceMoveDialog(None,raw,'a',['a','b'],bounds);d.timer.stop()
        check('default_connected_true_grounded_false',d.connected.isChecked() and not d.grounded.isChecked())
        d.fields['x'].setValue(-1);evaluate(d)
        check('partial_reduction_preview_blocks_apply',not d.apply_button.isEnabled() and selected_overlap(d.result['stats']['collisions'],['a','b'])>0)
        d.suggest('x',-1);evaluate(d)
        check('clear_suggestion_preview_allows_apply',d.apply_button.isEnabled() and selected_overlap(d.result['stats']['collisions'],['a','b'])==0)
        d.fields['x'].setValue(35);evaluate(d)
        check('new_third_part_overlap_blocks_apply',not d.apply_button.isEnabled() and d.interference['blocked'])
        d.reject();check('cancel_does_not_change_source',fingerprint(raw)==before and d.viewport.closed)
        dimbase=deepcopy(raw);dimbase['parts'][1]['transform']['x']=8
        dim=InterferenceDimensionDialog(None,dimbase,'a',['a','b']);dim.timer.stop()
        check('no_initial_dimension_change',dim.changed_dimensions()=={} and fingerprint(dim.candidate())==fingerprint(dimbase))
        dim.inputs['length'].setValue(4);evaluate(dim)
        check('dimension_preview_resolves_selected_pair',dim.apply_button.isEnabled() and selected_overlap(dim.result['stats']['collisions'],['a','b'])==0)
        check('only_explicit_dimension_changed',dim.changed_dimensions()=={'length':4} and dim.candidate()['parts'][0]['geometry']['width']==10 and dim.candidate()['parts'][1:]==dimbase['parts'][1:])
        dim.reject()
    with patch('cadstudio.native.inspect_tools.CADViewport',View):
        data={'meshes':[{'id':p['id'],'name':p['name']} for p in raw['parts']],'interference_bounds':bounds}
        overlaps=[{'a':'a','b':'b','volume':100.,'vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[(0,1,2)]}]
        inspector=InterferenceDialog(None,data,overlaps)
        check('inspector_default_target_a_and_actions',inspector.adjust_part.currentData()=='a' and inspector.move_button.isEnabled() and inspector.size_button.isEnabled())
        inspector.adjust_part.setCurrentIndex(1);inspector.request_adjustment('move')
        check('inspector_explicit_part_B_request',inspector.adjust_request['part_id']=='b' and inspector.adjust_request['pair']==['a','b'] and inspector.viewport.closed)
        empty=InterferenceDialog(None,data,[])
        check('no_overlap_actions_disabled',not empty.move_button.isEnabled() and empty.adjust_request is None);empty.reject()
    # Test actual dispatch method: no MainWindow, user document or renderer.
    class Host:
        busy=False;sketching=False
        def __init__(self):self.document=SimpleNamespace(design=raw);self.commits=[];self.selected=None
        def reset_role_view(self):pass
        def select_parts(self,ids):self.selected=ids
        def message(self,text):self.last_message=text
        def show_error(self,text):raise AssertionError(text)
        def apply_design(self,*args,**kwargs):self.commits.append((args,kwargs))
    h=Host()
    class Accepted:
        def __init__(self,*args):self.checked=Design.model_validate(raw);self.moved_ids=['a']
        def exec(self):return QDialog.DialogCode.Accepted
        def candidate(self):return {'raw':raw,'translation':[-5.2,0,0]}
    with patch('cadstudio.native.interference_adjustment.InterferenceMoveDialog',Accepted):
        MainWindow.adjust_interference(h,{'mode':'move','part_id':'a','pair':['a','b'],'bounds':bounds})
    check('actual_dispatch_uses_checked_design_pair_context',len(h.commits)==1 and h.commits[0][0][2]['tool']=='interference-adjustment' and h.commits[0][0][2]['pair']==['a','b'])
    check('actual_dispatch_rechecks_after_commit',callable(h.commits[0][1]['after']))
    tree=ast.parse((OWN/'source/cadstudio/native/window.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    apply=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='apply_design')
    check('commit_defense_rechecks_global_and_selected_pair','require_clear(d, baseline' in ast.unparse(apply) and 'require_selected_clear' in ast.unparse(apply))
    check('final_fixture_and_other_project_data_unchanged',fingerprint(raw)==before)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    result={'success':True,'checks':len(report),'results':report,'scope':'new pair-adjustment paths; three small synthetic solids and offscreen widget/dispatch tests',
            'native_inputs':0,'native_visible_windows':0,'GPU_render':0,'whole_project_kernel_or_history_replay':0,'original_projects_changed':0,'paid_calls':0}
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'success':True,'checks':len(report)}));return 0


