"""AI jobs never occupy Qt's global pool or keep the desktop process alive."""
from threading import Thread
from PySide6.QtCore import QObject,Signal
from .local_ai import DraftControl,DraftCancelled


class AITask(QObject):
    completed=Signal(object)
    failed=Signal(object)
    progress=Signal(object)
    settled=Signal()

    def __init__(self,fn,parent=None):
        super().__init__(parent);self.fn=fn;self.control=DraftControl();self.thread=None;self.settled.connect(self.deleteLater)
    def start(self):
        self.thread=Thread(target=self._run,name='CAD-AI',daemon=True);self.thread.start()
    def cancel(self):self.control.cancel()
    def report(self,text):
        self.control.check()
        try:self.progress.emit((self,text))
        except RuntimeError:pass
    def _run(self):
        try:
            self.control.check();result=self.fn(self.control,self.report);self.control.check()
        except DraftCancelled:pass
        except Exception as exc:
            if not self.control.cancelled.is_set():
                try:self.failed.emit((self,str(exc)))
                except RuntimeError:pass
        else:
            try:self.completed.emit((self,result))
            except RuntimeError:pass
        finally:
            try:self.settled.emit()
            except RuntimeError:pass
