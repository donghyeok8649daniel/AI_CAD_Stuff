"""Serialize checked recovery snapshots away from the UI; publish only the newest.

One worker and at most one pending snapshot bound queued work. Validation stays
identical to manual save. This module neither imports Qt nor accesses live CAD
state from its worker. Opening another document invalidates previous requests.
"""
from concurrent.futures import Future
from pathlib import Path
from threading import Condition,Thread
import os
from .document import _PROJECT_JSON,_atomic_project_write


class AutosaveQueue:
    def __init__(self,path):
        self.path=Path(path);self._condition=Condition();self._revision=0
        self._pending=None;self._latest=None;self._thread=None;self._closed=False
        self._errors=[]

    def submit(self,document):
        # Called on the UI thread. Later edits cannot mutate this owned snapshot.
        snapshot=document.autosave_snapshot()
        future=Future()
        with self._condition:
            if self._closed:raise RuntimeError('Autosave queue is closed')
            self._revision+=1
            if self._pending is not None:self._pending[2].set_result(False)
            self._pending=(self._revision,snapshot,future);self._latest=future
            if self._thread is None:
                self._thread=Thread(target=self._run,name='CAD-autosave',daemon=True)
                self._thread.start()
            self._condition.notify()
        return future

    def invalidate(self):
        """Prevent a previous document's in-flight save from replacing recovery."""
        with self._condition:
            self._revision+=1
            if self._pending is not None:self._pending[2].set_result(False)
            self._pending=None;self._latest=None;self._errors.clear()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda:self._pending is not None or self._closed)
                if self._pending is None:return
                revision,snapshot,future=self._pending;self._pending=None
            try:
                # Project() still verifies every historical state and branch.
                data=_PROJECT_JSON.dump_json(snapshot.project())
                def publish(temp,target):
                    with self._condition:
                        if revision!=self._revision:return False
                        os.replace(temp,target)
                        return True
                saved=_atomic_project_write(self.path,data,publish)
                future.set_result(saved)
            except Exception as exc:
                with self._condition:
                    if revision==self._revision:self._errors=[exc]
                future.set_exception(exc)
            # Do not retain the completed 47+ MB snapshot while waiting idle.
            snapshot=None
            if 'data' in locals():del data

    def errors(self):
        with self._condition:
            errors=self._errors;self._errors=[]
        return errors

    def flush(self):
        with self._condition:future=self._latest
        if future is not None:return future.result()

    def close(self):
        # Normal shutdown waits for the last recovery write; errors remain
        # visible to the caller and allow another submit/retry before closing.
        self.flush()
        with self._condition:
            self._closed=True;self._condition.notify_all();thread=self._thread
        if thread is not None:thread.join()
