"""Real Qt/VTK adapter lifecycle; interactor calls are instrumented, not rendered."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QRect,QSize,QTimer,Qt
from PySide6.QtGui import QPaintEvent,QResizeEvent,QKeyEvent
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import isValid
from vtkmodules.vtkRenderingOpenGL2 import vtkWin32OpenGLRenderWindow

from cadstudio.native.viewport import CursorInteractor,QVTKRenderWindowInteractor


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


class RecordingInteractor:
    """Exercise the actual Qt adapter without requesting a test GPU context."""
    def __init__(self,window):self.window=window;self.calls=[];self.observers={}
    def GetRenderWindow(self):return self.window
    def AddObserver(self,event,callback):self.observers.setdefault(event,[]).append(callback)
    def RemoveObservers(self,event):self.observers.pop(event,None)
    def Disable(self):self.calls.append(('Disable',))
    def Render(self):self.calls.append(('Render',))
    def SetSize(self,*args):self.calls.append(('SetSize',*args))
    def ConfigureEvent(self):self.calls.append(('ConfigureEvent',))
    def TimerEvent(self):self.calls.append(('TimerEvent',))
    def SetEventInformation(self,*args):self.calls.append(('SetEventInformation',*args))
    def MouseMoveEvent(self):self.calls.append(('MouseMoveEvent',))
    def KeyPressEvent(self):self.calls.append(('KeyPressEvent',))
    def CharEvent(self):self.calls.append(('CharEvent',))


def owned_adapter():
    parent=QWidget()
    window=vtkWin32OpenGLRenderWindow()
    interactor=RecordingInteractor(window)
    widget=CursorInteractor(parent,rw=window,iren=interactor)
    return SimpleNamespace(parent=parent,window=window,interactor=interactor,widget=widget)


def dispose(app,owned):
    if isValid(owned.parent):owned.parent.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_active_adapter_still_delivers_paint_resize_and_timer(app):
    owned=owned_adapter();widget=owned.widget;calls=owned.interactor.calls
    try:
        widget.paintEvent(QPaintEvent(QRect(0,0,100,100)))
        widget.resizeEvent(QResizeEvent(QSize(100,100),QSize(80,80)))
        widget.TimerEvent();widget.CreateTimer(None,None)
        assert ('Render',) in calls and ('ConfigureEvent',) in calls and ('TimerEvent',) in calls
        assert widget._Timer.isActive()
        widget.Finalize()
        assert not widget._Timer.isActive() and not widget.updatesEnabled()
    finally:dispose(app,owned)


def test_finalized_adapter_ignores_queued_native_events_and_callbacks(app):
    owned=owned_adapter();widget=owned.widget;calls=owned.interactor.calls
    try:
        # Schedule callbacks before cleanup, then deliver them after cleanup.
        widget.CreateTimer(None,None)
        QTimer.singleShot(0,widget.TimerEvent)
        widget.CursorChangedEvent(None,None)  # Queues upstream ShowCursor.
        QCoreApplication.postEvent(widget,QPaintEvent(QRect(0,0,100,100)))
        QCoreApplication.postEvent(widget,QResizeEvent(QSize(110,110),QSize(100,100)))
        QCoreApplication.postEvent(widget,QEvent(QEvent.Type.UpdateRequest))
        widget.Finalize();before=list(calls)
        app.processEvents()
        widget.paintEvent(QPaintEvent(QRect(0,0,100,100)))
        widget.resizeEvent(QResizeEvent(QSize(120,120),QSize(110,110)))
        widget.TimerEvent();widget.CreateTimer(None,None);widget.ShowCursor();widget.Render()
        QCoreApplication.sendEvent(widget,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_F,Qt.KeyboardModifier.NoModifier))
        QCoreApplication.sendEvent(widget,QEvent(QEvent.Type.Enter))
        assert calls==before
        assert not widget._Timer.isActive() and not widget.updatesEnabled()
        assert not owned.interactor.observers
    finally:dispose(app,owned)


def test_finalize_is_once_across_repeated_close_and_parent_destruction(app,monkeypatch):
    owned=owned_adapter();finalized=[]
    original=QVTKRenderWindowInteractor.Finalize
    def tracked(widget):
        finalized.append(widget)
        original(widget)
    monkeypatch.setattr(QVTKRenderWindowInteractor,'Finalize',tracked)
    try:
        owned.widget.Finalize();owned.widget.Finalize()
        owned.widget.close();owned.widget.close()
        dispose(app,owned)
        assert len(finalized)==1 and not isValid(owned.widget)
        assert owned.interactor.calls.count(('Disable',))==1
    finally:dispose(app,owned)


def test_parent_destruction_finalizes_an_active_adapter_once(app,monkeypatch):
    owned=owned_adapter();finalized=[]
    original=QVTKRenderWindowInteractor.Finalize
    def tracked(widget):
        finalized.append(True)
        original(widget)
    monkeypatch.setattr(QVTKRenderWindowInteractor,'Finalize',tracked)
    dispose(app,owned)
    assert finalized==[True] and not isValid(owned.widget)
    assert owned.interactor.calls.count(('Disable',))==1
