"""New PCB storage/legacy-history/NC integration, no native UI or kernel."""
def run(report_path,legacy_dir):
    from pathlib import Path
    from copy import deepcopy
    import json,sys,time
    from .models import Design,Project
    from .pcb import PCBProject,PCBComponent,PCBPin,PCBTrack,PCBPoint,PCBVia,PCBZone,pcb_digest
    from .pcb_plugin import with_pcb,design_digest,electrical_preview,execute,MANIFEST
    from .native.document import Document
    from . import __version__,__build_id__
    if Path(report_path).exists():raise FileExistsError(report_path)
    start=time.monotonic();checks=[];legacy=Path(legacy_dir)
    def check(name,value):
        checks.append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    before=json.loads((legacy/'expected.json').read_text(encoding='utf-8'))
    old=Project.model_validate_json((legacy/'pcb-history.pcad').read_bytes())
    check('old2L_history_current_exact_keys_and_values_preserved',old.design.model_dump()==before['current'])
    check('old2L_journal_branches_and_before_values_preserved',old.history.model_dump()==before['history'] and len(old.history.entries)==5)
    no_pcb=Project.model_validate_json((legacy/'no-pcb.pcad').read_bytes())
    check('old_no_PCB_document_retains_absent_PCB_key','pcb' not in no_pcb.design.model_dump())
    doc=Document();doc.load(old);cursor=doc.journal.data['entries'][2]['id'];doc.commit(Design.model_validate(doc.journal.at(cursor)),'old branch',cursor=cursor)
    check('old2L_branch_restore_is_still_valid',doc.project().history.cursor==cursor and doc.project().design.pcb.width_mm==65)
    pins=[PCBPin(number='1',net='VIN',shape='roundrect',size_x_mm=2,size_y_mm=1,roundrect_rratio=.2),PCBPin(number='2',net=None,x_mm=3,shape='oval',size_x_mm=2,size_y_mm=1)]
    board=PCBProject(name='owned4L_storage',layer_count=4,width_mm=70,height_mm=60,nets=['GND','VIN'],net_labels={'VIN':'+3V3_D'},
        components=[PCBComponent(ref='U1',x_mm=10,y_mm=10,pins=pins)],
        tracks=[PCBTrack(id='T'+str(i),net='VIN',layer='In1.Cu',points=[PCBPoint(x_mm=i%60+1,y_mm=30),PCBPoint(x_mm=i%60+1.1,y_mm=30)]) for i in range(355)],
        vias=[PCBVia(id='V1',net='VIN',x_mm=11,y_mm=10,diameter_mm=.8,drill_mm=.3,layers=['F.Cu','B.Cu'])],
        zones=[PCBZone(id='Z1',net='GND',layer='In2.Cu',outline=[PCBPoint(x_mm=x,y_mm=y) for x,y in [(1,1),(69,1),(69,59),(1,59)]])])
    raw=deepcopy(no_pcb.design.model_dump());original=deepcopy(raw);digest=design_digest(raw);updated=with_pcb(raw,board,expected_digest=digest)
    check('new4L_explicit_attach_preserves_original_document_input',raw==original and updated.pcb.layer_count==4)
    current=updated.model_dump();check('new4L_all_fields_survive_Project_JSON',Project.model_validate_json(Project(design=updated).model_dump_json()).design.model_dump()==current)
    check('355_individual_track_IDs_survive_storage',len(updated.pcb.tracks)==355 and [t.id for t in updated.pcb.tracks]==['T'+str(i) for i in range(355)])
    check('NC_pad_and_original_net_label_retained',updated.pcb.components[0].pins[1].net is None and updated.pcb.net_labels['VIN']=='+3V3_D')
    check('via_and_zone_outline_are_saved_without_invented_fill',updated.pcb.vias[0].drill_mm==.3 and not updated.pcb.zones[0].filled_polygons)
    stale=deepcopy(raw);stale['name']='changed document'
    try:with_pcb(stale,board,expected_digest=digest)
    except ValueError:blocked=True
    else:blocked=False
    check('stale_full_CAD_digest_blocks_PCB_attach',blocked)
    changed=board.model_copy(deep=True);changed.vias[0].drill_mm=.4
    check('PCB_digest_binds_extended_via_geometry',pcb_digest(changed)!=pcb_digest(board))
    workspace=dict(nodes=['GND','pcb_nc_U1_b'],components=[])
    exported=electrical_preview(board,workspace);u=next(c for c in exported['components'] if c['id']=='pcb_U1')
    check('one_net_unsupported_device_never_invents_GND',u['a']=='pcb_VIN' and u['b'] not in ('GND','pcb_nc_U1_b') and u['a']!=u['b'] and not u['analysis_enabled'])
    check('NC_terminal_not_added_to_real_pin_map',u['terminal_pins']=={'1':'pcb_VIN'})
    later=board.model_copy(deep=True)
    later.nets.extend(['nc_U1_b','nc_U1_b_1'])
    later.components.append(PCBComponent(ref='U2',pins=[PCBPin(number='1',net='nc_U1_b')]))
    collision=electrical_preview(later)
    first=next(c for c in collision['components'] if c['id']=='pcb_U1')
    second=next(c for c in collision['components'] if c['id']=='pcb_U2')
    check('NC_reserves_later_real_nets_and_suffixed_names',first['b'] not in ('pcb_nc_U1_b','pcb_nc_U1_b_1') and first['b']!=second['a'] and second['terminal_pins']=={'1':'pcb_nc_U1_b'})
    only_nc=PCBProject(components=[PCBComponent(ref='J1',pins=[PCBPin(number='1',net=None)])])
    nc=electrical_preview(only_nc)['components'][0]
    check('all_NC_component_has_distinct_explicit_NC_placeholders',nc['a']!='GND' and nc['b']!='GND' and nc['a']!=nc['b'] and not nc.get('terminal_pins'))
    before_workspace=deepcopy(workspace);electrical_preview(board,workspace)
    check('PCB_electrical_preview_preserves_caller_workspace',workspace==before_workspace)
    result=execute('validate',board)
    check('command_validate_retains_4L_true_shape_span_and_IDs',result['project']==board.model_dump(mode='json') and MANIFEST['geometry']['copper_layers']==[2,4])
    if getattr(sys,'frozen',False):
        from .program_drive_provenance import assert_trace_producer
        from . import program_simulation
        proof=assert_trace_producer(program_simulation,program_simulation.simulate_program)
        check('frozen_proof_binds_executed_new_build',proof['mode']=='verified_frozen_bundle' and proof['build_id']==__build_id__)
    report=dict(success=True,count=len(checks),checks=checks,seconds=time.monotonic()-start,version=__version__,build_id=__build_id__,frozen=bool(getattr(sys,'frozen',False)),
        kernel_calls=0,native_GUI_or_GPU=False,paid_API_calls=0,original_projects_modified=0,legacy_inputs='owned new tiny fixtures generated by frozen331 source',physical_or_manufacturing_qualification=False)
    with Path(report_path).open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,ensure_ascii=False)
    return 0
