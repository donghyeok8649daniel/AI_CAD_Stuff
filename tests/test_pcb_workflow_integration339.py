"""New cross-module transactions, using tiny synthetic boards only."""
from copy import deepcopy
from cadstudio.pcb import PCBProject, PCBComponent, PCBPin, PCBTrack, PCBVia, pcb_digest
from cadstudio.pcb_workflow import PCBWorkflowSession
from cadstudio.pcb_placement_aid import optimize_placement
from cadstudio.pcb_routing_aid import assess_routing


def component(ref,net,x,y,layers=('F.Cu',)):
    return PCBComponent(ref=ref,x_mm=x,y_mm=y,body_width_mm=2,body_height_mm=2,
        pins=[PCBPin(number='1',net=net,layers=list(layers),diameter_mm=.6)])


def test_optimizer_result_is_preview_only_then_one_undoable_local_edit():
    p=PCBProject(width_mm=60,height_mm=30,nets=['GND','N'],
        components=[component('J1','N',5,10),component('U1','N',45,10)])
    original=p.model_dump(mode='json');session=PCBWorkflowSession(p)
    result=optimize_placement(p,locked_refs=['J1'],max_trials=30)
    assert result['can_apply']
    session.stage_candidate(result['candidate'],expected_base_sha256=result['base_sha256'],label='최적화',kind='placement')
    assert session.current()==p and p.model_dump(mode='json')==original
    after=session.apply_preview();assert after!=p
    assert session.undo()==p and not session.can_undo


def test_routed_candidate_survives_transaction_without_changing_old_copper():
    p=PCBProject(width_mm=20,height_mm=12,nets=['GND','N'],
        components=[component('J1','N',3,4),component('J2','N',17,8)],
        tracks=[PCBTrack(id='old',net='N',points=[dict(x_mm=3,y_mm=4),dict(x_mm=3,y_mm=5)])])
    session=PCBWorkflowSession(p);result=assess_routing(p,max_expansions=500)
    trial=result['trials'][0];assert trial['status']=='routed'
    session.stage_candidate(trial['candidate'],expected_base_sha256=result['base_sha256'],label='배선',kind='routing')
    assert session.current()==p
    after=session.apply_preview();assert after.tracks[0]==p.tracks[0] and len(after.tracks)>1
    assert session.undo()==p


def test_higher_layer_warning_candidate_has_no_silent_apply_or_strict_success():
    p=PCBProject(width_mm=20,height_mm=8,edge_clearance_mm=0,nets=['GND','N'],
        components=[component('G1','GND',10,.5,['F.Cu','B.Cu']),component('G2','GND',10,7.5,['F.Cu','B.Cu']),
            component('N1','N',3,4),component('N2','N',17,4)],
        tracks=[PCBTrack(id='wall'+str(i),net='GND',layer=layer,points=[dict(x_mm=10,y_mm=.5),dict(x_mm=10,y_mm=7.5)])
            for i,layer in enumerate(['F.Cu','B.Cu'])],
        vias=[PCBVia(id='v1',net='N',x_mm=3,y_mm=4),PCBVia(id='v2',net='N',x_mm=17,y_mm=4)])
    original=deepcopy(p.model_dump(mode='json'));session=PCBWorkflowSession(p)
    result=assess_routing(p);trial=next(t for t in result['trials'] if t['layer_count']==4)
    assert result['minimum_successful_tested_layers'] is None and trial['status']=='partial'
    session.stage_candidate(trial['qualified_candidate'],expected_base_sha256=pcb_digest(p),label='경고 포함4층',kind='routing')
    assert session.current().layer_count==2
    session.cancel_preview();assert session.current()==p and p.model_dump(mode='json')==original
    session.stage_candidate(trial['qualified_candidate'],expected_base_sha256=pcb_digest(p),label='경고 포함4층',kind='routing')
    assert session.apply_preview().layer_count==4
    assert session.undo()==p
