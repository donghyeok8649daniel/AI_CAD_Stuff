"""Small native widgets and a consistent CAD palette."""
from PySide6.QtCore import Qt,QObject,QRunnable,Signal,Slot,QSize,QByteArray
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor,QFont
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDoubleSpinBox,QLabel,QPushButton,QFormLayout,QWidget,QVBoxLayout,QHBoxLayout

STYLE='''
QWidget{font-family:"Malgun Gothic";font-size:12px;color:#d7e2ec;}
QMainWindow,QDialog,QWidget#nativeCADMainWindow{background:#141d27;}
QMenuBar,QMenu,QToolBar{background:#1b2531;color:#d7e2ec;}
QMenuBar{padding:5px 8px;border-bottom:1px solid #2b3948;} QMenuBar::item{padding:5px 10px;border-radius:4px;} QMenuBar::item:selected{background:#2b3c4b;}
QMenu{border:1px solid #3a4b5c;padding:5px;} QMenu::item{padding:8px 30px;border-radius:4px;} QMenu::item:selected{background:#234c4e;color:#d6fff5;} QMenu::separator{height:1px;background:#344453;margin:5px 8px;}
QToolBar{border:0;border-bottom:1px solid #30404f;spacing:3px;padding:6px;} QToolBar::separator{width:1px;background:#354554;margin:8px;}
QToolButton{padding:7px 9px;border:1px solid transparent;border-radius:6px;background:transparent;} QToolButton:hover{background:#2a3b48;border-color:#365260;} QToolButton:checked{background:#204944;border-color:#3bb39f;color:#aef3e1;}
QDockWidget{font-weight:600;} QDockWidget::title{background:#202c39;color:#a9bdce;padding:9px 12px;} QDockWidget::close-button,QDockWidget::float-button{padding:2px;}
QTreeWidget,QListWidget,QTableWidget,QPlainTextEdit,QTextEdit{background:#17222e;border:1px solid #2c3d4c;border-radius:5px;selection-background-color:#244f50;selection-color:#d9fff6;alternate-background-color:#1c2935;}
QTreeWidget::item,QListWidget::item{padding:7px 5px;border-radius:4px;} QTreeWidget::item:hover,QListWidget::item:hover{background:#253845;} QHeaderView::section{background:#202d3b;padding:7px;border:0;border-bottom:1px solid #344858;}
QPushButton{background:#263644;color:#dce6ee;border:1px solid #405363;border-radius:6px;padding:8px 12px;} QPushButton:hover{background:#304858;border-color:#68969e;} QPushButton:pressed{background:#1d5350;}
QPushButton:disabled,QToolButton:disabled{color:#6f8292;background:#1b2733;border-color:#2d3b47;}
QPushButton[primary="true"]{background:#187d72;color:#f3fffb;border-color:#2dac99;font-weight:600;} QPushButton[primary="true"]:hover{background:#209588;border-color:#68d7bd;}
QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox{background:#111c27;color:#e3edf4;border:1px solid #384d60;border-radius:5px;padding:7px;min-height:20px;selection-background-color:#267d78;}
QLineEdit:focus,QDoubleSpinBox:focus,QComboBox:focus,QPlainTextEdit:focus{border-color:#43bca7;background:#162630;}
QComboBox QAbstractItemView{background:#203240;color:#e1ecf4;selection-background-color:#28635e;selection-color:#f3fffc;}
QGroupBox{font-weight:600;border:1px solid #344858;border-radius:6px;margin-top:14px;padding-top:12px;} QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;color:#a8c6d4;}
QTabWidget::pane{border:1px solid #314553;background:#1a2733;} QTabBar::tab{background:#1a2733;color:#9db3c3;padding:10px 13px;border-bottom:2px solid transparent;} QTabBar::tab:selected{background:#213a42;color:#b7f6e8;border-bottom:2px solid #44c6b0;} QTabBar::tab:hover{background:#283d49;}
QStatusBar{background:#111b26;border-top:1px solid #2b3e4d;color:#a1b9c9;} QSplitter::handle{background:#304453;width:3px;height:3px;} QScrollArea{border:0;background:#1a2733;}
QCheckBox{spacing:7px;padding:4px 0;} QCheckBox::indicator{width:15px;height:15px;border:1px solid #537080;border-radius:3px;background:#182631;} QCheckBox::indicator:checked{background:#2dac99;border:3px solid #204e4b;}
QScrollBar:vertical{background:#16232e;width:11px;margin:0;} QScrollBar::handle:vertical{background:#405766;border-radius:5px;min-height:28px;} QScrollBar::handle:vertical:hover{background:#617d89;} QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QScrollBar:horizontal{background:#16232e;height:11px;margin:0;} QScrollBar::handle:horizontal{background:#405766;border-radius:5px;min-width:28px;} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}
QToolTip{background:#243e49;color:#e1f8f3;border:1px solid #567e86;padding:6px;border-radius:4px;}
'''

def apply_theme(app):
    from PySide6.QtGui import QPalette
    palette=QPalette()
    for role,color in [('Window','#1a2733'),('WindowText','#d7e2ec'),('Base','#111c27'),('AlternateBase','#1c2935'),('Text','#e1eaf3'),('Button','#263644'),('ButtonText','#d7e2ec'),('Highlight','#28635e'),('HighlightedText','#f3fffc'),('ToolTipBase','#243e49'),('ToolTipText','#e1f8f3'),('PlaceholderText','#829bac'),('Link','#64d0bd'),('Light','#506474'),('Mid','#344858'),('Dark','#101a24')]:
        palette.setColor(getattr(QPalette.ColorRole,role),QColor(color))
    app.setPalette(palette);app.setStyleSheet(STYLE);app.styleHints().setColorScheme(Qt.ColorScheme.Dark)


PATHS={
 'specimen':'M2 4H7L10 9H14L17 4H22V20H17L14 15H10L7 20H2Z M10 12H14',
 'check':'M4 12L10 18L22 5',
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


def icon(name,color='#9fc8d2',size=28):
    path=PATHS.get(name,PATHS['file'])
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="-1 -1 26 26"><path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pix=QPixmap(size,size);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix);QSvgRenderer(QByteArray(svg.encode())).render(p);p.end();return QIcon(pix)


def number(value=0,low=-5000,high=5000,suffix='',decimals=5):
    widget=QDoubleSpinBox();widget.setRange(low,high);widget.setDecimals(decimals);widget.setValue(float(value));widget.setKeyboardTracking(False);widget.setSuffix(suffix);widget.setMinimumWidth(86);return widget


def label(text,muted=False):
    widget=QLabel(text);widget.setWordWrap(True)
    if muted:widget.setStyleSheet('color:#9bb2c3;font-size:11px;')
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
        try:result=self.fn()
        except Exception as exc:
            from pydantic import ValidationError
            if isinstance(exc,ValidationError):message='\n'.join(e['msg'].removeprefix('Value error, ') for e in exc.errors())
            else:message=str(exc)
            try:self.signals.failed.emit(message)
            except RuntimeError:pass  # Application already disposed the receiver.
        else:
            try:self.signals.done.emit(result)
            except RuntimeError:pass
