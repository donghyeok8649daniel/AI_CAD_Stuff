"""Windows native CAD entry point. Qt Widgets and VTK; no browser/server."""
import argparse
import logging
import os
from pathlib import Path
import sys
import traceback
import faulthandler
from cadstudio import __version__

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--open',type=Path);parser.add_argument('--no-restore',action='store_true');parser.add_argument('--smoke-test',type=Path);parser.add_argument('--self-test',type=Path);parser.add_argument('--setup-ai',action='store_true');parser.add_argument('--setup-codex',action='store_true');parser.add_argument('--codex-smoke',type=Path);parser.add_argument('--mechanical-smoke',type=Path);parser.add_argument('--usability-smoke',type=Path);parser.add_argument('--print-ai-smoke',type=Path);parser.add_argument('--advanced-smoke',type=Path);parser.add_argument('--reliability-smoke',type=Path);parser.add_argument('--direct-smoke',type=Path);parser.add_argument('--thread-smoke',type=Path);parser.add_argument('--sketch-guide-smoke',type=Path);parser.add_argument('--extended-smoke',type=Path);parser.add_argument('--ai-smoke','--wheel-smoke',dest='ai_smoke',type=Path);parser.add_argument('--selection-smoke',type=Path);parser.add_argument('--graphics-probe',nargs=2,metavar=('MODE','REPORT'));parser.add_argument('--renderer',choices=('auto','hardware','software'),default='auto');parser.add_argument('--startup-smoke',type=Path);parser.add_argument('--draft-repair-smoke',type=Path);parser.add_argument('--mechanism-print-smoke',type=Path);parser.add_argument('--reference-smoke',type=Path);parser.add_argument('--electrical-joint-smoke',type=Path);parser.add_argument('--electrical-2150-smoke',type=Path);parser.add_argument('--electrical-2160-smoke',type=Path);parser.add_argument('--mcu-pin-2170-smoke',type=Path);parser.add_argument('--electrical-registration-2180-smoke',type=Path);parser.add_argument('--project-history-smoke',type=Path);parser.add_argument('--circuit-canvas-2190-smoke',type=Path);args=parser.parse_args()
    if (args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke) and not os.getenv('CADSTUDIO_DATA_DIR'):os.environ['CADSTUDIO_DATA_DIR']=str((args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke).resolve().parent/'test-profile')
    if os.name=='nt' and any(value for key,value in vars(args).items() if key.endswith('smoke') or key=='smoke_test'):
        # Disposable verification only: native faults remain failures in logs
        # and exit status instead of blocking the user with a Windows dialog.
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
    data=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(os.getenv('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PromptCADStudio')));data.mkdir(parents=True,exist_ok=True);os.environ['CADSTUDIO_DATA_DIR']=str(data)
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
        if args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.smoke_test or args.advanced_smoke or args.reliability_smoke or args.direct_smoke or args.thread_smoke or args.sketch_guide_smoke or args.extended_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke:(args.circuit_canvas_2190_smoke or args.project_history_smoke or args.electrical_registration_2180_smoke or args.mcu_pin_2170_smoke or args.electrical_2160_smoke or args.electrical_2150_smoke or args.electrical_joint_smoke or args.reference_smoke or args.draft_repair_smoke or args.mechanism_print_smoke or args.startup_smoke or args.smoke_test or args.advanced_smoke or args.reliability_smoke or args.direct_smoke or args.thread_smoke or args.sketch_guide_smoke or args.extended_smoke or args.ai_smoke or args.selection_smoke or args.codex_smoke or args.mechanical_smoke or args.usability_smoke or args.print_ai_smoke).with_suffix('.error.txt').write_text(text,encoding='utf-8');app.exit(1)
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
    from cadstudio.native.window import MainWindow
    window=MainWindow();window.show();log.write('WINDOW_SHOWN\n')
    if any(value for key,value in vars(args).items() if key.endswith('smoke') or key=='smoke_test'):
        window.completion_notifier.enabled=False  # Owned test profiles never show desktop notifications.
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
