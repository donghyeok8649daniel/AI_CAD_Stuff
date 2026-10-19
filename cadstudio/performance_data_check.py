"""Explicit headless package acceptance: real PCAD round trip and one-part edit.

Creates no application/window/render objects, drives no equipment and never writes the input.
The frozen runtime may preload QtCore before dispatch to relocate its libraries.
"""
import gc,hashlib,json,sys,time
from pathlib import Path
_startup_modules=frozenset(sys.modules)
from . import __version__,__build_id__
from .native.document import Document,read_project,_atomic_project_write
from .models import Design,Part
from . import kernel as K


def audit_toolkit_modules(before,current):
    toolkit=lambda name:name.split('.')[0] in ('PySide6','PyQt6','tkinter','_tkinter','pyautogui')
    preloaded=sorted(name for name in before if toolkit(name))
    added=sorted(name for name in current if toolkit(name) and name not in before)
    allowed=lambda name:name in ('PySide6','PySide6.QtCore','PySide6.support') or name.startswith('PySide6.support.')
    forbidden=sorted(name for name in preloaded if not allowed(name))
    assert not forbidden and not added,('Unexpected GUI toolkit modules',forbidden,added)
    return dict(preloaded=preloaded,added=added,bootstrap_qualification='PyInstaller may preload QtCore; no GUI module imports by acceptance')


def run(report,input_path=None):
    target=Path(report)
    if target.exists():raise FileExistsError('Acceptance report already exists')
    started=time.perf_counter();last_progress=[0.]
    result=dict(status='RUNNING',version=__version__,build_id=__build_id__,GUI_actions=0,phases={})
    def record():_atomic_project_write(target,json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8'))
    def progress(text):
        now=time.perf_counter()
        if now-last_progress[0]>.5:
            result['stage']=text;result['elapsed_seconds']=now-started;record();last_progress[0]=now
    def phase(name,work):
        result['stage']=name;record();tick=time.perf_counter();value=work()
        result['phases'][name]=time.perf_counter()-tick;record();return value
    def stats(preview):
        return {key:preview['stats'][key] for key in ('valid','parts','triangles','volume','bounds')}
    try:
        doc=Document()
        if input_path:
            path=Path(input_path);before=hashlib.sha256(path.read_bytes()).hexdigest()
            project=phase('checked_file_history',lambda:read_project(path))
            doc.load(project);del project
            result['input']=dict(path=str(path),sha256=before,bytes=path.stat().st_size)
        else:
            doc.commit(Design(parts=[Part(id=f'p{i}',name=f'p{i}',geometry=dict(kind='cylinder',diameter=5,height=10+i*.1),transform=dict(x=i*25)) for i in range(40)]),'start')
        result['parts']=len(doc.design['parts']);result['history']=len(doc.journal.data['entries'])
        restored_path=target.with_name(target.stem+'-roundtrip.pcad')
        if restored_path.exists():raise FileExistsError('Acceptance roundtrip already exists')
        phase('checked_save',lambda:doc.write(restored_path,autosave=True))
        loaded=phase('checked_reopen',lambda:read_project(restored_path))
        expected=hashlib.sha256(json.dumps(dict(format='prompt-cad-project',version=2,design=doc.design,prompt=doc.prompt,history=doc.journal.data),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        actual=hashlib.sha256(json.dumps(loaded.model_dump(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert expected==actual,'Full checked project changed on save/reopen'
        result['roundtrip']=dict(full_project_equal=True,sha256=hashlib.sha256(restored_path.read_bytes()).hexdigest(),history=len(loaded.history.entries))
        design=loaded.design;del loaded;gc.collect()
        cold=phase('cold_preview',lambda:K.preview(design,progress=progress))
        result['cold']=stats(cold);result['cold']['collision_count']=len(cold['stats']['collisions'])
        assert cold['stats']['valid'] and cold['stats']['parts']==len(design.parts)
        parents={mate.parent for mate in design.mates}
        leaf=next((part for part in reversed(design.parts) if part.geometry.kind=='cylinder' and not part.features and part.id not in parents),None)
        if leaf is None:raise ValueError('No independent cylinder available for explicit one-part edit acceptance')
        edited=design.model_copy(deep=True);changed=next(part for part in edited.parts if part.id==leaf.id);changed.geometry.height+=.01
        warm=phase('one_part_edit',lambda:K.preview(edited,previous=(design,cold),progress=progress))
        assert warm['stats']['valid'] and warm['stats']['parts']==len(design.parts)
        result['edit']=dict(part_id=leaf.id,height_delta_mm=.01,stats=stats(warm),collision_count=len(warm['stats']['collisions']),
            shared_meshes=sum(a['vertices'] is b['vertices'] for a,b in zip(cold['meshes'],warm['meshes'])))
        result['cache']=K._part_mesh_cache.info()
        from .interference import _collision_cache
        result['exact_pair_cache_entries']=len(_collision_cache)
        if input_path:assert hashlib.sha256(Path(input_path).read_bytes()).hexdigest()==before
        toolkit=audit_toolkit_modules(_startup_modules,sys.modules)
        qtcore=sys.modules.get('PySide6.QtCore')
        assert qtcore is None or qtcore.QCoreApplication.instance() is None,'Application created during data-only acceptance'
        result.update(status='PASS',original_unchanged=True,GUI_modules=[],toolkit_module_audit=toolkit,application_created=False)
        return 0
    except Exception as exc:
        result.update(status='FAIL',error=type(exc).__name__+': '+str(exc));return 1
    finally:
        result['elapsed_seconds']=time.perf_counter()-started;record()
