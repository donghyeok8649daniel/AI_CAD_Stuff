import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from cadstudio import kernel as K
from cadstudio.models import Design,Part
from cadstudio.native.document import Document,read_project
from cadstudio.project_open import remember_saved_preview,load_project_preview


@pytest.mark.parametrize('mode',['normal','wrong-geometry','cache-denied'])
def test_actual_native_save_populates_only_a_matching_cache_and_never_fails_a_good_save(tmp_path,monkeypatch,mode):
    source=Path(__file__).resolve().parents[1]/'cadstudio/native/window.py'
    cls=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    save=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='save')
    design=Design(parts=[Part(id='p',name='saved',geometry=dict(kind='cylinder',diameter=4,height=5))])
    result=K.preview(design)
    if mode=='wrong-geometry':design.parts[0].geometry.height=6
    doc=Document();doc.commit(design,'start');doc.path=tmp_path/'saved.pcad';errors=[]
    if mode=='cache-denied':
        from cadstudio.verified_preview_cache import VerifiedPreviewCache
        monkeypatch.setattr(VerifiedPreviewCache,'_key',lambda *args,**kwargs:(_ for _ in ()).throw(PermissionError('owned denial')))
    class Loop:
        def __init__(self,parent):self.stopped=False
        def quit(self):self.stopped=True
        def exec(self):assert self.stopped
    def run(work,done,message,failed):
        try:done(work())
        except Exception as exc:failed(str(exc))
    host=SimpleNamespace(document=doc,result=result,data_dir=tmp_path/'profile',busy=False,sketching=False,run=run,
        title=lambda:None,message=lambda text:None,show_error=errors.append)
    ns=dict(Path=Path,QEventLoop=Loop,remember_saved_preview=remember_saved_preview)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[save],type_ignores=[])),'actual native Save cache bridge','exec'),ns)
    assert ns['save'](host) and not errors and not doc.dirty
    assert read_project(doc.path).design==design
    if mode=='normal':
        from cadstudio import project_open as P
        monkeypatch.setattr(P,'preview',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Save did not populate exact cache')))
        audit={};opened,preview=load_project_preview(doc.path,host.data_dir/'verified-previews',audit=audit)
        assert audit['cache_hit'] and preview['stats']['valid'] and opened.history
    else:assert not list(host.data_dir.glob('verified-previews/*.preview'))
