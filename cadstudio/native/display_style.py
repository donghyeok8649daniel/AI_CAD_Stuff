"""Local, saved grid/axis appearance shared by 2D and 3D views."""
import os
from pathlib import Path
from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QColorDialog,QMessageBox
from pydantic import BaseModel,Field,ConfigDict
from .widgets import number,button,label


class DisplayStyle(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    grid_color:str=Field(default='#597d8f',pattern=r'^#[0-9a-fA-F]{6}$')
    x_color:str=Field(default='#e77373',pattern=r'^#[0-9a-fA-F]{6}$')
    y_color:str=Field(default='#69c994',pattern=r'^#[0-9a-fA-F]{6}$')
    z_color:str=Field(default='#79aafa',pattern=r'^#[0-9a-fA-F]{6}$')
    grid_brightness:float=Field(default=20,ge=0,le=100)
    axes_brightness:float=Field(default=100,ge=0,le=100)
    grid_width:float=Field(default=1,ge=.5,le=5)
    axes_width:float=Field(default=2,ge=.5,le=5)


def color(style,key,brightness):
    result=QColor(getattr(style,key));result.setAlphaF(getattr(style,brightness)/100);return result


class DisplayPreferences(QObject):
    changed=Signal()
    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=Path(path);self.style=DisplayStyle()
        try:
            if self.path.stat().st_size<10000:self.style=DisplayStyle.model_validate_json(self.path.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    def set(self,style,persist=False):
        value=DisplayStyle.model_validate(style).model_copy(deep=True)
        if persist:
            self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp')
            try:temp.write_text(value.model_dump_json(indent=2),encoding='utf-8');os.replace(temp,self.path)
            finally:temp.unlink(missing_ok=True)
        self.style=value;self.changed.emit()


def preferences():
    app=QApplication.instance();result=getattr(app,'cad_display_preferences',None)
    if result is None:
        root=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(os.getenv('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PromptCADStudio')))
        result=DisplayPreferences(root/'display-settings.json',app);app.cad_display_preferences=result
    return result


class DisplayStyleDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('격자 · 축 모양');self.resize(420,440);self.prefs=preferences();self.original=self.prefs.style.model_copy(deep=True);self.values=self.original.model_dump();self.colors={};self.fields={}
        layout=QVBoxLayout(self);layout.addWidget(label('색상·밝기·선 굵기가 스케치와 3D 화면에 즉시 반영됩니다. 저장하면 다음 실행에도 유지됩니다.',True));form=QFormLayout();layout.addLayout(form)
        for key,title in [('grid_color','격자 색'),('x_color','X축 색'),('y_color','Y축 색'),('z_color','Z축 색')]:
            b=button('',lambda _,k=key:self.pick_color(k));self.colors[key]=b;form.addRow(title,b)
        for key,title,suffix,lo,hi in [('grid_brightness','격자 밝기',' %',0,100),('axes_brightness','축 밝기',' %',0,100),('grid_width','격자 선 굵기',' px',.5,5),('axes_width','축 선 굵기',' px',.5,5)]:
            w=number(self.values[key],lo,hi,suffix,decimals=1);self.fields[key]=w;form.addRow(title,w);w.valueChanged.connect(lambda value,k=key:self.set_value(k,value))
        layout.addWidget(button('기본 모양으로',self.reset));row=QHBoxLayout();row.addStretch();row.addWidget(button('취소',self.reject));row.addWidget(button('모양 저장',self.accept,True));layout.addLayout(row);self.refresh_colors()
    def refresh_colors(self):
        for key,b in self.colors.items():
            c=QColor(self.values[key]);b.setText(c.name().upper());b.setStyleSheet('background:'+c.name()+';color:'+('#101820' if c.lightness()>140 else '#ffffff')+';')
    def pick_color(self,key):
        c=QColorDialog.getColor(QColor(self.values[key]),self,'색 선택')
        if c.isValid():self.set_value(key,c.name());self.refresh_colors()
    def set_value(self,key,value):
        self.values[key]=value;self.prefs.set(self.values)
    def reset(self):
        self.values=DisplayStyle().model_dump()
        for key,w in self.fields.items():w.blockSignals(True);w.setValue(self.values[key]);w.blockSignals(False)
        self.refresh_colors();self.prefs.set(self.values)
    def accept(self):
        try:self.prefs.set(self.values,persist=True)
        except OSError as exc:QMessageBox.warning(self,'설정 저장 실패',str(exc));return
        super().accept()
    def done(self,result):
        if result!=QDialog.DialogCode.Accepted:self.prefs.set(self.original)
        super().done(result)
