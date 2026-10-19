"""Execute only open_project's current nested worker AST; no native imports."""
import ast
from copy import deepcopy
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


SOURCE=Path(__file__).resolve().parents[1]/'cadstudio/native/window.py'


class ObservedRLock:
    def __init__(self):
        self.lock=threading.RLock();self.entries=0;self.exits=0

    def __enter__(self):
        self.lock.acquire();self.entries+=1
        return self

    def __exit__(self,*args):
        self.exits+=1;self.lock.release()


def other_thread_can_acquire(lock):
    outcomes=[]
    def probe():
        acquired=lock.lock.acquire(blocking=False)
        outcomes.append(acquired)
        if acquired:lock.lock.release()
    thread=threading.Thread(target=probe,name='owned-load-lock-probe',daemon=True)
    thread.start();thread.join(timeout=2)
    assert not thread.is_alive(),'Owned nonblocking probe did not finish.'
    assert len(outcomes)==1
    return outcomes[0]


def actual_worker(read_project,preview,lock,path):
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='MainWindow')
    method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='open_project')
    worker=next(node for node in method.body if isinstance(node,ast.FunctionDef) and node.name=='work')
    module=ast.fix_missing_locations(ast.Module(body=[deepcopy(worker)],type_ignores=[]))
    def progress_preview(value,**kwargs):
        assert callable(kwargs['progress'])
        return preview(value)
    host=SimpleNamespace(worker=SimpleNamespace(signals=SimpleNamespace(progress=SimpleNamespace(emit=lambda text:None))))
    namespace={'read_project':read_project,'preview':progress_preview,'KERNEL_LOCK':lock,'path':path,'self':host}
    exec(compile(module,str(SOURCE),'exec'),namespace)
    return namespace['work']


def test_parse_does_not_hold_kernel_lock_but_preview_does():
    lock=ObservedRLock();project=SimpleNamespace(design=object());result=object();calls=[];path=object()
    def read(value):
        calls.append('parse');assert value is path
        assert other_thread_can_acquire(lock),'Project parse/history validation unnecessarily holds KERNEL_LOCK.'
        assert lock.entries==0
        return project
    def preview(value):
        calls.append('preview');assert value is project.design
        assert lock.entries==1 and lock.exits==0
        assert not other_thread_can_acquire(lock),'Preview must remain inside KERNEL_LOCK.'
        return result
    actual_worker(read,preview,lock,path)()
    assert calls==['parse','preview'] and lock.entries==lock.exits==1
    assert other_thread_can_acquire(lock)


def test_worker_returns_same_project_and_preview_objects_in_same_tuple_order():
    lock=ObservedRLock();project=SimpleNamespace(design=object());result={'owned':'preview'};path=object();calls=[]
    def read(value):calls.append(('read',value));return project
    def preview(value):calls.append(('preview',value));return result
    returned=actual_worker(read,preview,lock,path)()
    assert type(returned) is tuple and len(returned)==2
    assert returned[0] is project and returned[1] is result
    assert calls==[('read',path),('preview',project.design)]


def test_parse_failure_never_enters_kernel_lock_or_invokes_preview():
    lock=ObservedRLock();calls=[];failure=ValueError('owned invalid project fixture')
    def read(path):raise failure
    def preview(design):calls.append(design);raise AssertionError('No preview after parse failure.')
    with pytest.raises(ValueError) as caught:actual_worker(read,preview,lock,object())()
    assert caught.value is failure and calls==[]
    assert lock.entries==lock.exits==0 and other_thread_can_acquire(lock)


def test_preview_failure_releases_kernel_lock_without_substituting_an_error():
    lock=ObservedRLock();project=SimpleNamespace(design=object());failure=RuntimeError('owned preview fixture failure')
    def preview(design):
        assert design is project.design and not other_thread_can_acquire(lock)
        raise failure
    with pytest.raises(RuntimeError) as caught:
        actual_worker(lambda path:project,preview,lock,object())()
    assert caught.value is failure
    assert lock.entries==lock.exits==1 and other_thread_can_acquire(lock)
