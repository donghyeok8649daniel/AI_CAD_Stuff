"""Context-aware shortcuts; typing in a dimension/prompt never runs a tool."""
from pathlib import Path
import sys
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import QApplication,QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox,QComboBox,QDialog,QVBoxLayout,QTextBrowser


class ShortcutRouter(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;QApplication.instance().installEventFilter(self)
    def eventFilter(self,obj,event):
        w=self.window
        if event.type() not in (QEvent.Type.KeyPress,QEvent.Type.ShortcutOverride) or QApplication.activeWindow()!=w:return False
        focus=QApplication.focusWidget()
        if isinstance(focus,(QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox,QComboBox)):
            if event.type()==QEvent.Type.ShortcutOverride and event.modifiers()&Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_A,Qt.Key.Key_C,Qt.Key.Key_V,Qt.Key.Key_X,Qt.Key.Key_Z,Qt.Key.Key_Y):event.accept();return True
            return False
        if event.type()!=QEvent.Type.KeyPress or w.busy or w.sketching:return False
        key=event.key();mods=event.modifiers()
        if mods==Qt.KeyboardModifier.ControlModifier:
            commands={Qt.Key.Key_C:w.copy_parts,Qt.Key.Key_V:w.paste_parts,Qt.Key.Key_X:w.cut_parts,Qt.Key.Key_A:w.select_all_parts,Qt.Key.Key_G:w.group_parts}
            if key in commands:commands[key]();return True
        if mods==(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier):
            if key==Qt.Key.Key_G:w.ungroup_parts();return True
            if key==Qt.Key.Key_Z:w.redo();return True
        if mods==Qt.KeyboardModifier.ShiftModifier and Qt.Key.Key_1<=key<=Qt.Key.Key_6:
            w.viewport.filter.setCurrentIndex(key-Qt.Key.Key_1);w.viewport.widget.setFocus();return True
        if mods==Qt.KeyboardModifier.ControlModifier and key==Qt.Key.Key_D:w.duplicate_part();return True
        if mods==Qt.KeyboardModifier.ShiftModifier and key==Qt.Key.Key_E:w.edit_sketch();return True
        if mods!=Qt.KeyboardModifier.NoModifier:return False
        if key in (Qt.Key.Key_B,Qt.Key.Key_J):w.actions['box_select' if key==Qt.Key.Key_B else 'joints'].trigger();return True
        if key==Qt.Key.Key_Escape:
            if w.actions['box_select'].isChecked():w.actions['box_select'].trigger()
            w.select_parts([]);return True
        if key==Qt.Key.Key_T:w.thread_dialog();return True
        if Qt.Key.Key_1<=key<=Qt.Key.Key_4:w.viewport.set_view(('iso','top','front','right')[key-Qt.Key.Key_1]);return True
        commands={Qt.Key.Key_S:lambda:w.start_face_sketch() if w.viewport.face and w.viewport.face[1] and w.viewport.face[1]['planar'] else w.start_sketch(w.plane.currentData()),Qt.Key.Key_E:w.extrude_dialog,Qt.Key.Key_H:w.hole_dialog,Qt.Key.Key_I:w.measure_dialog,Qt.Key.Key_F:w.fit,Qt.Key.Key_U:w.parameter_dialog,Qt.Key.Key_A:lambda:(w.ai_dock.show(),w.ai_dock.raise_(),w.prompt.setFocus()),Qt.Key.Key_Delete:w.delete_part,Qt.Key.Key_Escape:w.viewport.clear_face}
        if key in commands:commands[key]();return True
        return False


def show_manual(parent):
    dialog=QDialog(parent);dialog.setWindowTitle('Prompt CAD Studio · 사용 설명서 / 단축키');dialog.resize(860,740);layout=QVBoxLayout(dialog);view=QTextBrowser();view.setOpenExternalLinks(False);layout.addWidget(view)
    path=Path(__file__).resolve().parents[2]/'docs'/'USER_MANUAL_KO.md'
    if not path.exists():path=Path(sys.executable).parent/'docs'/'USER_MANUAL_KO.md'
    view.setMarkdown(path.read_text(encoding='utf-8') if path.exists() else '설치 폴더의 docs/USER_MANUAL_KO.md를 열어주세요.');dialog.exec()
