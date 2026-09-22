"""Small native widgets and a consistent CAD palette."""
from PySide6.QtCore import Qt,QObject,QRunnable,Signal,Slot,QSize,QByteArray
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor,QFont
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDoubleSpinBox,QLabel,QPushButton,QFormLayout,QWidget,QVBoxLayout,QHBoxLayout

STYLE='''
QMainWindow,QDialog{background:#f0f2f5;color:#24313d;} QWidget{font-family:"Malgun Gothic";font-size:12px;}
QMenuBar,QMenu,QToolBar{background:#fff;color:#263746;} QMenuBar{padding:3px;} QMenu::item{padding:7px 28px;} QMenu::item:selected{background:#dbece9;}
QToolBar{border:0;border-bottom:1px solid #d8e0e5;spacing:5px;padding:6px;} QToolButton{padding:7px;border:1px solid transparent;border-radius:4px;} QToolButton:hover{background:#edf3f5;} QToolButton:checked{background:#d5e9e4;border:1px solid #79aaa1;}
QDockWidget{font-weight:600;} QDockWidget::title{background:#e5eaee;padding:7px;} QDockWidget::close-button,QDockWidget::float-button{padding:2px;}
QTreeWidget,QListWidget,QTableWidget,QPlainTextEdit,QTextEdit{background:#fff;border:1px solid #dce2e7;selection-background-color:#d5e9e4;selection-color:#193c37;}
QTreeWidget::item,QListWidget::item{padding:6px;} QHeaderView::section{background:#eef2f4;padding:6px;border:0;border-bottom:1px solid #d8e0e5;}
QPushButton{background:#fff;border:1px solid #cbd6dc;border-radius:4px;padding:7px 12px;} QPushButton:hover{background:#eaf2f3;border-color:#81aaa7;} QPushButton:pressed{background:#d3e9e5;} QPushButton:disabled,QToolButton:disabled{color:#9ca8b0;background:#f2f4f5;}
QPushButton[primary="true"]{background:#26796d;color:white;border-color:#26796d;font-weight:600;} QPushButton[primary="true"]:hover{background:#1f695f;}
QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox{background:#fff;border:1px solid #cfd9de;border-radius:3px;padding:6px;min-height:20px;} QLineEdit:focus,QDoubleSpinBox:focus,QComboBox:focus{border-color:#469589;}
QGroupBox{font-weight:600;border:1px solid #d6dfe5;border-radius:4px;margin-top:14px;padding-top:12px;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;} QTabWidget::pane{border:1px solid #d6dfe5;background:#fff;} QTabBar::tab{background:#e8eef1;padding:9px 16px;border-bottom:2px solid transparent;} QTabBar::tab:selected{background:#fff;border-bottom-color:#26796d;}
QStatusBar{background:#e9eef1;border-top:1px solid #d8e0e5;color:#49616c;} QSplitter::handle{background:#dde5e9;} QScrollArea{border:0;background:#f7f9fa;} QCheckBox{spacing:6px;padding:3px;}
'''

PATHS={
 'sketch':'M3 21L7 12L19 0L24 5L12 17Z M7 12L12 17 M3 21L12 17',
 'line':'M3 21L21 3 M1 19L5 23 M19 1L23 5',
 'rectangle':'M3 5H21V19H3Z',
 'circle':'M12 3A9 9 0 1 0 12 21A9 9 0 1 0 12 3 M10 12H14 M12 10V14',
 'arc':'M3 19A10 10 0 0 1 21 7 M1 17L5 21 M19 5L23 9',
 'spline':'M2 20C3 0 10 0 12 12S22 25 23 3',
 'extrude':'M3 9L12 3L21 8L12 15Z M3 9V18L12 23L21 17V8 M12 15V23',
 'cut':'M3 9L12 3L21 8L12 15Z M3 9V18L12 23L21 17V8 M12 15V23 M12 0V10 M9 7L12 10L15 7',
 'constraint':'M8 10V6A4 4 0 0 1 16 6V10 M5 10H19V22H5Z M12 14V18',
 'assembly':'M2 5H10V13H2Z M14 11H22V19H14Z M10 9H14V15',
 'file':'M5 2H15L21 8V23H5Z M15 2V8H21',
 'save':'M3 2H19L23 6V23H3Z M7 2V9H18V2 M7 23V14H19V23',
 'open':'M2 6H10L12 9H23L19 22H2Z M2 6V3H10L13 6H20V9',
 'undo':'M8 3L2 9L8 15 M2 9H16A6 6 0 0 1 16 21H12',
 'redo':'M16 3L22 9L16 15 M22 9H8A6 6 0 0 0 8 21H12',
 'fit':'M9 2H2V9 M15 2H22V9 M2 15V22H9 M22 15V22H15 M8 8H16V16H8Z',
 'history':'M3 10A9 9 0 1 1 3 16 M2 3V10H9 M12 6V12L17 15',
 'ai':'M12 1L15 9L23 12L15 15L12 23L9 15L1 12L9 9Z',
 'origin':'M2 12H22 M12 2V22 M7 12A5 5 0 1 0 17 12A5 5 0 1 0 7 12',
 'trim':'M3 3L21 21 M3 21L21 3 M2 2H8V8H2Z M2 16H8V22H2Z',
 'mirror':'M12 1V23 M3 18V6L8 18Z M21 18V6L16 18Z',
 'pattern':'M2 2H8V8H2Z M16 2H22V8H16Z M2 16H8V22H2Z M16 16H22V22H16Z',
 'dimension':'M3 3V21 M21 3V21 M3 12H21 M7 9L3 12L7 15 M17 9L21 12L17 15',
 'delete':'M3 6H21 M8 6V2H16V6 M6 6L7 22H17L18 6 M10 10V18 M14 10V18',
}


def icon(name,color='#335f67',size=28):
    path=PATHS.get(name,PATHS['file'])
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="-1 -1 26 26"><path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pix=QPixmap(size,size);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix);QSvgRenderer(QByteArray(svg.encode())).render(p);p.end();return QIcon(pix)


def number(value=0,low=-5000,high=5000,suffix='',decimals=5):
    widget=QDoubleSpinBox();widget.setRange(low,high);widget.setDecimals(decimals);widget.setValue(float(value));widget.setKeyboardTracking(False);widget.setSuffix(suffix);widget.setMinimumWidth(86);return widget


def label(text,muted=False):
    widget=QLabel(text);widget.setWordWrap(True)
    if muted:widget.setStyleSheet('color:#70818c;font-size:11px;')
    return widget


def button(text,callback=None,primary=False):
    widget=QPushButton(text);widget.setProperty('primary',primary)
    if callback:widget.clicked.connect(callback)
    return widget


def clear_layout(layout):
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().deleteLater()
        elif item.layout():clear_layout(item.layout())


class WorkerSignals(QObject):
    done=Signal(object)
    failed=Signal(str)


class Worker(QRunnable):
    def __init__(self,fn):super().__init__();self.fn=fn;self.signals=WorkerSignals()
    @Slot()
    def run(self):
        try:self.signals.done.emit(self.fn())
        except Exception as exc:
            from pydantic import ValidationError
            if isinstance(exc,ValidationError):message='\n'.join(e['msg'].removeprefix('Value error, ') for e in exc.errors())
            else:message=str(exc)
            self.signals.failed.emit(message)
