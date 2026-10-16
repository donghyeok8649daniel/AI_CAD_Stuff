"""AST/source-only PCB UI contracts; no Qt import, application or rendering."""
import ast
from pathlib import Path


SOURCE=Path(__file__).resolve().parents[1]/'cadstudio/native/pcb_workbench.py'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)
WORKBENCH=next(node for node in TREE.body if isinstance(node,ast.ClassDef) and node.name=='PCBWorkbench')
METHODS={node.name:node for node in WORKBENCH.body if isinstance(node,ast.FunctionDef)}


def calls(node):
    return [value for value in ast.walk(node) if isinstance(value,ast.Call)]


def call_names(node):
    return [ast.unparse(value.func) for value in calls(node)]


def strings(node):
    return [value.value for value in ast.walk(node) if isinstance(value,ast.Constant) and isinstance(value.value,str)]


def source(name):return ast.get_source_segment(TEXT,METHODS[name])


def test_prominent_three_task_groups_wire_via_placement_and_layer_controls_exist():
    text='\n'.join(strings(METHODS['__init__']))
    for label in ('부품 배치','배선 만들기','검사·최적화','배선 연결하기','비아 뚫기','배치 최적화','현재 층 배선 검사','층 수 비교'):
        assert label in text
    for identifier in ('pcbConnectTrace','pcbDrillVia','pcbOptimizePlacement','pcbCheckCurrentLayer','pcbCompareLayers','pcbLayerStackSummary','pcbRoutingSteps'):
        assert identifier in text
    assert 'QGroupBox' in call_names(METHODS['__init__'])
    assert 'self.tabs.setCurrentWidget' in call_names(METHODS['begin_via'])
    assert 'self.add_via' in call_names(METHODS['begin_via'])


def test_cpu_algorithms_are_called_only_inside_bounded_worker_on_a_copy():
    start=METHODS['start_workflow']
    work=next(node for node in start.body if isinstance(node,ast.FunctionDef) and node.name=='work')
    algorithms=[call for call in calls(start) if ast.unparse(call.func) in ('optimize_placement','assess_routing')]
    assert len(algorithms)==2
    assert all(call in calls(work) and isinstance(call.args[0],ast.Name) and call.args[0].id=='project' for call in algorithms)
    bounds={keyword.arg:keyword.value.value for call in algorithms for keyword in call.keywords if isinstance(keyword.value,ast.Constant)}
    assert bounds['max_trials']==200 and bounds['max_expansions']==12000
    assert any(ast.unparse(call.func)=='self.project.model_copy' and any(k.arg=='deep' and isinstance(k.value,ast.Constant) and k.value.value is True for k in call.keywords) for call in calls(start))
    assert 'Worker' in call_names(start) and 'QThreadPool.globalInstance().start' in call_names(start)
    assert source('start_workflow').count('Qt.ConnectionType.QueuedConnection')==2


def test_late_result_requires_same_worker_nonce_pcb_document_and_live_widget():
    start=METHODS['start_workflow']
    valid=next(node for node in start.body if isinstance(node,ast.FunctionDef) and node.name=='valid')
    names={ast.unparse(value) for value in ast.walk(valid) if isinstance(value,(ast.Attribute,ast.Compare,ast.Call))}
    assert 'self.alive' in names and 'self.workflow_task is worker' in names
    assert 'nonce == self.workflow_nonce' in names
    assert 'pcb_digest(self.project) == base' in names
    assert 'design_digest(self.current_raw()) == document_base' in names
    done=next(node for node in start.body if isinstance(node,ast.FunctionDef) and node.name=='done')
    guard=next(node for node in done.body if isinstance(node,ast.If) and ast.unparse(node.test)=='not accepted')
    assert any(isinstance(node,ast.Return) for node in guard.body)


def test_cancel_reload_document_change_and_close_invalidate_without_killing_cpu():
    cancel=source('cancel_workflow')
    assert 'self.workflow_nonce+=1' in cancel and 'self.workflow_task=None' in cancel
    assert 'self.workflow.cancel_preview' in call_names(METHODS['cancel_workflow'])
    assert not any(any(word in name.casefold() for word in ('terminate','kill','waitfordone')) for name in call_names(METHODS['cancel_workflow']))
    for name in ('reload','document_changed','closeEvent'):
        assert 'self.cancel_workflow' in call_names(METHODS[name])
    text='\n'.join(strings(METHODS['cancel_workflow']))
    assert 'bounded work may still finish' in text
    assert 'if self._workflow_workers' in source('start_workflow')  # no unlimited queue after cancellation


def test_preview_is_separate_from_local_current_and_whole_CAD_apply():
    stage=METHODS['stage_workflow_preview']
    assert 'self.workflow.stage_candidate' in call_names(stage)
    assert not any(isinstance(target,ast.Attribute) and target.attr=='project' for node in ast.walk(stage) if isinstance(node,ast.Assign) for target in node.targets)
    assert 'self.preview_project or self.project' in source('redraw')
    assert 'self.workflow.apply_preview' in call_names(METHODS['apply_workflow_preview'])
    assert 'design_digest(self.current_raw())!=self.base_sha' in source('apply_workflow_preview')
    for name in ('stage_workflow_preview','start_workflow','apply_workflow_preview','cancel_workflow_preview','undo_draft','redo_draft'):
        assert not any(call.endswith('emit') and 'applyRequested' in call for call in call_names(METHODS[name]))
    assert 'self.applyRequested.emit' in call_names(METHODS['request_apply'])
    assert 'self.preview_project is not None' in source('request_apply')


def test_manual_edits_and_undo_use_session_while_reload_resets_its_history():
    assert 'self.workflow.replace' in call_names(METHODS['set_project'])
    assert 'self.workflow.undo' in call_names(METHODS['undo_draft'])
    assert 'self.workflow.redo' in call_names(METHODS['redo_draft'])
    for name in ('reload','document_changed'):
        assert 'self.workflow.reset' in call_names(METHODS[name])
    controls=source('update_workflow_controls')
    assert 'self._workflow_workers' in controls and 'self.workflow.can_undo' in controls and 'self.workflow.can_redo' in controls


def test_manual_trace_still_requires_same_net_and_cancels_the_pending_gesture():
    route=source('route_click')
    assert "terminal['net']!=self.route['net']" in route
    assert "terminal['key']==self.route['start']" in route
    assert "packet.get('cancel')" in route and 'self.route=None' in route
    assert 'self.update_route_hint' in call_names(METHODS['route_click'])
    assert "self.route['net'] if self.route" in source('add_via')


def test_layer_guidance_keeps_search_failure_warning_success_and_minimum_distinct():
    text='\n'.join(strings(METHODS['routing_summary']))
    assert 'not a proven minimum' in text and 'not impossibility' in text
    assert 'Unsupported and unverified: ' in text
    assert 'Only tested 2/4/6/8-layer candidates' in text
    assert 'minimum_successful_tested_layers' in text and 'minimum_geometrically_routed_layers' in text
    trial=source('preview_trial')
    assert "trial.get('candidate') or trial.get('qualified_candidate')" in trial
    assert 'not full DRC/manufacturing approval' in trial


def test_readable_metrics_are_present_without_dumping_full_candidate_board():
    placement=source('placement_summary')
    for key in ('ratsnest_wirelength_mm','crossing_estimate','body_clearance_violations','boundary_violations','before_objective','after_objective'):
        assert key in placement
    assert 'self.placement_summary' in call_names(METHODS['start_workflow'])
    assert 'self.routing_summary' in call_names(METHODS['start_workflow'])
    assert 'json.dumps' not in call_names(METHODS['start_workflow'])
