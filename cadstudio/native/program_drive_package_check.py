"""New exact package path only. No old large or completed suites rerun."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from contextlib import contextmanager
import json,sys,time,hashlib
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent
import shiboken6
from .. import __version__,__build_id__,program_simulation
from ..program_simulation import simulate_program
from ..program_drive_provenance import assert_trace_producer
from ..program_drive_adapter import fingerprint
from .program_drive_dialog import ProgramDriveDialog


def run(report_path):
    report_path=Path(report_path);rows=[]
    def check(name,value):
        rows.append({'name':name,'pass':bool(value)})
        if not value:raise AssertionError(name)
    check('new_exact_frozen_version',getattr(sys,'frozen',False) is True and __version__=='3.1.9' and __build_id__=='local-20261013-display-auto-interference-01')
    binding=assert_trace_producer(program_simulation,simulate_program)
    check('actual_EXE_signed_bundle_provenance_positive',binding['mode']=='verified_frozen_bundle' and binding['build_id']==__build_id__)
    internal=Path(sys._MEIPASS);proof=internal/'cadstudio-program-drive-provenance.json'
    original=proof.read_bytes();original_sha=hashlib.sha256(original).hexdigest()
    # Only owned NEW candidate sidecars, before any Qt widget/worker exists.
    @contextmanager
    def changed(raw):
        try:proof.write_bytes(raw);yield
        finally:proof.write_bytes(original)
    for name,raw in [('malformed_manifest',b'{broken'),('unsigned_manifest',b'{"schema_version":1}'),('unknown_schema',json.dumps({**json.loads(original),'schema_version':2}).encode()),
                     ('forged_signature',json.dumps({**json.loads(original),'signature_hex':'0'*768}).encode())]:
        with changed(raw):
            try:assert_trace_producer(program_simulation,simulate_program)
            except (ValueError,OSError,KeyError):check(name+'_blocks_actual_frozen_path',True)
            else:check(name+'_blocks_actual_frozen_path',False)
    freeze=internal/'program-drive-source-freeze.json';freeze_original=freeze.read_bytes()
    try:
        freeze.write_bytes(freeze_original+b'\n')
        try:assert_trace_producer(program_simulation,simulate_program)
        except ValueError as exc:check('changed_full_freeze_rejected','signed_source_freeze' in str(exc))
        else:check('changed_full_freeze_rejected',False)
    finally:freeze.write_bytes(freeze_original)
    check('candidate_sidecars_restored_before_widgets',proof.read_bytes()==original and freeze.read_bytes()==freeze_original)
    fixture=json.loads((internal/'program-drive-package-check-fixture.json').read_text(encoding='utf-8'))
    root=report_path.with_suffix('').with_name(report_path.stem+'-inputs');root.mkdir()
    cp=root/'contract.json';pp=root/'parameters.json'
    cp.write_text(json.dumps(fixture['contract']),encoding='utf-8');pp.write_text(json.dumps(fixture['parameters']),encoding='utf-8')
    raw=deepcopy(fixture['design']);doc=SimpleNamespace(design=raw,dirty=True,path='not-written.pcad',journal={'entries':['preserved']});before=fingerprint(doc.__dict__)
    app=QApplication.instance() or QApplication([])
    dialog=ProgramDriveDialog(lambda:doc);runner=dialog.runner
    check('frozen_dialog_starts_without_defaults_or_calculation',dialog.table.rowCount()==0 and not dialog.paths['contract'].text() and not dialog.run_button.isEnabled())
    dialog.board.setCurrentIndex(1);dialog.program.setCurrentIndex(1)
    check('saved_board_code_selection_does_not_run',dialog.controller.active is None and dialog.table.rowCount()==0)
    dialog.load_file('contract',cp);dialog.load_file('parameters',pp);dialog.start()
    deadline=time.monotonic()+15
    while dialog._worker_busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents()
    check('one_bounded_frozen_scenario_uses_signed_provenance',not dialog._worker_busy and dialog.controller.result['ok'] and dialog.controller.result['producer_binding']['mode']=='verified_frozen_bundle')
    check('virtual_result_table_not_physical_measurement',dialog.table.rowCount()==11 and dialog.controller.result['actual_rpm'] is None and dialog.controller.result['actual_current_a'] is None and '미확인' in dialog.actual.text())
    check('no_Document_registry_history_writes',fingerprint(doc.__dict__)==before)
    dialog.reject();dialog.deleteLater()
    deadline=time.monotonic()+5
    while shiboken6.isValid(runner) and time.monotonic()<deadline:app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);time.sleep(.005)
    check('owned_worker_runner_quiesced_and_released',not shiboken6.isValid(runner))
    check('no_proof_tampering_remains',hashlib.sha256(proof.read_bytes()).hexdigest()==original_sha)
    result={'success':True,'checks':len(rows),'results':rows,'scope':'new actual frozen provenance and one tiny declared-scenario worker path only','version':__version__,'build_id':__build_id__,
            'producer_binding':binding,'new_declared_scenario_runs':1,'actual_rpm':None,'actual_current_a':None,'physical_clock_verified':False,'native_inputs':0,'native_visible_windows':0,
            'whole_kernel_mesh_history_replay':0,'old32_7_39_8_3_suites_repeated':0,'original_projects_changed':0,'pending_jobs':0}
    report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'success':True,'checks':len(rows),'version':__version__,'pending_jobs':0}));return 0
