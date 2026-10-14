"""Count-unbounded project storage checks; no mesh generation or hardware."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json,sys,time

def run(report_path,input_path):
    from ..models import Design,Part,PartGroup,DraftRequest
    from ..constraints import solve_assembly
    from .document import Document,read_project
    from ..history import equivalent
    from ..bom_design import BomDocument,preflight_bom_design,BomInputRequired
    from .. import __version__,__build_id__
    report_path=Path(report_path);input_path=Path(input_path);assert not report_path.exists()
    checks=[];started=time.monotonic()
    def check(name,value,**details):
        checks.append(dict(name=name,passed=bool(value),**details))
        if not value:raise AssertionError(name)
    data=input_path.read_bytes();raw=json.loads(data);desktop_sha=sha256(data).hexdigest()
    project=read_project(input_path)
    check('actual_desktop335_parts387_assets105_history_open',len(project.design.parts)==335 and len(project.design.assets)==387 and len(project.history.entries)==105)
    document=Document();document.load(project,input_path)
    check('actual_full_design_and_history_retained',equivalent(document.design,raw['design']) and document.journal.data==project.history.model_dump())
    target=report_path.parent/(report_path.stem+'-desktop-roundtrip.pcad');assert not target.exists()
    document.write(target);again=read_project(target)
    check('actual_file_save_reopen_preserves_every_history_entry_asset_and_pose',again.model_dump()==project.model_dump())
    check('actual_input_bytes_unchanged',sha256(input_path.read_bytes()).hexdigest()==desktop_sha)
    for count in (301,513,1025):
        typed=Design(name='Owned '+str(count),parts=[Part(id='p'+str(i),name='p'+str(i),fixed=True,geometry=dict(kind='cylinder',diameter=2,height=2)) for i in range(count)])
        check('more_than_old_caps_'+str(count),len(typed.parts)==count)
    large=typed.model_dump();large['parts'][0]['fixed']=True
    for p in large['parts'][1:]:p['fixed']=False
    large['mates']=[dict(id='m'+str(i),kind='rigid',parent='p0',child='p'+str(i),x=i) for i in range(1,1025)]
    frame=dict(face=0,face_count=1,origin=[0,0,0],normal=[0,0,1],x_direction=[1,0,0])
    large['joint_frames']=[dict(mate_id=m['id'],parent=deepcopy(frame),child=deepcopy(frame),flipped=False) for m in large['mates']]
    large['part_groups']=[dict(id='g'+str(i),name='g'+str(i),part_ids=['p'+str(i)]) for i in range(1025)]
    sample=min(raw['design']['assets'].values(),key=lambda a:len(a['data']))
    large['assets']={'a'+str(i):deepcopy(sample) for i in range(1025)}
    large['dimension_bindings']=[dict(path=['parts',i,'geometry','diameter'],expression='2') for i in range(1025)]
    typed=Design.model_validate(large)
    check('1025_assets_groups_bindings_and1024_mates_frames_load',len(typed.assets)==len(typed.part_groups)==len(typed.dimension_bindings)==1025 and len(typed.mates)==len(typed.joint_frames)==1024)
    group=deepcopy(large);group['part_groups']=[dict(id='all',name='all',part_ids=['p'+str(i) for i in range(1025)])]
    check('one_group_keeps_all1025_members',len(Design.model_validate(group).part_groups[0].part_ids)==1025)
    # Two valid journal branches both contain a formerly unsupported design size.
    doc=Document();doc.commit(typed,'large base');base=doc.journal.data['cursor']
    changed=deepcopy(doc.design);changed['name']='large branch1';doc.commit(changed,'branch1');first=doc.journal.data['cursor']
    doc.commit(doc.journal.at(base),'back',cursor=base);changed=deepcopy(doc.design);changed['name']='large branch2';doc.commit(changed,'branch2')
    path=report_path.parent/(report_path.stem+'-large-history.pcad');assert not path.exists();doc.write(path);reopened=read_project(path)
    check('large_old_branches_and_history_save_reopen_without_truncation',len(reopened.history.entries)==3 and len(reopened.design.parts)==1025)
    loaded=Document();loaded.load(reopened,path)
    check('large_undo_branch_still_restores1025_parts',len(loaded.journal.at(first)['parts'])==1025 and loaded.journal.at(first)['name']=='large branch1')
    chain=dict(name='reverse deep chain',parts=[dict(id='c'+str(i),name='c'+str(i),fixed=i==0,geometry=dict(kind='cylinder',diameter=2,height=2)) for i in reversed(range(1025))],
        mates=[dict(id='cm'+str(i),kind='rigid',parent='c'+str(i-1),child='c'+str(i),x=1) for i in range(1,1025)])
    deep=Design.model_validate(chain)
    check('reverse1024_parent_chain_without_recursion_error',next(p for p in deep.parts if p.id=='c1024').transform.x==1024 and solve_assembly(deep)['mates']==1024)
    invalid=deepcopy(chain);invalid['mates'][0]['parent']='c1024'
    try:Design.model_validate(invalid)
    except ValueError as exc:check('deep_cycle_still_rejected','순환' in str(exc))
    else:raise AssertionError('deep cycle accepted')
    invalid=deepcopy(large);invalid['mates'][0]['parent']='missing'
    try:Design.model_validate(invalid)
    except ValueError as exc:check('missing_part_reference_still_rejected','실제 부품' in str(exc))
    else:raise AssertionError('missing reference accepted')
    invalid=deepcopy(large);invalid['parts'][1]['id']='p0'
    try:Design.model_validate(invalid)
    except ValueError as exc:check('duplicate_part_ID_still_rejected','중복' in str(exc))
    else:raise AssertionError('duplicate ID accepted')
    # The project256 check must not shadow the separate per-request operation budget.
    digest='a'*64;bom=BomDocument(id='bom_'+digest[:20],source_name='owned',source='owned',source_sha256=digest,
        items=[dict(id='i'+str(i),name='item'+str(i),quantity=1,source_row=i+1) for i in range(513)])
    check('saved_BOM_can_keep_more_than512_items',len(bom.items)==513)
    request=DraftRequest(prompt='owned',current=Design(parts=typed.parts,bom=bom))
    try:preflight_bom_design(request)
    except BomInputRequired as exc:check('large_project_BOM_reports_per_draft32_without_project256_gate','32개 새 부품' in str(exc) and '256개 CAD' not in str(exc))
    else:raise AssertionError('unbounded per-draft work unexpectedly accepted')
    small=bom.model_copy(deep=True);small.items=small.items[:1]
    request=DraftRequest(prompt='owned small batch',current=Design(parts=typed.parts,bom=small))
    allowed=preflight_bom_design(request)
    check('bounded_BOM_batch_allowed_in_existing1025_part_project',allowed is not None)
    schema=Design.model_json_schema()
    check('3D_project_collections_have_no_numeric_count_cap',all('maxItems' not in schema['properties'][k] and 'maxProperties' not in schema['properties'][k]
        for k in ['parts','mates','assets','joint_frames','part_groups','dimension_bindings','motion_links','sketches']))
    if getattr(sys,'frozen',False):
        from ..program_drive_provenance import assert_trace_producer
        from .. import program_simulation
        proof=assert_trace_producer(program_simulation,program_simulation.simulate_program)
        check('exact_new_frozen_build_signed_proof',proof['mode']=='verified_frozen_bundle' and proof['build_id']==__build_id__)
    result=dict(success=True,count=len(checks),checks=checks,seconds=time.monotonic()-started,version=__version__,build_id=__build_id__,
        frozen=bool(getattr(sys,'frozen',False)),actual_desktop_input_sha256=desktop_sha,roundtrip=str(target),source_input_modified=False,
        native_mainwindow_acceptance=False,geometry_generation=0,hardware_IO=False,old_motion_suites_repeated=0)
    with report_path.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    return 0
