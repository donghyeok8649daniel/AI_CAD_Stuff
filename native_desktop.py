"""Windows native CAD entry point. Qt Widgets and VTK; no browser/server."""
import argparse
import logging
import os
from pathlib import Path
import sys
import traceback
import faulthandler
from cadstudio import __version__, __build_id__

def parse_startup_args(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--open',type=Path);parser.add_argument('--no-restore',action='store_true');parser.add_argument('--smoke-test',type=Path);parser.add_argument('--self-test',type=Path);parser.add_argument('--setup-ai',action='store_true');parser.add_argument('--setup-codex',action='store_true');parser.add_argument('--codex-smoke',type=Path);parser.add_argument('--mechanical-smoke',type=Path);parser.add_argument('--usability-smoke',type=Path);parser.add_argument('--print-ai-smoke',type=Path);parser.add_argument('--advanced-smoke',type=Path);parser.add_argument('--reliability-smoke',type=Path);parser.add_argument('--direct-smoke',type=Path);parser.add_argument('--thread-smoke',type=Path);parser.add_argument('--sketch-guide-smoke',type=Path);parser.add_argument('--extended-smoke',type=Path);parser.add_argument('--ai-smoke','--wheel-smoke',dest='ai_smoke',type=Path);parser.add_argument('--selection-smoke',type=Path);parser.add_argument('--graphics-probe',nargs=2,metavar=('MODE','REPORT'));parser.add_argument('--renderer',choices=('auto','hardware','software'),default='auto');parser.add_argument('--startup-smoke',type=Path);parser.add_argument('--draft-repair-smoke',type=Path);parser.add_argument('--mechanism-print-smoke',type=Path);parser.add_argument('--reference-smoke',type=Path);parser.add_argument('--electrical-joint-smoke',type=Path);parser.add_argument('--electrical-2150-smoke',type=Path);parser.add_argument('--electrical-2160-smoke',type=Path);parser.add_argument('--mcu-pin-2170-smoke',type=Path);parser.add_argument('--electrical-registration-2180-smoke',type=Path);parser.add_argument('--project-history-smoke',type=Path);parser.add_argument('--circuit-canvas-2190-smoke',type=Path);parser.add_argument('--occlusion-smoke',type=Path);parser.add_argument('--engineering-smoke',type=Path);parser.add_argument('--electrical-workbench-smoke',type=Path);parser.add_argument('--electrical-ai-wiring-smoke',type=Path);parser.add_argument('--program-simulation-smoke',type=Path);parser.add_argument('--electrical-code-smoke',type=Path);parser.add_argument('--firmware-smoke',type=Path);parser.add_argument('--register-cad-files',action='store_true');parser.add_argument('--unregister-cad-files',action='store_true');parser.add_argument('--default-apps',action='store_true');parser.add_argument('--registration-report',type=Path);parser.add_argument('--bom-smoke',type=Path)
    parser.add_argument('--v3-smoke',type=Path)
    parser.add_argument('--g474-pin-smoke',type=Path)
    parser.add_argument('--project-review-smoke',type=Path)
    parser.add_argument('--review-project',type=Path)
    parser.add_argument('--motion-precision-smoke',type=Path)
    parser.add_argument('--print-batch-smoke',type=Path)
    parser.add_argument('--target-integration-check',type=Path)
    parser.add_argument('--target-project-check',type=Path)
    parser.add_argument('--target-check-input',type=Path)
    parser.add_argument('--performance-check',type=Path)
    parser.add_argument('--role-performance-check',type=Path)
    parser.add_argument('--performance-data-check',type=Path)
    parser.add_argument('--performance-data-input',type=Path)
    parser.add_argument('--automatic-interference-check',type=Path)
    parser.add_argument('--common-app-check',type=Path)
    parser.add_argument('--motion-click-check',type=Path)
    parser.add_argument('--motion-budget-check',type=Path)
    parser.add_argument('--motion-initial-view-check',type=Path)
    parser.add_argument('--pcb-layer-package-check',type=Path)
    parser.add_argument('--flexible-wire-policy-check',type=Path)
    parser.add_argument('--install-canonical',type=Path,metavar='REPORT',help='Install this verified Windows bundle to the single per-user app folder; no GUI.')
    parser.add_argument('--pcb-legacy-fixtures',type=Path)
    parser.add_argument('--project-capacity-check',type=Path)
    parser.add_argument('--capacity-check-input',type=Path)
    parser.add_argument('--program-drive-package-check',type=Path)
    parser.add_argument('--interference-adjustment-check',type=Path)
    parser.add_argument('--render-controls-check',type=Path)
    parser.add_argument('--electrical-ui-check',type=Path)
    parser.add_argument('--g474-project',type=Path)
    parser.add_argument('--g474-elf',type=Path)
    parser.add_argument('--g474-board',default='')
    parser.add_argument('--g474-save',type=Path)
    parser.add_argument('--g474-run-dir',type=Path)
    parser.add_argument('--g474-backend',type=Path)
    parser.add_argument('--g474-duration',type=float)
    parser.add_argument('--g474-scenario',choices=['boot','drdy','timer_rollover','motor_drive','motor_stop','motor_guard','motor_limit'])
    parser.add_argument('--g474-observe-symbol',action='append',default=[])
    parser.add_argument("project", nargs="?", type=Path, help="CAD project opened by Windows")
    args=parser.parse_args(argv)
    if args.install_canonical and any(value for key,value in vars(args).items() if key not in ('install_canonical','renderer','no_restore')):
        parser.error('--install-canonical is a separate headless installation action.')
    g474_fields={'g474_project','g474_elf','g474_board','g474_save','g474_run_dir','g474_backend','g474_duration','g474_scenario','g474_observe_symbol','renderer','no_restore'}
    if args.g474_project:
        if any(value for key,value in vars(args).items() if key not in g474_fields):
            parser.error('G474 headless 실행과 창 열기/다른 시작 작업은 함께 요청할 수 없습니다.')
        if not args.g474_save and not args.g474_run_dir:
            parser.error('G474 headless 실행에는 --g474-save 또는 --g474-run-dir가 필요합니다.')
    elif args.g474_elf or args.g474_board or args.g474_save or args.g474_run_dir or args.g474_backend or args.g474_duration is not None or args.g474_scenario or args.g474_observe_symbol:
        parser.error('G474 옵션에는 --g474-project가 필요합니다.')
    if bool(args.project_capacity_check) != bool(args.capacity_check_input):
        parser.error('--project-capacity-check requires --capacity-check-input.')
    if args.project_capacity_check and any(value for key,value in vars(args).items() if key not in ('project_capacity_check','capacity_check_input','renderer','no_restore')):
        parser.error('--project-capacity-check uses only owned project copies.')
    if args.motion_click_check and any(value for key,value in vars(args).items() if key not in ('motion_click_check','renderer','no_restore')):
        parser.error('--motion-click-check uses only owned Qt signals and an inert offscreen viewport.')
    if args.motion_budget_check and any(value for key,value in vars(args).items() if key not in ('motion_budget_check','renderer','no_restore')):
        parser.error('--motion-budget-check uses only headless owned clocks/small geometry fixtures.')
    if args.motion_initial_view_check and any(value for key,value in vars(args).items() if key not in ('motion_initial_view_check','renderer','no_restore')):
        parser.error('--motion-initial-view-check uses only owned inert/offscreen initial-view fixtures.')
    if args.flexible_wire_policy_check and any(value for key,value in vars(args).items() if key not in ('flexible_wire_policy_check','renderer','no_restore')):
        parser.error('--flexible-wire-policy-check uses only owned small/offscreen fixtures.')
    if bool(args.pcb_layer_package_check)!=bool(args.pcb_legacy_fixtures):
        parser.error('--pcb-layer-package-check requires owned --pcb-legacy-fixtures.')
    if args.pcb_layer_package_check and any(value for key,value in vars(args).items() if key not in ('pcb_layer_package_check','pcb_legacy_fixtures','renderer','no_restore')):
        parser.error('--pcb-layer-package-check uses only owned small PCB/history fixtures.')
    if args.common_app_check and any(value for key,value in vars(args).items() if key not in ('common_app_check','renderer','no_restore')):
        parser.error('--common-app-check uses only owned package/offscreen fixtures.')
    if args.automatic_interference_check and any(value for key,value in vars(args).items() if key not in ('automatic_interference_check','renderer','no_restore')):
        parser.error('--automatic-interference-check uses only owned small/offscreen fixtures.')
    if args.program_drive_package_check and any(value for key,value in vars(args).items() if key not in ('program_drive_package_check','renderer','no_restore')):
        parser.error('--program-drive-package-check uses only owned package/small/offscreen fixtures.')
    if args.interference_adjustment_check and any(value for key,value in vars(args).items() if key not in ('interference_adjustment_check','renderer','no_restore')):
        parser.error('--interference-adjustment-check uses only owned small/offscreen fixtures.')
    if args.render_controls_check and any(value for key,value in vars(args).items() if key not in ('render_controls_check','renderer','no_restore')):
        parser.error('--render-controls-check uses only its owned small/offscreen fixtures.')
    if args.electrical_ui_check and any(value for key,value in vars(args).items()
            if key not in ('electrical_ui_check','renderer','no_restore')):
        parser.error('--electrical-ui-check uses only owned small/offscreen fixtures.')
    if args.role_performance_check and any(value for key,value in vars(args).items()
            if key not in ('role_performance_check','renderer','no_restore')):
        parser.error('--role-performance-check uses only owned synthetic/offscreen fixtures.')
    if args.performance_check and any(value for key,value in vars(args).items()
            if key not in ('performance_check','renderer','no_restore')):
        parser.error('--performance-check uses only bounded synthetic/offscreen fixtures.')
    if args.target_integration_check and any(value for key,value in vars(args).items()
            if key not in ('target_integration_check','renderer','no_restore')):
        parser.error('--target-integration-check uses only owned small/offscreen fixtures.')
    if bool(args.target_project_check) != bool(args.target_check_input):
        parser.error('--target-project-check requires --target-check-input and vice versa.')
    if args.target_project_check and any(value for key,value in vars(args).items()
            if key not in ('target_project_check','target_check_input','renderer','no_restore')):
        parser.error('--target-project-check uses only its owned immutable input; other startup actions are prohibited.')
    if args.project is not None:
        if args.open is not None:
            parser.error("Specify the project once: use either a file path or --open.")
        args.open=args.project
    if args.g474_pin_smoke and any(value for key,value in vars(args).items()
                                   if key not in ('g474_pin_smoke','renderer','no_restore')):
        parser.error('--g474-pin-smoke uses only its owned synthetic project; other startup actions are not supported.')
    if bool(args.project_review_smoke) != bool(args.review_project):
        parser.error('--project-review-smoke requires --review-project and vice versa.')
    if args.project_review_smoke and any(value for key,value in vars(args).items()
            if key not in ('project_review_smoke','review_project','renderer','no_restore')):
        parser.error('--project-review-smoke uses only its owned review copy; other startup actions are not supported.')
    if args.motion_precision_smoke and any(value for key,value in vars(args).items()
            if key not in ('motion_precision_smoke','renderer','no_restore')):
        parser.error('--motion-precision-smoke uses only its owned synthetic project; other startup actions are not supported.')
    if args.print_batch_smoke and any(value for key,value in vars(args).items()
            if key not in ('print_batch_smoke','renderer','no_restore')):
        parser.error('--print-batch-smoke uses only its owned synthetic project; other startup actions are not supported.')
    if args.performance_data_input and not args.performance_data_check:
        parser.error('--performance-data-input requires --performance-data-check')
    if args.performance_data_check and any(value for key,value in vars(args).items()
            if key not in ('performance_data_check','performance_data_input','renderer','no_restore')):
        parser.error('--performance-data-check does not permit other startup actions')
    return args

def main():
    args=parse_startup_args()
    if args.performance_data_check:
        from cadstudio.performance_data_check import run
        return run(args.performance_data_check,args.performance_data_input)
    from cadstudio.windows_identity import APP_USER_MODEL_ID,set_windows_app_identity
    app_identity_set=set_windows_app_identity()
    if args.install_canonical:
        from cadstudio.single_install import run_install_cli
        return run_install_cli(Path(sys.executable),args.install_canonical)
    if args.flexible_wire_policy_check:
        try:
            from cadstudio.flexible_wire_package_check import run
            return run(args.flexible_wire_policy_check)
        except Exception:
            import json
            failure=traceback.format_exc()
            try:
                with args.flexible_wire_policy_check.open('x',encoding='utf-8') as stream:
                    json.dump({'success':False,'exception':failure,'native_inputs':0},stream,ensure_ascii=False,indent=2)
            except OSError:
                print(failure,file=sys.stderr)
            return 1
    if args.pcb_layer_package_check:
        try:
            from cadstudio.pcb_layer_package_check import run
            return run(args.pcb_layer_package_check,args.pcb_legacy_fixtures)
        except Exception:
            import json
            failure=traceback.format_exc()
            try:
                with args.pcb_layer_package_check.open('x',encoding='utf-8') as stream:
                    json.dump({'success':False,'exception':failure,'native_inputs':0},stream,ensure_ascii=False,indent=2)
            except OSError:
                print(failure,file=sys.stderr)
            return 1
    if args.motion_initial_view_check:
        try:
            from cadstudio.native.motion_initial_view_check import run
            return run(args.motion_initial_view_check)
        except Exception:
            import json
            args.motion_initial_view_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.motion_budget_check:
        try:
            from cadstudio.native.motion_budget_check import run
            return run(args.motion_budget_check)
        except Exception:
            import json
            args.motion_budget_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.g474_project:
        from cadstudio.firmware_emulation_cli import main as run_g474
        command=['--project',str(args.g474_project),'--duration',str(args.g474_duration if args.g474_duration is not None else 0.01)]
        for flag,value in [('--elf',args.g474_elf),('--board',args.g474_board),('--save-project',args.g474_save),('--run-dir',args.g474_run_dir),('--backend-dir',args.g474_backend),('--scenario',args.g474_scenario)]:
            if value:command += [flag,str(value)]
        for value in args.g474_observe_symbol:command += ['--observe-symbol',value]
        return run_g474(command)
    if args.project_capacity_check:
        try:
            from cadstudio.native.capacity_check import run
            return run(args.project_capacity_check,args.capacity_check_input)
        except Exception:
            import json
            args.project_capacity_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.motion_click_check:
        try:
            from cadstudio.native.motion_click_check import run
            return run(args.motion_click_check)
        except Exception:
            import json
            args.motion_click_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.common_app_check:
        try:
            from cadstudio.native.common_app_package_check import run
            return run(args.common_app_check)
        except Exception:
            import json
            args.common_app_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.automatic_interference_check:
        try:
            from cadstudio.native.automatic_interference_check import run
            run(args.automatic_interference_check)
            return 0
        except Exception:
            import json
            args.automatic_interference_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.program_drive_package_check:
        try:
            from cadstudio.native.program_drive_package_check import run
            return run(args.program_drive_package_check)
        except Exception:
            import json
            args.program_drive_package_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.interference_adjustment_check:
        try:
            from cadstudio.native.interference_adjustment_check import run
            return run(args.interference_adjustment_check)
        except Exception:
            import json
            args.interference_adjustment_check.write_text(json.dumps({'success':False,'exception':traceback.format_exc(),'native_inputs':0},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    if args.render_controls_check:
        from cadstudio.native.render_controls_check import run
        return run(args.render_controls_check)
    if args.electrical_ui_check:
        from cadstudio.native.electrical_ui_check import run
        return run(args.electrical_ui_check)
    if args.role_performance_check:
        from cadstudio.native.role_performance_check import run
        return run(args.role_performance_check)
    if args.performance_check:
        from cadstudio.native.performance_check import run
        return run(args.performance_check)
    if args.target_integration_check:
        from cadstudio.native.target_integration_check import run
        return run(args.target_integration_check)
    if args.target_project_check:
        from cadstudio.native.target_project_check import run
        return run(args.target_project_check,args.target_check_input)
    if args.print_batch_smoke:
        report=args.print_batch_smoke.resolve()
        os.environ['CADSTUDIO_DATA_DIR']=str(report.parent/(report.stem+'-profile'))
    if args.motion_precision_smoke:
        report=args.motion_precision_smoke.resolve()
        os.environ['CADSTUDIO_DATA_DIR']=str(report.parent/(report.stem+'-profile'))
    if args.project_review_smoke:
        report=args.project_review_smoke.resolve()
        os.environ['CADSTUDIO_DATA_DIR']=str(report.parent/(report.stem+'-profile'))
    if args.g474_pin_smoke:
        os.environ['CADSTUDIO_DATA_DIR']=str(args.g474_pin_smoke.resolve().parent/'test-profile-g474')
    if args.v3_smoke and not os.getenv('CADSTUDIO_DATA_DIR'):
        os.environ['CADSTUDIO_DATA_DIR']=str(args.v3_smoke.resolve().parent/'test-profile-v3')
    if args.register_cad_files or args.unregister_cad_files or args.default_apps:
        from cadstudio.file_associations import register,unregister,open_default_apps
        result={}
        try:
            if args.register_cad_files and args.unregister_cad_files:raise ValueError('동시에 등록과 해제를 요청할 수 없습니다.')
            if args.register_cad_files or args.unregister_cad_files:
                if not getattr(sys,'frozen',False):raise ValueError('설치된 Windows EXE에서 CAD 파일 연결을 설정하세요.')
                from cadstudio.single_install import require_canonical_executable
                require_canonical_executable(Path(sys.executable))
                result=register(Path(sys.executable)) if args.register_cad_files else unregister(Path(sys.executable))
            if args.default_apps:open_default_apps()
            result=dict(success=True,registration=result)
        except (OSError,ValueError,RuntimeError) as exc:result=dict(success=False,error=str(exc))
        if args.registration_report:
            import json
            args.registration_report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if result['success'] else 2
    if args.bom_smoke and not os.getenv('CADSTUDIO_DATA_DIR'):os.environ['CADSTUDIO_DATA_DIR']=str(args.bom_smoke.resolve().parent/'test-profile')
    if (args.bom_smoke or args.firmware_smoke or args.electrical_code_smoke or args.program_simulation_smoke or args.electrical_ai_wiring_smoke or args.electrical_workbench_smoke or args.engineering_smoke or args.occlusion_smoke or args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke) and not os.getenv('CADSTUDIO_DATA_DIR'):os.environ['CADSTUDIO_DATA_DIR']=str((args.bom_smoke or args.firmware_smoke or args.electrical_code_smoke or args.program_simulation_smoke or args.electrical_ai_wiring_smoke or args.electrical_workbench_smoke or args.engineering_smoke or args.occlusion_smoke or args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke).resolve().parent/'test-profile')
    if os.name=='nt' and any(value for key,value in vars(args).items() if key.endswith('smoke') or key=='smoke_test'):
        # Disposable verification only: native faults remain failures in logs
        # and exit status instead of blocking the user with a Windows dialog.
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
    from cadstudio.profile_paths import default_data_dir
    data=default_data_dir();data.mkdir(parents=True,exist_ok=True);os.environ['CADSTUDIO_DATA_DIR']=str(data)
    log_path=data/('graphics-'+args.graphics_probe[0]+'-native.log' if args.graphics_probe else 'native-desktop.log')
    if log_path.exists() and log_path.stat().st_size>2_000_000:log_path.replace(log_path.with_suffix('.previous.log'))
    log=log_path.open('a',encoding='utf-8',buffering=1)
    if sys.stdout is None:sys.stdout=log
    if sys.stderr is None:sys.stderr=log
    logging.basicConfig(stream=log,level=logging.WARNING)
    if args.graphics_probe:
        from cadstudio.native.graphics import run_probe
        # Keep a native fault in the disposable probe out of the CAD process.
        return run_probe(args.graphics_probe[0],Path(args.graphics_probe[1]),data)
    faulthandler.enable(file=log,all_threads=True)
    log.write(f'\nSTART {__version__} pid={os.getpid()}\n')
    if app_identity_set:log.write('APP_USER_MODEL_ID '+APP_USER_MODEL_ID+'\n')
    from cadstudio.native.graphics import prepare,recovery_dialog
    graphics=None if (args.self_test or args.setup_ai or args.setup_codex) else prepare(data,args.renderer)
    log.write('GRAPHICS '+str(graphics)+'\n')
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtGui import QIcon,QFont
    from PySide6.QtWidgets import QApplication,QMessageBox,QSplashScreen
    app=QApplication(sys.argv);app.setApplicationName('Prompt CAD Studio');app.setOrganizationName('PromptCAD');app.setApplicationVersion(__version__);app.setFont(QFont('Malgun Gothic',9));app.setStyle('Fusion')
    if graphics and not graphics['selected']:
        if recovery_dialog(app,data,graphics):
            import subprocess
            command=[sys.executable]+([] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve())])+sys.argv[1:]
            subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return 0
    root=Path(__file__).resolve().parent;ico=root/'assets'/'app.ico'
    if not ico.exists():ico=root/'static'/'app.ico'
    app.setWindowIcon(QIcon(str(ico)))
    from cadstudio.native.widgets import apply_theme
    apply_theme(app)
    from cadstudio.native.i18n import install_language
    install_language(data/'ui-settings.json')
    def report_exception(kind,value,tb):
        text=''.join(traceback.format_exception(kind,value,tb));log.write(text);log.flush()
        if args.print_batch_smoke or args.motion_precision_smoke or args.v3_smoke or args.g474_pin_smoke or args.project_review_smoke:
            (args.print_batch_smoke or args.motion_precision_smoke or args.project_review_smoke or args.g474_pin_smoke or args.v3_smoke).with_suffix('.error.txt').write_text(text,encoding='utf-8');app.exit(1);return
        if args.bom_smoke or args.firmware_smoke or args.electrical_code_smoke or args.program_simulation_smoke or args.electrical_ai_wiring_smoke or args.electrical_workbench_smoke or args.engineering_smoke or args.occlusion_smoke or args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.smoke_test or args.advanced_smoke or args.reliability_smoke or args.direct_smoke or args.thread_smoke or args.sketch_guide_smoke or args.extended_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke:(args.bom_smoke or args.firmware_smoke or args.electrical_code_smoke or args.program_simulation_smoke or args.electrical_ai_wiring_smoke or args.electrical_workbench_smoke or args.engineering_smoke or args.occlusion_smoke or args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.smoke_test or args.advanced_smoke or args.reliability_smoke or args.direct_smoke or args.thread_smoke or args.sketch_guide_smoke or args.extended_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke).with_suffix('.error.txt').write_text(text,encoding='utf-8');app.exit(1)
        else:QMessageBox.warning(None,'작업 오류',str(value)[:1500])
    sys.excepthook=report_exception
    if args.setup_codex:
        from cadstudio.native.codex_setup import CodexSetupDialog
        dialog=CodexSetupDialog();dialog.show();return app.exec()
    if args.setup_ai:
        from cadstudio.native.ai_setup import AISetupDialog
        dialog=AISetupDialog();dialog.show();return app.exec()
    if args.self_test:
        from cadstudio.native.smoke import kernel_self_test
        kernel_self_test(args.self_test);return 0
    if args.program_simulation_smoke:
        from cadstudio.native.program_smoke2230 import run
        run(args.program_simulation_smoke);return 0
    if args.print_batch_smoke or args.motion_precision_smoke or args.project_review_smoke or args.g474_pin_smoke or args.v3_smoke or args.bom_smoke or args.firmware_smoke or args.electrical_code_smoke:
        from cadstudio.native.model_picker import LocalModelPicker
        LocalModelPicker.refresh = lambda self: None  # Owned smoke never discovers network models.
    from cadstudio.native.window import MainWindow
    window=MainWindow();window.show();log.write('WINDOW_SHOWN\n')
    if args.print_batch_smoke:
        from cadstudio.native.print_batch_smoke import run
        window.completion_notifier.enabled=False
        QTimer.singleShot(300,lambda:run(app,window,args.print_batch_smoke))
        return app.exec()
    if args.motion_precision_smoke:
        from cadstudio.native.motion_precision_smoke import run
        window.completion_notifier.enabled=False
        QTimer.singleShot(300,lambda:run(app,window,args.motion_precision_smoke))
        return app.exec()
    if args.project_review_smoke:
        from cadstudio.native.project_review_smoke3001 import run
        window.completion_notifier.enabled=False
        QTimer.singleShot(300,lambda:run(app,window,args.review_project,args.project_review_smoke))
        return app.exec()
    if args.g474_pin_smoke:
        from cadstudio.native.g474_pin_smoke import run
        window.completion_notifier.enabled=False
        QTimer.singleShot(300,lambda:run(app,window,args.g474_pin_smoke))
        return app.exec()
    if args.v3_smoke:
        from cadstudio.native.v3_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.v3_smoke))
        return app.exec()
    if any(value for key,value in vars(args).items() if key.endswith('smoke') or key=='smoke_test'):
        window.completion_notifier.enabled=False  # Owned test profiles never show desktop notifications.
    if args.firmware_smoke:
        from cadstudio.native.firmware_smoke2240 import run
        QTimer.singleShot(300,lambda:run(app,window,args.firmware_smoke))
        return app.exec()
    if args.electrical_code_smoke:
        from cadstudio.native.electrical_code_smoke2230 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_code_smoke))
        return app.exec()
    if args.electrical_ai_wiring_smoke:
        from cadstudio.native.electrical_ai_wiring_smoke2220 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_ai_wiring_smoke))
        return app.exec()
    if args.electrical_workbench_smoke:
        from cadstudio.native.electrical_workbench_smoke2210 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_workbench_smoke))
        return app.exec()
    if args.engineering_smoke:
        from cadstudio.native.engineering_smoke2200 import run
        QTimer.singleShot(300,lambda:run(app,window,args.engineering_smoke))
        return app.exec()
    if args.occlusion_smoke:
        from cadstudio.native.occlusion_smoke2191 import run
        QTimer.singleShot(300,lambda:run(app,window,args.occlusion_smoke))
        return app.exec()
    if args.circuit_canvas_2190_smoke:
        from cadstudio.native.circuit_canvas_smoke2190 import run
        QTimer.singleShot(300,lambda:run(app,window,args.circuit_canvas_2190_smoke))
        return app.exec()
    if args.project_history_smoke:
        from cadstudio.native.project_history_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.project_history_smoke))
        return app.exec()
    if args.reference_smoke:
        from cadstudio.native.reference_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.reference_smoke))
        return app.exec()
    if args.electrical_registration_2180_smoke:
        from cadstudio.native.electrical_registration_smoke2180 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_registration_2180_smoke))
        return app.exec()
    if args.mcu_pin_2170_smoke:
        from cadstudio.native.mcu_pin_smoke2170 import run
        QTimer.singleShot(300,lambda:run(app,window,args.mcu_pin_2170_smoke))
        return app.exec()
    if args.electrical_2160_smoke:
        from cadstudio.native.electrical_smoke2160 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_2160_smoke))
        return app.exec()
    if args.electrical_2150_smoke:
        from cadstudio.native.electrical_smoke2150 import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_2150_smoke))
        return app.exec()
    if args.electrical_joint_smoke:
        from cadstudio.native.electrical_joint_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.electrical_joint_smoke))
        return app.exec()
    if args.draft_repair_smoke:
        from cadstudio.native.draft_repair_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.draft_repair_smoke))
        return app.exec()
    if args.mechanism_print_smoke:
        from cadstudio.native.mechanism_print_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.mechanism_print_smoke))
        return app.exec()
    if args.startup_smoke:
        from cadstudio.native.startup_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.startup_smoke))
        return app.exec()
    if args.print_ai_smoke:
        from cadstudio.native.print_ai_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.print_ai_smoke))
        return app.exec()
    if args.usability_smoke:
        from cadstudio.native.usability_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.usability_smoke or args.print_ai_smoke))
        return app.exec()
    if args.mechanical_smoke:
        from cadstudio.native.mechanical_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.mechanical_smoke))
        return app.exec()
    if args.codex_smoke:
        from cadstudio.native.codex_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.codex_smoke))
        return app.exec()
    if args.selection_smoke:
        from cadstudio.native.selection_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.selection_smoke))
        return app.exec()
    if args.ai_smoke:
        from cadstudio.native.ai_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.ai_smoke))
        return app.exec()
    if args.extended_smoke:
        from cadstudio.native.extended_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.extended_smoke))
        return app.exec()
    if args.sketch_guide_smoke:
        from cadstudio.native.sketch_guide_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.sketch_guide_smoke))
    if args.thread_smoke:
        from cadstudio.native.thread_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.thread_smoke))
    if args.direct_smoke:
        from cadstudio.native.direct_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.direct_smoke))
    if args.reliability_smoke:
        from cadstudio.native.reliability_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.reliability_smoke))
    if args.advanced_smoke:
        from cadstudio.native.advanced_smoke import run
        QTimer.singleShot(300,lambda:run(app,window,args.advanced_smoke))
    if args.bom_smoke:
        from cadstudio.native.bom_smoke2240 import run
        QTimer.singleShot(300,lambda:run(app,window,args.bom_smoke))
    if args.open:QTimer.singleShot(100,lambda:window.open_project(args.open))
    if args.smoke_test:
        from cadstudio.native.smoke import run_smoke
        QTimer.singleShot(300,lambda:run_smoke(app,window,args.smoke_test))
    return app.exec()

def run():
    try:return main()
    except Exception:
        data=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(__file__).parent/'data')))
        data.mkdir(parents=True,exist_ok=True)
        (data/'native-startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise


if __name__=='__main__':
    raise SystemExit(run())
