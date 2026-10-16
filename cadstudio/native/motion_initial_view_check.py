"""Narrow initial-view delta with inert viewport; no CAD kernel/native UI."""
def run(report_path):
    from pathlib import Path
    from copy import deepcopy
    import json,sys,time,threading
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtCore import QEvent
    from ..models import Design,Part
    from ..automatic_interference import design_digest
    from ..preview_metadata import geometry_key
    from ..motion_initial_view import capture_initial_motion_snapshot,bound_initial_motion_preview
    from . import motion_playback_dialog as module
    from .. import __version__,__build_id__
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    class InertViewport(QWidget):
        def __init__(self):super().__init__();self.closed=False;self.actors={};self.loads=[]
        def render(self):pass
        def shutdown(self):self.closed=True
        def load(self,data):
            self.loads.append(data);self.actors={} if data is None else {m['id']:() for m in data['meshes']}
            if data and data.get('_fail_display'):raise ValueError('owned synthetic display failure')
    prior=module.CADViewport;module.CADViewport=InertViewport;dialogs=[];checks=[];started=time.monotonic()
    def check(name,value):
        checks.append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    raw=Design(name='new initial view fixture',parts=[Part(id=key,name=key,fixed=key=='base',geometry=dict(kind='cylinder',diameter=5,height=5)) for key in ('base','rotor')],
        mates=[dict(id='D_rev_1',kind='revolute',parent='base',child='rotor',x=20,limits={'rz':[-360,360]})]).model_dump()
    data=dict(_geometry_key=geometry_key(raw),meshes=[dict(id=p['id'],name=p['name'],color=p['color'],vertices=[0.,0.,0.,1.,0.,0.,0.,1.,0.],triangles=[0,1,2]) for p in raw['parts']],
              sketches=[],stats=dict(parts=2,bounds=[25.,5.,5.],min=[0.,0.,0.],max=[25.,5.,5.],volume=100.,collisions=[],assembly_constraints=dict(mates=1,dof=1)))
    current=deepcopy(raw);revision=[('owned_document',5,'cursor5')];original=deepcopy(raw);parent_preview=deepcopy(data)
    def make(snapshot=None,revision_provider=True):
        d=module.MotionPlaybackDialog(None,raw,lambda:current,initial_snapshot=snapshot,revision_provider=(lambda:revision[0]) if revision_provider else None)
        dialogs.append(d);return d
    try:
        snapshot=capture_initial_motion_snapshot(raw,parent_preview,revision[0]);d=make(snapshot)
        check('current_snapshot_loads_immediately_before_worker_or_compile',d.initial_view_state=='current' and len(d.viewport.loads)==1 and set(d.viewport.actors)=={'base','rotor'} and not d.runner.busy and d.ticket is None)
        normalized=Design.model_validate(deepcopy(raw)).model_dump()
        check('exact_numeric_default_normalization_retains_both_attestations',snapshot.preview_geometry_key==geometry_key(raw) and snapshot.normalized_geometry_key==geometry_key(normalized) and snapshot.preview_geometry_key!=snapshot.normalized_geometry_key and snapshot.preview['_geometry_key']==geometry_key(raw))
        other_normalized=deepcopy(normalized);other_normalized['mates'][0]['x']+=1
        check('different_normalized_pose_cannot_use_current_raw_snapshot',bound_initial_motion_preview(snapshot,other_normalized,design_digest(raw),revision[0])[1]=='stale')
        other_normalized=deepcopy(normalized);other_normalized['parts'].reverse()
        check('reordered_parts_cannot_use_current_raw_snapshot',bound_initial_motion_preview(snapshot,other_normalized,design_digest(raw),revision[0])[1]=='stale')
        other_normalized=deepcopy(normalized);other_normalized['mates'].clear()
        check('removed_constraint_cannot_use_current_raw_snapshot',bound_initial_motion_preview(snapshot,other_normalized,design_digest(raw),revision[0])[1]=='stale')
        for name,path,value in [('string_coercion',('parts',0,'geometry','diameter'),'5'),('bool_numeric_coercion',('parts',0,'fixed'),1)]:
            coercion=deepcopy(raw);node=coercion
            for key in path[:-1]:node=node[key]
            node[path[-1]]=value;coercion_data=deepcopy(data);coercion_data['_geometry_key']=geometry_key(coercion)
            check(name+'_does_not_qualify_as_numeric_representation_only',capture_initial_motion_snapshot(coercion,coercion_data,revision[0]) is None)
        d.rpm.setValue(20);d.play()
        check('initial_geometry_is_not_motion_clearance_even_RPM20',d.compiled is None and not d.play_button.isEnabled() and not d.timer.isActive() and '검사 전' in d.initial_note.text())
        parent_preview['meshes'][0]['vertices'][0]=999
        check('independent_snapshot_does_not_share_parent_mesh_containers',d.viewport.loads[0]['meshes'][0]['vertices'][0]==0 and d.viewport.loads[0] is not parent_preview)
        changed=deepcopy(raw);changed['parts'][0]['color']='#FFD400';changed['parts'][0]['name']='current name'
        metadata=capture_initial_motion_snapshot(changed,data,revision[0])
        check('metadata_refresh_uses_current_names_colors_without_geometry_build',metadata.preview['meshes'][0]['color']=='#FFD400' and metadata.preview['meshes'][0]['name']=='current name')
        wrong=deepcopy(raw);wrong['parts'][0]['geometry']['diameter']=6
        check('stale_geometry_preview_not_captured',capture_initial_motion_snapshot(wrong,data,revision[0]) is None)
        duplicate=deepcopy(data);duplicate['meshes'][1]['id']='base'
        check('duplicate_mesh_ID_rejected_not_just_set_comparison',capture_initial_motion_snapshot(raw,duplicate,revision[0]) is None)
        missing=deepcopy(data);missing['meshes'].pop()
        check('missing_part_mesh_rejected',capture_initial_motion_snapshot(raw,missing,revision[0]) is None)
        broken=deepcopy(data);broken['meshes'][0]['triangles'][2]=3
        check('invalid_mesh_index_rejected_before_display',capture_initial_motion_snapshot(raw,broken,revision[0]) is None)
        check('missing_preview_is_explicit_no_kernel_fallback',capture_initial_motion_snapshot(raw,None,revision[0]) is None)
        check('metadata_full_digest_binding_not_geometry_key_only',bound_initial_motion_preview(snapshot,changed,design_digest(changed),revision[0])[1]=='stale')
        revision[0]=('owned_document',6,'cursor5');stale=make(snapshot)
        check('identical_geometry_new_project_revision_has_no_initial_load',stale.initial_view_state=='stale' and not stale.viewport.loads and stale.compiled is None and not stale.play_button.isEnabled())
        revision[0]=('owned_document',5,'cursor5');missing_dialog=make()
        check('missing_snapshot_explains_initial_view_unavailable',missing_dialog.initial_view_state=='missing' and '미리보기가 없습니다' in missing_dialog.initial_note.text() and not missing_dialog.viewport.loads)
        failure_data=deepcopy(data);failure_data['_fail_display']=True;bad=make(capture_initial_motion_snapshot(raw,failure_data,revision[0]))
        check('display_failure_clears_partial_owned_actors_and_keeps_Play_locked',bad.initial_view_state=='display_error' and not bad.viewport.actors and bad.viewport.loads[-1] is None and bad.compiled is None and not bad.play_button.isEnabled())
        ticket=module._Ticket(d.revision,deepcopy(raw),[],threading.Event());d.ticket=ticket;d.cancel()
        check('cancel_keeps_current_initial_model_visible_without_readiness',ticket.cancel.is_set() and d.ticket is None and set(d.viewport.actors)=={'base','rotor'} and d.compiled is None and not d.play_button.isEnabled())
        ticket=module._Ticket(d.revision,deepcopy(raw),[],threading.Event());d.ticket=ticket;d.failed(ticket,'owned synthetic failed inspection')
        check('failed_inspection_retains_initial_view_but_not_clearance',d.compiled is None and set(d.viewport.actors)=={'base','rotor'} and '미완료' in d.initial_note.text() and not d.play_button.isEnabled())
        ticket=module._Ticket(d.revision,deepcopy(raw),[],threading.Event());d.ticket=ticket
        synthetic=dict(samples=3,step_degrees=2,preview=deepcopy(data),inspection_metrics=None,can_loop=False,
                       drives=[dict(mate_id='D_rev_1',start=0,end=4)],frames=[dict(matrices={}) for _ in range(3)])
        d.ready(ticket,synthetic)
        check('only_matching_ready_slot_enables_playback_not_initial_snapshot',d.compiled is synthetic and d.play_button.isEnabled() and '검사 완료' in d.initial_note.text())
        d.invalidate()
        check('target_change_relocks_play_and_labels_view_uninspected',d.compiled is None and not d.play_button.isEnabled() and '검사 전' in d.initial_note.text() and set(d.viewport.actors)=={'base','rotor'})
        ticket=module._Ticket(d.revision,deepcopy(raw),[],threading.Event());d.ticket=ticket;revision[0]=('owned_document',6,'cursor6');d.ready(ticket,synthetic)
        check('revision_changed_ready_discarded_and_old_view_cleared',d.compiled is None and d.initial_view_state=='stale' and not d.viewport.actors)
        d.compile()
        check('revision_changed_compile_does_not_start_worker',not d.runner.busy and d.ticket is None and not d.timer.isActive())
        revision[0]=('owned_document',5,'cursor5')
        def broken_provider():raise ValueError('owned provider unavailable')
        unavailable=module.MotionPlaybackDialog(None,raw,lambda:current,initial_snapshot=snapshot,revision_provider=broken_provider);dialogs.append(unavailable)
        check('revision_capture_exception_fails_closed_without_worker',not unavailable.current_unchanged() and unavailable.initial_view_state=='stale' and unavailable.compiled is None and not unavailable.runner.busy)
        unavailable.compile()
        check('unavailable_revision_compile_never_starts_worker',unavailable.ticket is None and not unavailable.runner.busy)
        later=make(snapshot);later.document_provider=broken_provider;later.play()
        check('document_provider_exception_fails_closed',not later.current_unchanged())
        later.show_initial_view()
        check('unavailable_document_provider_clears_prior_owned_view',later.initial_view_state=='stale' and not later.viewport.actors)
        ready_failure=make(snapshot);ready_failure.rpm.setValue(20)
        ticket=module._Ticket(ready_failure.revision,deepcopy(raw),[],threading.Event());ready_failure.ticket=ticket
        failed_result=deepcopy(synthetic);failed_result['preview']['_fail_display']=True;ready_failure.ready(ticket,failed_result)
        check('checked_result_display_failure_restores_initial_view_but_keeps_play_locked',ready_failure.compiled is None and not ready_failure.play_button.isEnabled() and set(ready_failure.viewport.actors)=={'base','rotor'} and '미완료' in ready_failure.initial_note.text())
        # Exercise the production caller method without making a main window.
        from .window import MainWindow
        owner=SimpleNamespace(busy=False,sketching=False,document=SimpleNamespace(design=raw,journal=SimpleNamespace(data={'cursor':'cursor5'})),operation_serial=5,result=deepcopy(data))
        calls=[];actual=module.MotionPlaybackDialog
        class CapturedDialog:
            def __init__(self,parent,value,provider,**kwargs):calls.append((parent,value,provider,kwargs))
            def exec(self):return 0
            def deleteLater(self):pass
        module.MotionPlaybackDialog=CapturedDialog
        try:MainWindow.motion_playback_dialog(owner)
        finally:module.MotionPlaybackDialog=actual
        arguments=calls[0][3];stamp=(id(owner.document),5,'cursor5')
        check('real_MainWindow_caller_supplies_current_result_and_full_document_stamp',arguments['initial_snapshot'].document_revision==stamp and arguments['revision_provider']()==stamp and arguments['initial_snapshot'].input_digest==design_digest(raw))
        owner.operation_serial+=1
        check('caller_stamp_tracks_revision_even_if_raw_design_identical',arguments['revision_provider']()!=stamp)
        owner.document.journal=None;module.MotionPlaybackDialog=CapturedDialog
        try:MainWindow.motion_playback_dialog(owner)
        finally:module.MotionPlaybackDialog=actual
        check('cleared_journal_caller_has_explicit_None_cursor_without_exception',calls[-1][3]['initial_snapshot'].document_revision==(id(owner.document),6,None))
        check('all_new_display_paths_preserve_raw_source',raw==original and current==original)
        if getattr(sys,'frozen',False):
            from ..program_drive_provenance import assert_trace_producer
            from .. import program_simulation
            proof=assert_trace_producer(program_simulation,program_simulation.simulate_program)
            check('new_frozen_proof_matches_exact_executed_build',proof['mode']=='verified_frozen_bundle' and proof['build_id']==__build_id__)
    finally:
        for d in dialogs:
            d.reject();check('new_fixture_runner_pool_quiescent_'+str(len(checks)),d.runner.pool.activeThreadCount()==0);d.deleteLater()
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();module.CADViewport=prior
    report=dict(success=True,count=len(checks),checks=checks,seconds=time.monotonic()-started,version=__version__,build_id=__build_id__,frozen=bool(getattr(sys,'frozen',False)),
                real_Qt_widgets_offscreen=True,inert_viewport=True,synthetic_preview_and_ready_slot=True,actual_geometry_or_interference_calls=0,actual_worker_runs=0,
                native_mainwindow_or_GPU_acceptance=False,GUI_inputs=0,old335_181_suites_repeated=0,original_or_doc_writes=0,hardware_IO=False)
    with Path(report_path).open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,ensure_ascii=False)
    return 0
