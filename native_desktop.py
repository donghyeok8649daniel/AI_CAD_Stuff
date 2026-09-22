"""Windows native CAD entry point. Qt Widgets and VTK; no browser/server."""
import argparse
import logging
import os
from pathlib import Path
import sys
import traceback

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--open',type=Path);parser.add_argument('--no-restore',action='store_true');parser.add_argument('--smoke-test',type=Path);parser.add_argument('--self-test',type=Path);args=parser.parse_args()
    data=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(os.getenv('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PromptCADStudio')));data.mkdir(parents=True,exist_ok=True);os.environ['CADSTUDIO_DATA_DIR']=str(data)
    log=(data/'native-desktop.log').open('a',encoding='utf-8',buffering=1)
    if sys.stdout is None:sys.stdout=log
    if sys.stderr is None:sys.stderr=log
    logging.basicConfig(stream=log,level=logging.WARNING)
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtGui import QIcon,QFont
    from PySide6.QtWidgets import QApplication,QMessageBox,QSplashScreen
    app=QApplication(sys.argv);app.setApplicationName('Prompt CAD Studio');app.setOrganizationName('PromptCAD');app.setApplicationVersion('2.1.0');app.setFont(QFont('Malgun Gothic',9));app.setStyle('Fusion')
    root=Path(__file__).resolve().parent;ico=root/'assets'/'app.ico'
    if not ico.exists():ico=root/'static'/'app.ico'
    app.setWindowIcon(QIcon(str(ico)))
    from cadstudio.native.widgets import apply_theme
    apply_theme(app)
    def report_exception(kind,value,tb):
        text=''.join(traceback.format_exception(kind,value,tb));log.write(text);log.flush()
        if args.smoke_test:args.smoke_test.with_suffix('.error.txt').write_text(text,encoding='utf-8');app.exit(1)
        else:QMessageBox.warning(None,'작업 오류',str(value)[:1500])
    sys.excepthook=report_exception
    if args.self_test:
        from cadstudio.native.smoke import kernel_self_test
        kernel_self_test(args.self_test);return 0
    from cadstudio.native.window import MainWindow
    window=MainWindow(restore=not (args.no_restore or args.open or args.smoke_test));window.show()
    if args.open:QTimer.singleShot(100,lambda:window.open_project(args.open))
    if args.smoke_test:
        from cadstudio.native.smoke import run_smoke
        QTimer.singleShot(300,lambda:run_smoke(app,window,args.smoke_test))
    return app.exec()

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        data=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(__file__).parent/'data')));data.mkdir(parents=True,exist_ok=True);(data/'native-startup-error.log').write_text(traceback.format_exc(),encoding='utf-8');raise
