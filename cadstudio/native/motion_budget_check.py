"""Small headless inspection-clock and collision gates; no GUI or hardware."""
def run(report_path):
    from pathlib import Path
    from copy import deepcopy
    import json,sys,time,threading
    from ..motion_budget import MotionInspectionBudget,MotionInspectionTimeout
    from ..motion_playback import compile_joint_playback
    from ..models import Design
    from ..interference import exact_collisions
    from ..kernel import build,KERNEL_LOCK
    from .. import __version__,__build_id__
    report_path=Path(report_path);assert not report_path.exists();started=time.monotonic();checks=[]
    def check(name,value,**detail):
        checks.append(dict(name=name,passed=bool(value),**detail))
        if not value:raise AssertionError(name)
    clock=[0.];events=[];budget=MotionInspectionBudget(120.,lambda:None,events.append,clock=lambda:clock[0],segmented=True)
    with budget.locked(threading.RLock()):
        budget.phase('baseline_collisions')
        for i in range(100):clock[0]+=3.;budget.checkpoint()
        report=budget.finish()
    check('finite_completed_work_slices_not_blanket_budget_increase',report['active_seconds']==300 and report['completed_slices']==100 and max(report['completed_slice_seconds'])==3 and report['active_budget_seconds']==120 and report['budget_scope']=='completed_work_slices')
    for segmented,name in [(False,'direct_API_retains_total_budget'),(True,'single_overlong_native_work_fails_closed')]:
        clock=[0.];budget=MotionInspectionBudget(120.,lambda:None,lambda x:None,clock=lambda:clock[0],segmented=segmented)
        with budget.locked(threading.RLock()):
            budget.phase('sample_collisions');clock[0]=121
            try:budget.checkpoint()
            except MotionInspectionTimeout as exc:check(name,exc.report['completed_slices']==0 and exc.report['stage']=='sample_collisions')
            else:raise AssertionError('deadline ignored')
    lock=threading.RLock();ready=threading.Event();release=threading.Event()
    def hold():
        with lock:ready.set();release.wait(1)
    thread=threading.Thread(target=hold);thread.start();assert ready.wait(.5)
    timer=threading.Timer(.08,release.set);timer.start();events=[]
    try:
        budget=MotionInspectionBudget(.02,lambda:None,events.append,wait_seconds=.5)
        with budget.locked(lock):report=budget.finish()
        check('actual_lock_wait_excluded_from_active_clock',report['queue_seconds']>=.06 and report['active_seconds']<.02 and events[0]['active_seconds']==0)
    finally:release.set();thread.join(1);timer.join(1)
    cancelled=[False];clock=[0.]
    def cancel():
        if cancelled[0]:raise ValueError('cancelled owned work')
    budget=MotionInspectionBudget(120.,cancel,lambda x:None,clock=lambda:clock[0],segmented=True)
    with budget.locked(threading.RLock()):
        clock[0]=3;budget.checkpoint();cancelled[0]=True
        try:budget.checkpoint()
        except ValueError:check('cancel_not_ignored_by_automatic_slicing',budget.checkpoints==1)
        else:raise AssertionError('cancel ignored')
    parts=[dict(id='root',name='root',fixed=True,geometry=dict(kind='plate',length=2,width=2,thickness=2,hole_count=0)),dict(id='arm',name='arm',geometry=dict(kind='plate',length=4,width=1,thickness=1,hole_count=0))]
    raw=Design.model_validate(dict(name='new bounded work',parts=parts,mates=[dict(id='rev',kind='revolute',parent='root',child='arm',x=5,limits={'rz':[-360,360]})])).model_dump()
    initial=deepcopy(raw);result=compile_joint_playback(raw,[dict(mate_id='rev',end_degrees=4)],segmented=True)
    check('initial_and_each2degree_sample_checked',result['samples']==3 and result['pair_checks']==3 and result['step_degrees']==2)
    check('only_complete_result_raw_unchanged_no_hardware',raw==initial and result['inspection_metrics']['stage']=='complete' and result['hardware_motion_allowed'] is False)
    obstacle=dict(id='obstacle',name='obstacle',fixed=True,geometry=dict(kind='plate',length=.4,width=.1,thickness=1,hole_count=0),transform=dict(x=6.8,y=.65))
    collision=deepcopy(raw);collision['parts'].append(obstacle)
    check('future_sample_obstacle_starts_clear',not exact_collisions(Design.model_validate(collision)))
    try:compile_joint_playback(collision,[dict(mate_id='rev',end_degrees=10)],segmented=True)
    except ValueError as exc:check('future_sample_overlap_rejects_partial_playback','재생 구간' in str(exc) and '체적 간섭' in str(exc))
    else:raise AssertionError('future collision allowed')
    overlapping=deepcopy(raw);overlapping['parts'].append({**obstacle,'transform':dict(x=5)});overlapping['part_groups']=[dict(id='group',name='group',part_ids=['arm','obstacle'])]
    try:compile_joint_playback(overlapping,[dict(mate_id='rev',end_degrees=4)],segmented=True)
    except ValueError as exc:check('grouped_start_overlap_not_excluded','현재 자세에 체적 간섭' in str(exc))
    else:raise AssertionError('group masks collision')
    completed=[];typed=Design.model_validate(raw)
    with KERNEL_LOCK:exact_collisions(typed,build(typed),completed=lambda:completed.append(True))
    check('completion_checkpoint_after_every_baseline_pair',len(completed)==1)
    if getattr(sys,'frozen',False):
        from ..program_drive_provenance import assert_trace_producer
        from .. import program_simulation
        proof=assert_trace_producer(program_simulation,program_simulation.simulate_program)
        check('new_frozen_build_proof_matches_executed_code',proof['mode']=='verified_frozen_bundle' and proof['build_id']==__build_id__)
    report=dict(success=True,checks=checks,count=len(checks),seconds=time.monotonic()-started,version=__version__,build_id=__build_id__,
                frozen=bool(getattr(sys,'frozen',False)),GUI_actions=0,hardware_IO=False,old335_motion_and_capacity_suites_repeated=0,
                scope='small owned fixtures and clocks only; actual native window/full335 separately qualified')
    with report_path.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,ensure_ascii=False)
    return 0
