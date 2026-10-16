"""Alignment UI wiring by source AST plus one detached adapter/session transaction."""
import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import pytest
from cadstudio.pcb import PCBProject,pcb_digest
from cadstudio.pcb_pin_alignment import align_components
from cadstudio.pcb_workflow import PCBWorkflowSession

SOURCE=Path(__file__).parents[1]/'cadstudio/native'


def module(name):return ast.parse((SOURCE/name).read_text(encoding='utf-8-sig'))


def function(tree,name):return next(node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name)


def extracted(tree,name):
    method=deepcopy(function(tree,name));method.decorator_list=[]
    scope=dict(math=math);exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'isolated-ui-method','exec'),scope)
    return scope[name]


def test_dialog_collects_only_bounded_explicit_inputs_and_no_cpu_alignment():
    tree=module('pcb_alignment_dialog.py');text=(SOURCE/'pcb_alignment_dialog.py').read_text(encoding='utf-8-sig')
    called={node.func.id for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
    assert not called & {'align_components','align_pins','inspect_layout','optimize_placement'}
    assert 'MAX_REFERENCE_BYTES=2*1024*1024' in text and 'stream.read(MAX_REFERENCE_BYTES+1)' in text
    assert 'rowCount()>=32' in text and "'unverified'" in text
    assert 'target_world_pose' not in text and 'source_world_pose' not in text
    assert 'write_bytes' not in text and 'write_text' not in text
    assert "('미확인 / Unknown','unverified')" in text
    assert "widget.addItem('미확인 / Unknown',None)" in text
    assert 'setChecked(True)' not in text
    assert "field.setPlaceholderText('빈칸 = 미확인 / Unknown')" in text
    assert "for box in (self.plane,self.allowed,self.keying,self.tolerances):box.setChecked(False)" in text


def test_worker_alignment_reuses_existing_nonce_pcb_cad_cancel_gates_and_strict_preview():
    tree=module('pcb_workbench.py');text=(SOURCE/'pcb_workbench.py').read_text(encoding='utf-8')
    workflow=function(tree,'start_workflow');work=function(workflow,'work');done=function(workflow,'done')
    assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='align_components' for node in ast.walk(work))
    assert 'nonce == self.workflow_nonce' in ast.unparse(workflow) and 'pcb_digest(self.project)==base' in text
    assert 'design_digest(self.current_raw())==document_base' in text and 'accepted=valid()' in text
    assert "result.get('can_apply') is True" in text
    assert "self.stage_workflow_preview(result['candidate'],'대응 핀 정렬 / Pin alignment','alignment')" in text
    assert "'pcbAlignPins'" in text and 'params=dialog.checked' in text
    assert 'dialog_base' in ast.unparse(function(tree,'align_selected'))
    assert 'locked_refs' in ast.unparse(workflow)
    assert 'locked_refs' in ast.unparse(function(tree,'stage_workflow_preview'))
    assert 'locked_refs' in ast.unparse(function(tree,'apply_workflow_preview'))
    assert ast.unparse(done).index('if not accepted:')<ast.unparse(done).index("elif kind == 'alignment':")


@pytest.mark.parametrize('text,expected',[('',None),('  ',None),('0',0.0),('0.02',.02)])
def test_blank_numeric_inputs_remain_unknown_instead_of_becoming_zero(text,expected):
    numeric=extracted(module('pcb_alignment_dialog.py'),'numeric')
    field=type('Field',(),dict(text=lambda self:text))()
    assert numeric(field)==expected


def test_nonfinite_numeric_input_is_rejected_without_qt_import():
    numeric=extracted(module('pcb_alignment_dialog.py'),'numeric')
    field=type('Field',(),dict(text=lambda self:'nan'))()
    with pytest.raises(ValueError):numeric(field)


def test_assembly_preview_summary_exposes_matrix_residual_unknowns_and_no_apply():
    summary=extracted(module('pcb_workbench.py'),'alignment_summary')
    text=summary(dict(status='assembly_preview',core_status='unverified',source_ref='J1',target_ref='J2',target_external=True,
        source_assembly_world_pose=dict(rotation=[[0,-1,0],[1,0,0],[0,0,1]],translation_xyz_mm=[80,210,13]),
        core=dict(max_pin_error_mm=.01,issues=[dict(code='VOLTAGE_INFORMATION_MISSING',message='Unknown voltage')]),can_apply=False))
    assert '80, 210, 13' in text and '[0, -1, 0]' in text and '0.01' in text
    assert 'Unknown voltage' in text and '미확인 / unknown' in text and '아니오 / no' in text
    assert 'no actual CAD assembly registration' in text


def test_adapter_candidate_stages_locally_apply_and_undo_without_cad_mutation():
    def component(ref,x,pin_x,layer,side):
        pins=[dict(number=str(index+1),net='GND',x_mm=pin_x,y_mm=index*2,diameter_mm=.5,layers=[layer]) for index in range(2)]
        metadata=dict(manufacturer='Synthetic',model=ref,source_url='https://example.org/synthetic-only',revision='fixture-r1',
            pin1_number='1',mounted_side=side,orientation_reference='+X',body_height_mm=1,service_clearance_mm=0,
            geometry_complete_declared=True,footprint_review_state='source_reviewed',reviewed_by='Synthetic author',
            reviewed_date='2026-10-16',review_note='Synthetic only; not a manufacturer declaration',
            pin_specs=[dict(number=str(index+1),role='ground',operating_min_v=0,operating_max_v=0) for index in range(2)])
        return dict(ref=ref,x_mm=x,y_mm=10,body_width_mm=2,body_height_mm=2,pins=pins,library_metadata=metadata)
    project=PCBProject(width_mm=60,height_mm=30,nets=['GND'],components=[component('J1',10,-5,'B.Cu','B'),component('J2',25,5,'F.Cu','F')])
    before=project.model_dump(mode='json');cad=dict(name='Unmodified CAD fixture',pcb=deepcopy(before));saved=deepcopy(cad)
    result=align_components(project,'J1','J2',[dict(source_pin=str(index),target_pin=str(index),net_compatibility='compatible') for index in (1,2)],
        mating=dict(source_normal=[0,0,1],target_normal=[0,0,1],source_side='bottom',target_side='top',allowed_side_pairs=[['bottom','top']],stand_off_height_mm=0,insertion_depth_mm=0,keying_verified=True),
        constraints=dict(max_pin_error_mm=.01,pitch_tolerance_mm=.01,normal_tolerance_deg=.1,tolerances_verified=True),
        verification={side:dict(footprint_verified=True,pin_map_verified=True) for side in ('source','target')})
    assert result['can_apply']
    session=PCBWorkflowSession(project)
    preview=session.stage_candidate(result['candidate'],expected_base_sha256=result['base_sha256'],label='대응 핀 정렬',kind='alignment')
    assert preview['kind']=='alignment' and session.current().model_dump(mode='json')==before
    assert not session.can_undo and cad==saved
    session.apply_preview();assert session.can_undo and session.current().components[0].x_mm==pytest.approx(35)
    assert session.undo().model_dump(mode='json')==before and cad==saved and project.model_dump(mode='json')==before
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))
