"""Exercise pure UI summaries without importing Qt or creating a GUI."""
import ast
from pathlib import Path

TEXT=(Path(__file__).resolve().parents[1]/'cadstudio/native/pcb_workbench.py').read_text(encoding='utf-8')
CLASS=next(n for n in ast.parse(TEXT).body if isinstance(n,ast.ClassDef) and n.name=='PCBWorkbench')

def summary(name, packet):
    fn=next(n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name==name)
    fn.decorator_list=[]
    scope={}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<pure PCB summary>','exec'),scope)
    return scope[name](packet)

def test_unchecked_routing_trial_does_not_display_false_zero():
    text=summary('routing_summary',dict(trials=[dict(layer_count=4,status='budget_exhausted',geometric_check=None,blockers=[])]))
    assert '미연결 그룹 미확인 / unknown' in text and '미연결 그룹 0' not in text

def test_actual_inspection_unrouted_count_preserved():
    report=dict(checked_layers=['F.Cu'],findings=[dict(code='unrouted_net'),dict(code='unrouted_net')])
    text=summary('routing_summary',dict(trials=[dict(layer_count=2,status='blocked',geometric_check=report,blockers=[])]))
    assert '미연결 그룹 2' in text

def test_preview_stack_uses_candidate_not_old_two_layer_visibility():
    method=next(n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name=='sync_layers')
    text=ast.get_source_segment(TEXT,method)
    assert 'shown=self.preview_project or self.project' in text
    assert 'copper_layers(shown)' in text and 'shown.layer_count' in text

def test_placement_trial_integer_does_not_become_layer_trial_UI():
    method=next(n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name=='update_workflow_controls')
    assert 'if not isinstance(trials,list):trials=[]' in ast.get_source_segment(TEXT,method)
