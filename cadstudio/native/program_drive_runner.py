"""Owned Qt worker lifetime, independent of a dialog's C++ destruction.

Delivery/release only occurs after the owned pool is quiescent. Closing a
dialog cancels its ticket and leaves this app-owned runner alive until cleanup.
"""
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,QCoreApplication,Signal,Slot
from ..program_drive_adapter import review_program_drive


class _Signals(QObject):
    finished=Signal(object,object)
    failed=Signal(object,str)


class ProgramDriveWorker(QRunnable):
    def __init__(self,ticket,parent):
        super().__init__();self.setAutoDelete(False);self.ticket=ticket;self.signals=_Signals(parent)
    @Slot()
    def run(self):
        t=self.ticket
        try:self.signals.finished.emit(t,review_program_drive(t.design,t.attachment,t.contract,t.parameters,cancel_event=t.cancel))
        except Exception as exc:self.signals.failed.emit(t,str(exc)[:1600])


class ProgramDriveRunner(QObject):
    finished=Signal(object,object)
    failed=Signal(object,str)
    def __init__(self):
        super().__init__(QCoreApplication.instance());self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        QCoreApplication.instance().aboutToQuit.connect(self.close)
        self.worker=None;self.busy=False;self.closing=False;self.pending=None
        self.retirement=QTimer(self);self.retirement.setInterval(5);self.retirement.timeout.connect(self.retire)
    def start(self,ticket):
        if self.busy or self.closing:return False
        worker=ProgramDriveWorker(ticket,self);self.worker=worker;self.busy=True
        worker.signals.finished.connect(self.collect_finished);worker.signals.failed.connect(self.collect_failed)
        self.pool.start(worker);return True
    @Slot(object,object)
    def collect_finished(self,ticket,result):self.pending=('finished',ticket,result);self.retirement.start()
    @Slot(object,str)
    def collect_failed(self,ticket,message):self.pending=('failed',ticket,message);self.retirement.start()
    def retire(self):
        if self.pool.activeThreadCount()!=0:return
        self.retirement.stop();self.busy=False;worker=self.worker;self.worker=None
        pending=self.pending;self.pending=None
        if worker is not None:worker.signals.deleteLater()
        # Auto-delete is off: the Python QRunnable reference is released here,
        # after run() returned, rather than inside its queued result callback.
        if self.closing:self.deleteLater();return
        if pending:
            signal=self.finished if pending[0]=='finished' else self.failed;signal.emit(pending[1],pending[2])
    def close(self):
        if self.closing:return
        self.closing=True
        if self.worker:self.worker.ticket.cancel.set()
        if not self.busy:self.deleteLater()
