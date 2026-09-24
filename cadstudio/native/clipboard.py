"""Keep CAD cut data recoverable when the Windows clipboard is unavailable."""
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication


def write(kind,encoded,text):
    app=QApplication.instance()
    if not hasattr(app,'_cad_clipboard'):app._cad_clipboard={}
    # Store the bounded payload before any cut can remove source geometry.
    app._cad_clipboard[kind]=bytes(encoded)
    mime=QMimeData();mime.setData(kind,encoded);mime.setText(text)
    app._cad_clipboard_mime=mime
    QApplication.clipboard().setMimeData(mime)


def read(kind):
    mime=QApplication.clipboard().mimeData()
    if mime and mime.hasFormat(kind):return bytes(mime.data(kind))
    # CAD's own last copy remains usable during a clipboard lock/disconnection.
    return getattr(QApplication.instance(),'_cad_clipboard',{}).get(kind)
