from copy import deepcopy
import pytest
from cadstudio.pcb import PCBProject, PCBComponent, PCBPin, pcb_digest
from cadstudio.pcb_workflow import PCBWorkflowSession


def board():
    return PCBProject(components=[PCBComponent(ref='U1',pins=[PCBPin(number='1',net='GND')])])


def moved(p):
    q=p.model_dump(mode='json');q['components'][0]['x_mm']=15
    return q


def test_preview_cancel_never_changes_source_or_history():
    p=board();before=p.model_dump(mode='json');s=PCBWorkflowSession(p)
    preview=s.stage_candidate(moved(p),expected_base_sha256=pcb_digest(p),label='배치',kind='placement')
    preview['candidate']['components'][0]['x_mm']=99
    assert s.preview['candidate']['components'][0]['x_mm']==15
    s.cancel_preview()
    assert p.model_dump(mode='json')==before==s.current().model_dump(mode='json')
    assert not s.can_undo and s.preview is None


def test_apply_is_one_atomic_undo_redo_and_current_is_copy():
    p=board();s=PCBWorkflowSession(p)
    s.stage_candidate(moved(p),expected_base_sha256=pcb_digest(p),label='배치',kind='placement')
    after=s.apply_preview();after.components[0].x_mm=99
    assert s.current().components[0].x_mm==15 and s.can_undo
    s.replace(s.current())  # UI synchronization must not add a second step.
    assert s.undo()==p and not s.can_undo and s.can_redo
    assert s.redo().components[0].x_mm==15


def test_replace_invalidates_pending_and_rejects_stale_candidate():
    p=board();s=PCBWorkflowSession(p);sha=pcb_digest(p)
    s.stage_candidate(moved(p),expected_base_sha256=sha,label='배치',kind='placement')
    q=p.model_dump(mode='json');q['name']='manual';s.replace(q)
    assert s.preview is None
    with pytest.raises(ValueError,match='Stale'):s.stage_candidate(moved(p),expected_base_sha256=sha,label='배치',kind='placement')
    with pytest.raises(ValueError):s.apply_preview()


def test_candidate_cannot_discard_copper_or_edit_pitch_or_product():
    p=board();q=p.model_dump(mode='json')
    q['tracks']=[dict(id='T1',net='GND',layer='F.Cu',width_mm=.25,points=[dict(x_mm=10,y_mm=10),dict(x_mm=12,y_mm=10)])]
    p=PCBProject.model_validate(q);s=PCBWorkflowSession(p)
    for mutate in ('delete_copper','move_wired','pitch','new_part'):
        candidate=deepcopy(q)
        if mutate=='delete_copper':candidate['tracks']=[]
        elif mutate=='move_wired':candidate['components'][0]['x_mm']=12
        elif mutate=='pitch':candidate['components'][0]['pins'][0]['x_mm']=1
        else:candidate['components'].append(dict(candidate['components'][0],ref='U2'))
        with pytest.raises(ValueError):s.stage_candidate(candidate,expected_base_sha256=pcb_digest(p),label='배치',kind='placement')
        assert s.current()==p and not s.can_undo


def test_routing_preview_layers_tracks_and_vias_are_undone_together():
    p=board();s=PCBWorkflowSession(p);q=p.model_dump(mode='json');q['layer_count']=4
    q['tracks']=[dict(id='T2',net='GND',layer='In1.Cu',width_mm=.25,points=[dict(x_mm=10,y_mm=10),dict(x_mm=12,y_mm=10)])]
    q['vias']=[dict(id='V1',net='GND',x_mm=10,y_mm=10,diameter_mm=.8,drill_mm=.4,layers=['F.Cu','B.Cu'])]
    s.stage_candidate(q,expected_base_sha256=pcb_digest(p),label='층별 후보',kind='routing');s.apply_preview()
    assert s.current().layer_count==4 and len(s.current().vias)==1
    assert s.undo()==p


def test_routing_cannot_modify_existing_component_or_remove_layer():
    p=board();s=PCBWorkflowSession(p)
    with pytest.raises(ValueError):s.stage_candidate(moved(p),expected_base_sha256=pcb_digest(p),label='배선',kind='routing')
    p.layer_count=4;s.reset(p);q=p.model_dump(mode='json');q['layer_count']=2
    with pytest.raises(ValueError):s.stage_candidate(q,expected_base_sha256=pcb_digest(p),label='배선',kind='routing')


def test_invalid_replace_preserves_preview_and_current():
    p=board();s=PCBWorkflowSession(p);s.stage_candidate(moved(p),expected_base_sha256=pcb_digest(p),label='배치',kind='placement')
    preview=s.preview
    with pytest.raises(ValueError):s.replace(dict(p.model_dump(mode='json'),width_mm=-1))
    assert s.preview==preview and s.current()==p


def test_bounded_undo_and_reset():
    s=PCBWorkflowSession(board(),undo_limit=2)
    for x in (11,12,13):
        q=s.current().model_dump(mode='json');q['components'][0]['x_mm']=x;s.replace(q)
    assert s.undo().components[0].x_mm==12
    assert s.undo().components[0].x_mm==11
    assert not s.can_undo
    s.reset(board());assert not s.can_redo and s.preview is None
