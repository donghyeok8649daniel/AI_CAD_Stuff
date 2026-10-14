"""Focused new display/filter/print tests. No old whole-project geometry or UI."""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import contextmanager
class patch:
    @staticmethod
    @contextmanager
    def object(obj,name,value):
        prior=getattr(obj,name);setattr(obj,name,value)
        try:yield
        finally:setattr(obj,name,prior)

OWN=Path('C:\\Users\\keidi\\Documents\\Codex\\2026-09-22\\prompt-cad-studio\\work\\render-controls316-package')
os.environ['QT_QPA_PLATFORM']='offscreen'
from cadstudio.role_memberships import role_memberships
from cadstudio.printing import print_exclusions,prepare_print_plates,export_print_stl
from cadstudio.native.role_view import confirmed_display_roles,RoleViewUI
from cadstudio.native.viewport import CADViewport
from cadstudio.native.part_display_controls import PartDisplayControls
from cadstudio.native.display_overrides import surviving_opacities
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QSpinBox,QVBoxLayout,QCheckBox,QComboBox
from vtkmodules.vtkRenderingCore import vtkActor


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def run(report_path):
    results=[]
    def check(name,value,detail=None):
        results.append({'name':name,'pass':bool(value),'detail':detail})
        if not value:raise AssertionError(name)
    raw={'name':'SYNTHETIC_PRINT_FIXTURE','parts':[],'bom':{'id':'bom_'+'a'*20,'source_name':'fixture.csv','source':'fixture.csv',
         'source_sha256':'a'*64,'format':'csv','items':[],'warnings':[]}}
    for index,(pid,role) in enumerate([('frame','structure'),('motor','transmission'),('board','electrical'),('bolt','structure'),('nut','structure'),('pin','structure')]):
        part={'id':pid,'name':pid,'geometry':{'kind':'plate','length':4,'width':4,'thickness':1,'hole_count':0},'role':role,
              'color':'#F2F2F2','transform':{'x':index*10,'y':0,'z':0,'rx':0,'ry':0,'rz':0}}
        if pid=='motor':part['bom']={'document_id':'bom_'+'a'*20,'item_id':'m','source_sha256':'a'*64}
        if pid in ('bolt','nut','pin'):
            part['mechanical_function']='fastener'
            part['product']={'name':pid,'specs':[{'label':'fastener_type','value':'retaining_pin' if pid=='pin' else pid}]}
        raw['parts'].append(part)
    raw['bom']['items']=[{'id':'m','name':'fixture motor','quantity':1,'source_row':1,'raw_fields':{'Component ID':'MOTOR'}}]
    before=digest(raw)
    memberships=role_memberships(raw)
    check('motor_has_both_memberships',memberships['motor']==frozenset(('electrical','transmission')))
    check('frame_not_electrical',memberships['frame']==frozenset(('structure',)))
    check('names_colors_not_motor_inference',not role_memberships({'parts':[{'id':'x','name':'Motor','color':'#FFD400'}]})['x'])
    declared=deepcopy(raw);declared['electrical']={'components':[{'id':'motor_c','part_id':'motor','kind':'motor'}]}
    check('linked_motor_primary_color_role_retained',confirmed_display_roles(declared)['motor']=='transmission')
    declared['electrical']['components'].append({'id':'frame_c','part_id':'frame','kind':'mcu'})
    check('other_conflicting_color_role_stays_neutral',confirmed_display_roles(declared)['frame']=='unspecified')
    stale=deepcopy(raw);stale['parts'][1]['bom']['source_sha256']='b'*64
    check('stale_BOM_not_motor_evidence',role_memberships(stale)['motor']==frozenset(('transmission',)))
    source=OWN.parent/'urc-electrical-ui314/data/URC2027_D2_electrical_candidate.pcad'
    current=json.loads(source.read_text(encoding='utf-8'))['design'];current_before=digest(current)
    actual=role_memberships(current)
    check('D2_declared_MOTOR4_dual_no_project_edit',all({'electrical','transmission'}<=actual['motor_'+str(i)] for i in range(1,5)) and digest(current)==current_before)
    chosen=set(memberships)
    check('no_filter_keeps_selection',print_exclusions(raw,chosen)==[])
    check('electrical_filter_excludes_motor_and_board',[r['id'] for r in print_exclusions(raw,chosen,exclude_electrical=True)]==['board','motor'])
    check('bolt_nut_filter_excludes_only_bolt_nut',[r['id'] for r in print_exclusions(raw,chosen,exclude_fasteners=True)]==['bolt','nut'])
    check('both_filters_union_no_duplicate',[r['id'] for r in print_exclusions(raw,chosen,exclude_fasteners=True,exclude_electrical=True)]==['board','bolt','motor','nut'])
    try:print_exclusions(raw,chosen,exclude_electrical=1)
    except ValueError:check('nonbool_exclusion_rejected',True)
    else:check('nonbool_exclusion_rejected',False)
    # New actual small geometry/export check: 6 simple4x4x1mm bodies, retain
    # frame+retaining pin only. Not the250/248 models or whole QA repeated.
    plates,previews,warnings=prepare_print_plates(raw,list(chosen),bed=(80,80,50),gap=5,
       exclude_fasteners=True,exclude_electrical=True)
    check('real_small_print_geometry_excluded_IDS',len(plates)==1 and {p.id for p in plates[0].parts}=={'frame','pin'})
    output=Path(report_path).with_suffix('').with_name(Path(report_path).stem+'-output');output.mkdir(exist_ok=False)
    export_print_stl(plates[0],output/'filtered.stl',tolerance=.1)
    # STL is a mesh, so read the ASCII/binary triangle data independently below.
    stl=(output/'filtered.stl').read_bytes()
    import struct
    count=struct.unpack_from('<I',stl,80)[0]
    vertices=[]
    for i in range(count):
        row=struct.unpack_from('<12fH',stl,84+i*50)
        vertices.extend([row[3:6],row[6:9],row[9:12]])
    check('STL_has_two_plate_meshes_only',count==24 and len(stl)==84+50*count)
    check('STL_bed_placement_bottom0',abs(min(p[2] for p in vertices))<1e-6)
    check('print_does_not_mutate_source',digest(raw)==before)
    try:prepare_print_plates(raw,['motor','board'],exclude_electrical=True)
    except ValueError as exc:check('all_excluded_clear_error','제외 후 출력할 부품이 없습니다' in str(exc))
    else:check('all_excluded_clear_error',False)
    # CPU actors; no viewport/renderer/window initialization, no GPU render.
    class View:
        def __init__(self):
            self.actors={pid:(vtkActor(),vtkActor()) for pid in ['frame','other']}
            self.hidden={'other'};self.show_edges=True;self.selected_ids={'frame'};self.part_opacities={};self.closed=False;self.render_calls=0
        def render(self):self.render_calls+=1
        def rebuild_pick_objects(self):pass
        def set_hidden_parts(self,ids,render=True):CADViewport.set_hidden_parts(self,ids,render)
        def set_part_opacity(self,ids,value,render=True):CADViewport.set_part_opacity(self,ids,value,render)
        def reset_part_opacity(self,render=True):CADViewport.reset_part_opacity(self,render)
    v=View();v.set_part_opacity(['frame'],.35)
    check('opacity_sets_body_and_edge_CPU_properties',all(a.GetProperty().GetOpacity()==.35 for a in v.actors['frame']))
    check('opacity_keeps_hidden_and_other_properties',v.hidden=={'other'} and v.actors['other'][0].GetProperty().GetOpacity()==1.)
    v.reset_part_opacity();check('opacity_reset100',v.part_opacities=={} and v.actors['frame'][0].GetProperty().GetOpacity()==1.)
    for bad in [0,-1,2,float('nan'),True]:
        try:v.set_part_opacity(['frame'],bad)
        except ValueError:check('invalid_opacity_'+repr(bad),True)
        else:check('invalid_opacity_'+repr(bad),False)
    check('opacity_prunes_deleted_part_IDS',surviving_opacities({'frame':.35,'gone':.4},['frame'])=={'frame':.35})
    v.closed=True;v.set_part_opacity(['frame'],.35);check('closed_viewport_no_actor_touch',v.part_opacities=={})
    v.closed=False
    app=QApplication.instance() or QApplication([])
    class Host(QWidget,PartDisplayControls):
        def __init__(self):
            super().__init__();self.viewport=v;self.document=SimpleNamespace(design=raw,dirty=True,journal={'entries':['unchanged']})
            self._selected=['frame'];self.selection_sync=0;self.tree_sync=0
        def selected_ids(self):return self._selected
        def reset_role_view(self):pass
        def sync_tree_visibility(self):self.tree_sync+=1
        def sync_tree_selection(self):self.selection_sync+=1
        def message(self,text):self.last_message=text
    h=Host();doc_before=digest(h.document.__dict__)
    h.hide_selected_temporarily();check('selected_hide_temporary',v.hidden=={'frame','other'} and not v.actors['frame'][0].GetVisibility())
    h.show_selected_temporarily();check('selected_show_keeps_previous_hidden',v.hidden=={'other'})
    def cancel(dialog):dialog.findChild(QSpinBox).setValue(35);return QDialog.DialogCode.Rejected
    with patch.object(QDialog,'exec',cancel):h.selected_opacity_dialog()
    check('opacity_dialog_cancel_restores_previous',v.actors['frame'][0].GetProperty().GetOpacity()==1.)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def accept(dialog):dialog.findChild(QSpinBox).setValue(35);return QDialog.DialogCode.Accepted
    with patch.object(QDialog,'exec',accept):h.selected_opacity_dialog()
    check('opacity_dialog_accept_keeps35',v.actors['frame'][0].GetProperty().GetOpacity()==.35)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    h.restore_temporary_part_display();check('restore_original_hidden_and_opacity',v.hidden=={'other'} and not v.part_opacities)
    check('display_controls_no_Document_or_color_edits',digest(h.document.__dict__)==doc_before and digest(raw)==before)
    layout=QVBoxLayout(h);h.add_part_display_buttons(layout)
    check('property_buttons_available',all(h.findChild(QWidget,n) for n in ['partTemporaryHide','partTemporaryShow','partTemporaryOpacity']))
    # Build only the added print checkbox statements, not PrintDialog/VTK.
    tree=ast.parse((OWN/'source/cadstudio/native/print_dialog.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PrintDialog')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    statements=[n for n in init.body if 'exclude_electrical' in ast.unparse(n) or 'exclude_fasteners' in ast.unparse(n) or
                (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='exclusions' for t in n.targets))]
    fake=SimpleNamespace(controls=QVBoxLayout(),schedule=lambda *args:None)
    from PySide6.QtWidgets import QHBoxLayout
    exec(compile(ast.Module(body=statements,type_ignores=[]),'new-print-checkbox-source','exec'),{'self':fake,'QCheckBox':QCheckBox,'QHBoxLayout':QHBoxLayout})
    check('two_print_exclusion_checkboxes_default_off',fake.exclude_electrical.text()=='전장 제외' and fake.exclude_fasteners.text()=='볼트·너트 제외'
          and not fake.exclude_electrical.isChecked() and not fake.exclude_fasteners.isChecked())
    check('native_windows_not_shown',not h.isVisible())
    h.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    check('source_current_and_fixture_preserved',digest(current)==current_before and digest(raw)==before)
    from cadstudio.native.window import MainWindow
    from cadstudio.native.mass_cg_entry import read_document_review,DEFAULT_BINDINGS,read_bound_json
    check('frozen_mainwindow_import',MainWindow.__name__=='MainWindow')
    reviewed=read_document_review(SimpleNamespace(design=current))
    check('R2_positive_retains_unknown_complete_mass_CG',reviewed['ok'] and reviewed['actual_complete_mass_g'] is None and reviewed['actual_complete_CG_world_mm'] is None)
    missing={k:dict(v) for k,v in DEFAULT_BINDINGS.items()};missing['contract']['path']=output/'not-present.json'
    check('R2_missing_input_is_unknown',read_document_review(SimpleNamespace(design=current),bindings=missing)['reason_code']=='missing_contract')
    unsupported=read_bound_json('contract',DEFAULT_BINDINGS);unsupported['schema_version']=3
    from cadstudio.native.mass_cg_r2_adapter import adapt_schema2,AdapterProblem,R2_SHA
    try:adapt_schema2(unsupported,read_bound_json('audit',DEFAULT_BINDINGS),read_bound_json('packet',DEFAULT_BINDINGS),read_bound_json('report',DEFAULT_BINDINGS),R2_SHA,current)
    except AdapterProblem as exc:check('unsupported_schema_never_falls_back',str(exc)=='unsupported_schema')
    else:check('unsupported_schema_never_falls_back',False)
    menu=(OWN/'source/cadstudio/native/window.py').read_text(encoding='utf-8')
    check('menu_source_binds_mass_CG_and_interference',"'assembly_mass_cg'" in menu and 'self.interference_dialog' in menu)
    check('fixture_and_D2_still_preserved',digest(current)==current_before and digest(raw)==before)
    receipt={'success':True,'checks':len(results),'results':results,
      'scope':'New multi-membership/temporary display/print exclusion paths only',
      'small_print_fixture':{'source_parts':6,'exported_parts':['frame','pin'],'STL_triangles':count,'path':str(output/'filtered.stl'),
        'sha256':hashlib.sha256(stl).hexdigest()},'native_inputs':0,'native_windows':0,'GPU_render':0,
      'whole_project_kernel_or_history_replay':0,'previous_CG_or_electrical_or_performance_checks_rerun':0,
      'Document_writes':0,'hardware':0,'new_EXE':bool(getattr(sys,'frozen',False))}
    Path(report_path).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'success':True,'checks':len(results),'STL_triangles':count,'native':0,'GPU_render':0}))



