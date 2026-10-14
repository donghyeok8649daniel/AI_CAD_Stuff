"""Owned firmware worker transport; no execution on import/construction.

The app-owned private pool retires workers before delivering results. Dialog
code owns full-document/image/config freshness and attachment validation.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import tempfile
import threading
from uuid import uuid4
from PySide6.QtCore import QRunnable, Slot
from .program_drive_runner import ProgramDriveRunner, _Signals


@dataclass(frozen=True)
class FirmwareRunTicket:
    revision: int
    workspace: dict
    image: object
    design: dict | None
    scenario: str
    cancel: threading.Event
    context_digest: str = ''


FirmwareEmulationTicket = FirmwareRunTicket


def _cancelled_result():
    return {'status': 'cancelled', 'errors': ['Virtual firmware execution cancelled.'],
            'physical_IO': False, 'allow_motion': False}


def _execute_firmware(workspace, image, design, scenario, cancel_event, output_dir):
    # Import only on an explicit run. No SDK/runtime discovery occurs when
    # opening the dialog or creating this owned runner.
    from ..firmware_emulation import run_firmware
    return run_firmware(workspace, image, output_dir=output_dir,
                        cancel_event=cancel_event, scenario=scenario, design=design)


class _FirmwareWorker(QRunnable):
    def __init__(self, ticket, parent):
        super().__init__()
        self.setAutoDelete(False)
        self.ticket = ticket
        self.signals = _Signals(parent)
        # Frozen ticket fields do not freeze nested containers. Keep private
        # submission-time payloads; preserve ticket identity for dialog gates.
        self._inputs = deepcopy((ticket.workspace, ticket.image, ticket.design, ticket.scenario))

    @Slot()
    def run(self):
        try:
            if self.ticket.cancel.is_set():
                result = _cancelled_result()
            else:
                output = Path(tempfile.gettempdir()) / ('cad-g474-' + uuid4().hex)
                workspace, image, design, scenario = self._inputs
                result = _execute_firmware(workspace, image, design, scenario,
                                           self.ticket.cancel, output)
                if self.ticket.cancel.is_set():
                    result = _cancelled_result()
            self.signals.finished.emit(self.ticket, result)
        except Exception as exc:
            try:
                self.signals.failed.emit(self.ticket, str(exc)[:1800])
            except RuntimeError:
                # QApplication destruction can invalidate QObject transport;
                # child-process cleanup remains the executor's finally scope.
                pass


class FirmwareEmulationRunner(ProgramDriveRunner):
    """Private one-worker pool; inherited close/retire suppresses late output."""
    def start(self, ticket):
        if self.busy or self.closing:
            return False
        worker = _FirmwareWorker(ticket, self)
        self.worker = worker
        self.busy = True
        worker.signals.finished.connect(self.collect_finished)
        worker.signals.failed.connect(self.collect_failed)
        self.pool.start(worker)
        return True

    def cancel(self):
        if self.worker is not None:
            self.worker.ticket.cancel.set()
