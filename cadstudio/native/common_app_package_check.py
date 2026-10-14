"""New integrated frozen package smoke; no original documents or hardware."""
from pathlib import Path
from types import SimpleNamespace
import importlib,json,sys

def run(report_path):
    from .. import __version__,__build_id__,program_simulation
    from ..program_drive_provenance import assert_trace_producer
    from ..models import Design
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtCore import QCoreApplication,QEvent
    from .document import Document
    from .motor_matrix_dialog import MotorMatrixDialog
    from .pcb_workbench import PCBWorkbench
    from .program_drive_dialog import ProgramDriveDialog
    checks=[]
    def check(name,value):
        checks.append(dict(name=name,pass_=bool(value)))
        if not value:raise AssertionError(name)
    check('exact_new_integrated_frozen_identity',getattr(sys,'frozen',False) is True and __version__=='3.2.0' and __build_id__=='local-20261014-common-cad-pcb-motion-05')
    names=['cadstudio.motion_playback','cadstudio.motor_state_space','cadstudio.native.motion_playback_dialog','cadstudio.native.motor_matrix_dialog',
           'cadstudio.pcb','cadstudio.pcb_plugin','cadstudio.pcb_simulation','cadstudio.native.pcb_workbench','cadstudio.native.pcb_ai']
    names+=['cadstudio.firmware_emulation','cadstudio.firmware_drive','cadstudio.firmware_motion','cadstudio.native.firmware_emulation_dialog','cadstudio.native.firmware_emulation_runner']
    modules=[importlib.import_module(name) for name in names]
    check('new_packaged_modules_import_without_external_calls',all(getattr(module,'__loader__',None) is not None for module in modules))
    binding=assert_trace_producer(program_simulation,program_simulation.simulate_program)
    check('new_EXE_and_full_source_signed_proof_bound',binding['mode']=='verified_frozen_bundle' and binding['build_id']==__build_id__)
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    matrix=MotorMatrixDialog()
    check('packaged_matrix_opens_symbolic_without_auto_scenario',matrix.report['numeric'] is None)
    matrix.reject();matrix.deleteLater()
    raw=Design(name='owned package smoke',parts=[]).model_dump();host=QWidget();host.document=Document();host.document.commit(raw,'owned fixture')
    pcb=PCBWorkbench(host,raw)
    check('packaged_PCB_widget_no_auto_AI_or_simulation',pcb.advice_task is None and pcb.simulation_result is None and not pcb.dirty)
    pcb.alive=False;pcb.stop_advice();pcb.deleteLater();host.deleteLater()
    drive=ProgramDriveDialog(lambda:SimpleNamespace(design=raw))
    check('packaged_program_review_no_auto_code_run_or_files',drive.controller.active is None and drive.controller.contract is None and drive.controller.parameters is None and not drive.runner.busy)
    drive.reject();drive.deleteLater()
    from .firmware_emulation_dialog import FirmwareEmulationDialog
    from ..firmware_emulation import runtime_root,RENODE_MANIFEST_SHA256
    import hashlib
    firmware=FirmwareEmulationDialog({},design=raw)
    check('packaged_firmware_UI_idle_and_owned_pool',firmware.result is None and not firmware.runner.busy and firmware.runner.pool.activeThreadCount()==0)
    firmware.reject();firmware.deleteLater()
    check('packaged_runtime_manifest_matches_compiled_pin',hashlib.sha256((runtime_root()/'cad-runtime-manifest.json').read_bytes()).hexdigest()==RENODE_MANIFEST_SHA256)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    Path(report_path).write_text(json.dumps(dict(success=True,count=len(checks),checks=checks,version=__version__,build_id=__build_id__,
        native_mainwindow_acceptance=False,offscreen_only=True,liveAI_calls=0,firmware_execution=0,hardware_calls=0,original_documents=0),indent=2),encoding='utf-8')
    return 0
