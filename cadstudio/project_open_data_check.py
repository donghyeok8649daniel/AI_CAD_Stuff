"""Explicit file-only opening acceptance. No application, render context or input."""
import hashlib,json,sys,time
from pathlib import Path
from . import __version__,__build_id__
from .native.document import _atomic_project_write
from .project_open import load_project_preview
from .performance_data_check import audit_toolkit_modules


def run(output,input_path,cache_folder):
    started=time.perf_counter();before_modules=frozenset(sys.modules);last=[0.]
    output=Path(output);assert not output.exists()
    report=dict(status='RUNNING',version=__version__,build_id=__build_id__,GUI_actions=0,audit={})
    def write():_atomic_project_write(output,json.dumps(report,ensure_ascii=False,indent=2).encode())
    def progress(text):
        if time.perf_counter()-last[0]>.5:
            report.update(stage=text,elapsed_seconds=time.perf_counter()-started);write();last[0]=time.perf_counter()
    try:
        sha=hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
        project,result=load_project_preview(input_path,cache_folder,progress=progress,audit=report['audit'])
        assert hashlib.sha256(Path(input_path).read_bytes()).hexdigest()==sha==report['audit']['file_sha256']
        report.update(parts=len(project.design.parts),history=len(project.history.entries),
            result_sha256=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            resolved_design_sha256=hashlib.sha256(project.design.model_dump_json().encode()).hexdigest(),
            stats={key:result['stats'][key] for key in ('valid','parts','triangles','volume','bounds','collisions')},
            toolkit=audit_toolkit_modules(before_modules,sys.modules),original_unchanged=True)
        core=sys.modules.get('PySide6.QtCore');assert core is None or core.QCoreApplication.instance() is None
        report['status']='PASS';return 0
    except Exception as exc:report.update(status='FAIL',error=type(exc).__name__+': '+str(exc));return 1
    finally:report['elapsed_seconds']=time.perf_counter()-started;write()
