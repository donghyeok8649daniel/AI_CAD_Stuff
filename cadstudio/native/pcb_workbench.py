"""PCB workspace with local drafts and explicit CAD/electrical commits."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QThreadPool
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QTransform
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,
    QTabWidget,QSplitter,QDialog,QDialogButtonBox,QCheckBox,QFileDialog,QHeaderView,QAbstractItemView,QGroupBox,
    QScrollArea,QLayout,QGridLayout)
from ..pcb import (PCBProject,PCBComponent,PCBTrack,PCBPoint,PCBVia,new_component,divider_example,pad_positions,
    copper_layers,via_layers,pcb_digest,inspect_layout,bom_report,bom_csv)
from ..pcb_simulation import simulate_pcb,spice_netlist
from ..pcb_plugin import design_digest,with_pcb,electrical_preview
from ..pcb_workflow import PCBWorkflowSession
from .widgets import Worker


def number(value,lo,hi,decimals=6):
    w=QDoubleSpinBox();w.setRange(lo,hi);w.setDecimals(decimals);set_number(w,value);return w


def set_number(widget,value):
    widget.setValue(value);widget._pcb_original_value=value;widget._pcb_display_value=widget.value()


def number_value(widget):
    value=widget.value()
    return widget._pcb_original_value if value==widget._pcb_display_value else value


def push(text,fn,name=''):
    w=QPushButton(text);w.clicked.connect(fn)
    if name:w.setObjectName(name)
    return w


COPPER_COLORS={'F.Cu':'#f88d55','In1.Cu':'#d18bf5','In2.Cu':'#72d493',
    'In3.Cu':'#e6cf67','In4.Cu':'#ed9bb9','In5.Cu':'#65ccdc','In6.Cu':'#d6a576','B.Cu':'#659de5'}


def net_description(project,net):
    if net is None:return 'NC'
    label=project.net_labels.get(net,net)
    return net+(' · '+label if label!=net else '')


def pad_copper_path(pad):
    """World-space copper outline, including the circular drill cutout."""
    width,height=pad['size_x_mm'],pad['size_y_mm'];rect=QRectF(-width/2,-height/2,width,height)
    path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
    if pad['shape']=='circle':path.addEllipse(rect)
    elif pad['shape']=='rect':path.addRect(rect)
    else:
        radius=min(width,height)*(0.5 if pad['shape']=='oval' else pad['roundrect_rratio'])
        path.addRoundedRect(rect,radius,radius)
    if pad['drill_mm']:
        radius=pad['drill_mm']/2;path.addEllipse(QPointF(0,0),radius,radius)
    transform=QTransform();transform.translate(pad['x'],pad['y']);transform.rotate(pad['rotation_deg'])
    return transform.map(path)


def via_copper_path(via):
    path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
    path.addEllipse(QPointF(via.x_mm,via.y_mm),via.diameter_mm/2,via.diameter_mm/2)
    path.addEllipse(QPointF(via.x_mm,via.y_mm),via.drill_mm/2,via.drill_mm/2)
    return path


def polygon_path(points,holes=()):
    path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
    for ring in [points,*holes]:
        if not ring:continue
        path.moveTo(ring[0].x_mm,ring[0].y_mm)
        for point in ring[1:]:path.lineTo(point.x_mm,point.y_mm)
        path.closeSubpath()
    return path


class PCBComponentEditor(QDialog):
    def __init__(self,parent,component,nets):
        super().__init__(parent);self.setWindowTitle('PCB 부품 · 핀 / 모델 / 가격 · Component');self.resize(1120,750);self.checked=None;self.original=component
        root=QVBoxLayout(self);tabs=QTabWidget();root.addWidget(tabs)
        basic=QWidget();form=QFormLayout(basic);tabs.addTab(basic,'부품 / 모델')
        price_notice=QLabel('제품번호를 바꾸거나 제품번호 없는 부품의 규격을 바꾸면 그대로 복사된 이전 가격을 미정으로 바꿉니다. 새 가격을 함께 입력하면 그 입력을 유지합니다.')
        price_notice.setWordWrap(True);form.addRow(price_notice)
        if getattr(component,'library_metadata',None):
            notice=QLabel('제품 참고정보가 연결돼 있습니다. 패드·몸체 치수를 바꾸면 도면 확인 상태가 미확인으로 바뀌며, 제품번호·출처를 바꾸면 기존 제품 연결을 해제합니다.')
            notice.setWordWrap(True);form.addRow(notice)
        self.ref=QLineEdit(component.ref);self.value=QLineEdit(component.value);self.mpn=QLineEdit(component.mpn);self.footprint=QLineEdit(component.footprint)
        self.source=QLineEdit(component.source_url);self.basis=QComboBox();self.basis.addItems(['declared','datasheet_reference']);self.basis.setCurrentText(component.footprint_basis)
        self.x=number(component.x_mm,-1000,1000);self.y=number(component.y_mm,-1000,1000);self.angle=number(component.rotation_deg,-360,360)
        self.bw=number(component.body_width_mm,.1,500);self.bh=number(component.body_height_mm,.1,500)
        self.fitted=QCheckBox('실장 / Fitted');self.fitted.setChecked(component.fitted)
        self.kind=QComboBox();self.kind.addItems(['resistor','capacitor','voltage_source','none','unsupported']);self.kind.setCurrentText(component.model.kind)
        self.pa=QLineEdit(component.model.pin_a or '');self.pb=QLineEdit(component.model.pin_b or '')
        self.model_value=QLineEdit(str(next((v for v in [component.model.resistance_ohm,component.model.capacitance_f,component.model.dc_voltage_v] if v is not None),'')))
        self.ac=QLineEdit(str(component.model.ac_voltage_v if component.model.ac_voltage_v is not None else ''));self.phase=number(component.model.ac_phase_deg,-360,360)
        for title,w in [('참조 / Ref',self.ref),('값 / Value',self.value),('제품번호 / MPN',self.mpn),('패드 선언 / Footprint',self.footprint),('패드 근거 / Basis',self.basis),('사양 출처 / Source',self.source),('X mm',self.x),('Y mm',self.y),('회전 °',self.angle),('몸체 폭 mm',self.bw),('몸체 높이 mm',self.bh),('실장',self.fitted),('시뮬 모델 / Model',self.kind),('모델 + 핀',self.pa),('모델 − 핀',self.pb),('R: Ω / C: F / V: DC V',self.model_value),('AC 진폭 V (peak)',self.ac),('AC 위상 °',self.phase)]:form.addRow(title,w)
        pins_page=QWidget();pins_layout=QVBoxLayout(pins_page);tabs.addTab(pins_page,'핀 / net / 패드')
        hint=QLabel('등록 net: '+', '.join(nets)+' · 좌표/회전은 부품 기준 · shape: circle / rect / oval / roundrect\n층: F.Cu, In1.Cu…In6.Cu, B.Cu (보드에서 활성화한 층만) · circle 크기 빈칸=직경 · 드릴 0=없음 · 둥근 모서리 비율 0~0.5')
        if hasattr(parent,'project'):hint.setToolTip('\n'.join(net_description(parent.project,net) for net in nets))
        hint.setWordWrap(True);pins_layout.addWidget(hint)
        self.pins=QTableWidget(0,13);self.pins.setObjectName('pcbPinGeometry');self.pins.setHorizontalHeaderLabels(['번호','이름','net (빈칸=NC)','X mm','Y mm','직경 mm','층','shape','폭 mm','높이 mm','회전 °','드릴 mm','모서리 비율']);self.pins.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);pins_layout.addWidget(self.pins)
        for pin in component.pins:self.add_pin(pin.model_dump())
        row=QHBoxLayout();row.addWidget(push('핀 추가',lambda:self.add_pin()));row.addWidget(push('선택 핀 삭제',lambda:self.pins.removeRow(self.pins.currentRow())));pins_layout.addLayout(row)
        quote_page=QWidget();qf=QFormLayout(quote_page);tabs.addTab(quote_page,'BOM / 가격')
        q=component.quote;self.price_status=QComboBox();self.price_status.addItems(['unknown','reference','quoted']);self.price_status.setCurrentText(q.status)
        self.amount=QLineEdit(str(q.unit_price) if q.unit_price is not None else '');self.currency=QLineEdit(q.currency);self.as_of=QLineEdit(q.as_of.isoformat() if q.as_of else '')
        self.supplier=QLineEdit(q.supplier);self.price_source=QLineEdit(q.source_url);self.moq=QSpinBox();self.moq.setRange(1,1000000);self.moq.setValue(q.minimum_quantity);self.pack=QSpinBox();self.pack.setRange(1,1000000);self.pack.setValue(q.pack_quantity);self.note=QLineEdit(q.note)
        for title,w in [('상태',self.price_status),('개당 금액',self.amount),('통화 (KRW / USD 등)',self.currency),('기준일 YYYY-MM-DD',self.as_of),('판매처',self.supplier),('가격 출처 HTTPS',self.price_source),('최소 구매수량',self.moq),('구매 묶음수량',self.pack),('메모',self.note)]:qf.addRow(title,w)
        qf.addRow(QLabel('저장된 참조/입력 견적 · 실시간 가격 확인과 환율 변환은 수행하지 않습니다.'))
        self.error=QLabel();self.error.setWordWrap(True);root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);root.addWidget(buttons)

    def add_pin(self,pin=None):
        defaults=dict(number='P'+str(self.pins.rowCount()+1),name='',net=None,x_mm=0,y_mm=0,diameter_mm=1,layers=['F.Cu'],shape='circle',size_x_mm=None,size_y_mm=None,rotation_deg=0,drill_mm=0,roundrect_rratio=.25)
        defaults.update(pin or {});pin=defaults
        r=self.pins.rowCount();self.pins.insertRow(r)
        for col,key in enumerate(['number','name','net','x_mm','y_mm','diameter_mm','layers','shape','size_x_mm','size_y_mm','rotation_deg','drill_mm','roundrect_rratio']):
            value=pin.get(key);self.pins.setItem(r,col,QTableWidgetItem(','.join(value) if isinstance(value,list) else str(value) if value is not None else ''))

    def candidate(self):
        def text(r,c):return self.pins.item(r,c).text().strip() if self.pins.item(r,c) else ''
        pins=[dict(number=text(r,0),name=text(r,1),net=text(r,2) or None,x_mm=float(text(r,3)),y_mm=float(text(r,4)),diameter_mm=float(text(r,5)),layers=[s.strip() for s in text(r,6).split(',')],shape=text(r,7),size_x_mm=float(text(r,8)) if text(r,8) else None,size_y_mm=float(text(r,9)) if text(r,9) else None,rotation_deg=float(text(r,10)),drill_mm=float(text(r,11)),roundrect_rratio=float(text(r,12))) for r in range(self.pins.rowCount())]
        kind=self.kind.currentText();model=dict(kind=kind,pin_a=self.pa.text().strip() or None,pin_b=self.pb.text().strip() or None,ac_phase_deg=number_value(self.phase))
        if kind in ('resistor','capacitor','voltage_source'):
            model.update(pin_a=self.pa.text().strip(),pin_b=self.pb.text().strip())
            model[{'resistor':'resistance_ohm','capacitor':'capacitance_f','voltage_source':'dc_voltage_v'}[kind]]=float(self.model_value.text())
        if kind=='voltage_source':model.update(ac_voltage_v=float(self.ac.text()) if self.ac.text().strip() else None)
        status=self.price_status.currentText()
        quote=dict(status=status,unit_price=self.amount.text().strip() or None,currency=self.currency.text().strip(),as_of=self.as_of.text().strip() or None,supplier=self.supplier.text().strip(),source_url=self.price_source.text().strip(),minimum_quantity=self.moq.value(),pack_quantity=self.pack.value(),note=self.note.text())
        candidate=PCBComponent(ref=self.ref.text().strip(),value=self.value.text(),mpn=self.mpn.text(),footprint=self.footprint.text(),footprint_basis=self.basis.currentText(),source_url=self.source.text().strip(),x_mm=number_value(self.x),y_mm=number_value(self.y),rotation_deg=number_value(self.angle),body_width_mm=number_value(self.bw),body_height_mm=number_value(self.bh),pins=pins,model=model,quote=quote,fitted=self.fitted.isChecked())
        from ..pcb_editor_data import preserve_library_metadata
        return preserve_library_metadata(self.original,candidate)

    def accept(self):
        self.checked=None
        try:self.checked=self.candidate()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc));return
        super().accept()


class PCBViaEditor(QDialog):
    def __init__(self,parent,via,nets,layers):
        super().__init__(parent);self.setWindowTitle('PCB 비아 / Via');self.checked=None;self.original=via
        root=QVBoxLayout(self);form=QFormLayout();root.addLayout(form)
        self.identifier=QLineEdit(via.id);self.net=QComboBox();self.net.addItems(nets);self.net.setCurrentText(via.net)
        for index,net in enumerate(nets):self.net.setItemData(index,net_description(parent.project,net),Qt.ItemDataRole.ToolTipRole)
        self.x=number(via.x_mm,-1000,1000);self.y=number(via.y_mm,-1000,1000)
        self.diameter=number(via.diameter_mm,.05,20);self.drill=number(via.drill_mm,0,20)
        self.layers=QLineEdit(', '.join(via.layers))
        for label,widget in [('ID',self.identifier),('net',self.net),('X mm',self.x),('Y mm',self.y),('구리 직경 mm',self.diameter),('드릴 mm',self.drill),('연결 층',self.layers)]:form.addRow(label,widget)
        hint=QLabel('층 순서: '+', '.join(layers)+'\n시작/끝 층 또는 연속된 전체 층을 쉼표로 입력하세요.');hint.setWordWrap(True);root.addWidget(hint)
        self.error=QLabel();self.error.setWordWrap(True);root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);root.addWidget(buttons)

    def candidate(self):
        return PCBVia(id=self.identifier.text().strip(),net=self.net.currentText(),x_mm=number_value(self.x),y_mm=number_value(self.y),diameter_mm=number_value(self.diameter),drill_mm=number_value(self.drill),layers=[s.strip() for s in self.layers.text().split(',')])

    def accept(self):
        self.checked=None
        try:
            candidate=self.candidate();raw=self.parentWidget().project.model_dump(mode='json')
            rows=raw.setdefault('vias',[]);row=candidate.model_dump(mode='json')
            raw['vias']=[row if item['id']==self.original.id else item for item in rows] if any(item['id']==self.original.id for item in rows) else rows+[row]
            PCBProject.model_validate(raw);self.checked=candidate
        except (ValueError,TypeError) as exc:self.error.setText(str(exc));return
        super().accept()


class PCBBoardCanvas(QWidget):
    placementChanged=Signal(str,float,float)
    routeClicked=Signal(object)
    componentSelected=Signal(str)
    viaSelected=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(320,250);self.project=PCBProject();self.selected=None;self.selected_via=None;self.routing=False;self.layer='F.Cu';self.visible_layers=set(copper_layers(self.project));self.route_points=[];self.drag=None
        self.setMouseTracking(True);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setObjectName('pcbBoardCanvas')

    def layout_transform(self):
        p=self.project;s=min((self.width()-40)/p.width_mm,(self.height()-40)/p.height_mm)
        return s,(self.width()-p.width_mm*s)/2,(self.height()-p.height_mm*s)/2

    def mm(self,pos):
        s,x,y=self.layout_transform();return ((pos.x()-x)/s,(pos.y()-y)/s)

    def drawing_layer(self,layers):
        shown=[layer for layer in copper_layers(self.project) if layer in layers and layer in self.visible_layers]
        return self.layer if self.layer in shown else shown[-1] if shown else None

    def layer_color(self,layer,alpha=255):
        color=QColor(COPPER_COLORS[layer]);color.setAlpha(alpha if layer==self.layer else min(alpha,115));return color

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.fillRect(self.rect(),QColor('#10191c'));s,x,y=self.layout_transform();p=self.project
        painter.translate(x,y);painter.scale(s,s);painter.fillRect(QRectF(0,0,p.width_mm,p.height_mm),QColor('#18352d'));painter.setPen(QPen(QColor('#63907e'),1/s));painter.drawRect(QRectF(0,0,p.width_mm,p.height_mm))
        painter.setPen(QPen(QColor('#284b40'),.6/s))
        for i in range(0,int(p.width_mm)+1,5):painter.drawLine(QPointF(i,0),QPointF(i,p.height_mm))
        for i in range(0,int(p.height_mm)+1,5):painter.drawLine(QPointF(0,i),QPointF(p.width_mm,i))
        zone_labels=[]
        for zone in sorted(p.zones,key=lambda item:item.layer==self.layer):
            if zone.layer not in self.visible_layers:continue
            for polygon in zone.filled_polygons:
                painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(self.layer_color(zone.layer,90));painter.drawPath(polygon_path(polygon.points,polygon.holes))
            painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(self.layer_color(zone.layer,200),1/s,Qt.PenStyle.SolidLine if zone.filled_polygons else Qt.PenStyle.DashLine));painter.drawPath(polygon_path(zone.outline,zone.holes))
            if not zone.filled_polygons:zone_labels.append((zone.outline[0],zone.id+' · outline / 미채움'))
        for track in sorted(p.tracks,key=lambda item:item.layer==self.layer):
            if track.layer not in self.visible_layers:continue
            color=self.layer_color(track.layer);painter.setPen(QPen(color,track.width_mm,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            path=QPainterPath();path.moveTo(track.points[0].x_mm,track.points[0].y_mm)
            for pt in track.points[1:]:path.lineTo(pt.x_mm,pt.y_mm)
            painter.drawPath(path)
        for c in p.components:
            painter.save();painter.translate(c.x_mm,c.y_mm);painter.rotate(c.rotation_deg);painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#ffffff' if c.ref==self.selected else '#a7c7b8'),1.5/s));painter.drawRect(QRectF(-c.body_width_mm/2,-c.body_height_mm/2,c.body_width_mm,c.body_height_mm));painter.restore()
        for pad in pad_positions(p):
            layer=self.drawing_layer(pad['layers'])
            if layer is None:continue
            color=self.layer_color(layer) if pad['net'] else QColor('#526765');painter.setPen(QPen(color.lighter(125),.6/s));painter.setBrush(color);painter.drawPath(pad_copper_path(pad))
            if pad['drill_mm']:
                radius=pad['drill_mm']/2;painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#0b1316'));painter.drawEllipse(QPointF(pad['x'],pad['y']),radius,radius)
        for via in p.vias:
            layer=self.drawing_layer(via_layers(p,via))
            if layer is None:continue
            color=self.layer_color(layer);painter.setPen(QPen(QColor('#ffffff') if via.id==self.selected_via else color.lighter(125),1/s));painter.setBrush(color);painter.drawPath(via_copper_path(via))
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#0b1316'));painter.drawEllipse(QPointF(via.x_mm,via.y_mm),via.drill_mm/2,via.drill_mm/2)
        painter.resetTransform();painter.setPen(QColor('#d4e6df'))
        for c in p.components:painter.drawText(QPointF(x+c.x_mm*s,y+c.y_mm*s-8),c.ref)
        for point,label in zone_labels:painter.drawText(QPointF(x+point.x_mm*s+4,y+point.y_mm*s-4),label)
        for via in p.vias:
            if via.id==self.selected_via and self.drawing_layer(via_layers(p,via)):painter.drawText(QPointF(x+via.x_mm*s+5,y+via.y_mm*s-5),via.id)
        if self.route_points:
            painter.setPen(QPen(QColor('#f8e682'),2,Qt.PenStyle.DashLine));path=QPainterPath();path.moveTo(x+self.route_points[0][0]*s,y+self.route_points[0][1]*s)
            for pt in self.route_points[1:]:path.lineTo(x+pt[0]*s,y+pt[1]*s)
            painter.drawPath(path)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:self.routeClicked.emit(dict(cancel=True));return
        if event.button()!=Qt.MouseButton.LeftButton:return
        point=self.mm(event.position())
        if self.routing:
            pads=[pad for pad in pad_positions(self.project) if self.layer in self.visible_layers and self.layer in pad['layers'] and pad_copper_path(pad).contains(QPointF(*point))]
            vias=[via for via in self.project.vias if self.layer in self.visible_layers and self.layer in via_layers(self.project,via) and via_copper_path(via).contains(QPointF(*point))]
            self.routeClicked.emit(dict(point=point,pad=pads[0] if pads else None,via=vias[0] if vias and not pads else None));return
        vias=[via for via in self.project.vias if self.drawing_layer(via_layers(self.project,via)) and via_copper_path(via).contains(QPointF(*point))]
        if vias:
            self.selected_via=vias[-1].id;self.selected=None;self.viaSelected.emit(self.selected_via);self.update();return
        hits=[c for c in self.project.components if ((point[0]-c.x_mm)**2+(point[1]-c.y_mm)**2)**.5 <= max(3,c.body_width_mm/2,c.body_height_mm/2)]
        if hits:
            c=min(hits,key=lambda c:(point[0]-c.x_mm)**2+(point[1]-c.y_mm)**2);self.selected=c.ref;self.selected_via=None;self.drag=(c.ref,c.x_mm-point[0],c.y_mm-point[1]);self.componentSelected.emit(c.ref);self.update()

    def mouseReleaseEvent(self,event):
        if self.drag:
            ref,dx,dy=self.drag;self.drag=None;x,y=self.mm(event.position());self.placementChanged.emit(ref,round(x+dx,3),round(y+dy,3))

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.routeClicked.emit(dict(cancel=True))
        else:super().keyPressEvent(event)


class PCBWorkbench(QWidget):
    applyRequested=Signal(object)
    def __init__(self,parent,raw):
        super().__init__(parent);self.host=parent;self.setObjectName('pcbWorkbench');self.base=deepcopy(raw);self.base_sha=design_digest(raw);self.project=PCBProject.model_validate(raw.get('pcb') or {});self.dirty=False;self.alive=True;self.advice_task=None;self.simulation_result=None;self.route=None
        self.workflow=PCBWorkflowSession(self.project);self.preview_project=None;self.locked_refs=set()
        self.workflow_task=None;self._workflow_workers=[];self.workflow_nonce=0;self.workflow_result=None;self._workflow_controls=[];self.cost_proposal=None
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.workbench_scroll=QScrollArea();self.workbench_scroll.setObjectName('pcbWorkbenchScroll');self.workbench_scroll.setWidgetResizable(True);outer.addWidget(self.workbench_scroll)
        contents=QWidget();contents.setObjectName('pcbWorkbenchContents');root=QVBoxLayout(contents);root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);self.workbench_scroll.setWidget(contents)
        top=QHBoxLayout();root.addLayout(top)
        top.addWidget(QLabel('PCB  /  설계 · 배선 · 시뮬레이션'))
        for title,callback,name in [('CAD에 PCB 저장',lambda:self.request_apply(False),'pcbApply'),('PCB + 전장에 명시 적용',lambda:self.request_apply(True),'pcbElectricalApply')]:
            control=push(title,callback,name);top.addWidget(control);self._workflow_controls.append(control)
        top.addWidget(push('문서에서 다시 불러오기',self.reload,'pcbReload'))
        tools=QHBoxLayout();root.addLayout(tools)
        for title,callback,name in [('빈 보드',lambda:self.replace_project(PCBProject()),''),('분압 예제',lambda:self.replace_project(divider_example()),'pcbExample'),('PCB 열기',self.load_file,'')]:
            control=push(title,callback,name);tools.addWidget(control);self._workflow_controls.append(control)
        tools.addWidget(push('PCB 내보내기',lambda:self.export_file('pcb')));tools.addWidget(push('BOM CSV',lambda:self.export_file('bom')));tools.addWidget(push('SPICE netlist',lambda:self.export_file('spice')))
        groups=QHBoxLayout();root.addLayout(groups)
        for title,actions in [
            ('1. 부품 배치 · Place', [('부품 추가 / Add',self.add_component,'pcbPlaceAdd'),('임베디드 제품 찾기 / Products',self.embedded_product,'pcbEmbeddedProduct'),('대응 핀 정렬 / Align pins',self.align_selected,'pcbAlignPins'),('이동·회전 / Edit',lambda:self.edit_component(),'pcbPlaceEdit'),('선택 고정/해제 / Lock',self.toggle_locked,'pcbPlacementLock')]),
            ('2. 배선 만들기 · Connect', [('배선 연결하기 / Connect traces',self.begin_routing,'pcbConnectTrace'),('비아 뚫기 / Add via',self.begin_via,'pcbDrillVia')]),
            ('3. 검사·최적화 · Review', [('배치 최적화 / Optimize placement',lambda:self.start_workflow('placement'),'pcbOptimizePlacement'),('현재 층 배선 검사 / Check layer',lambda:self.start_workflow('routing'),'pcbCheckCurrentLayer'),('층 수 비교 / Compare layers',lambda:self.start_workflow('layers'),'pcbCompareLayers')])]:
            group=QGroupBox(title);actions_layout=QVBoxLayout(group)
            for text,callback,name in actions:
                control=push(text,callback,name);actions_layout.addWidget(control);self._workflow_controls.append(control)
            actions_layout.addStretch(1)
            groups.addWidget(group)
        self.stack_status=QLabel();self.stack_status.setObjectName('pcbLayerStackSummary');self.stack_status.setWordWrap(True);root.addWidget(self.stack_status)
        self.route_hint=QLabel('시작 패드 → 꺾임점 → 같은 연결 그룹의 끝 패드 / Start pad → corners → end pad on the same net. 비아는 구리층을 연결합니다. / Vias join copper layers.');self.route_hint.setObjectName('pcbRoutingSteps');self.route_hint.setWordWrap(True);root.addWidget(self.route_hint)
        self.workflow_report=QPlainTextEdit();self.workflow_report.setObjectName('pcbWorkflowReport');self.workflow_report.setReadOnly(True);self.workflow_report.setMaximumHeight(130);root.addWidget(self.workflow_report)
        preview_row=QGridLayout();root.addLayout(preview_row)
        self.trial_choice=QComboBox();self.trial_choice.setObjectName('pcbLayerTrials');preview_row.addWidget(self.trial_choice,0,0,1,2)
        self.trial_preview=push('선택안 미리보기 / Preview trial',self.preview_trial,'pcbPreviewTrial');preview_row.addWidget(self.trial_preview,0,2)
        self.preview_apply=push('미리보기 → PCB 초안에 적용 / Apply preview',self.apply_workflow_preview,'pcbApplyWorkflowPreview');preview_row.addWidget(self.preview_apply,1,0)
        self.preview_cancel=push('미리보기 취소 / Cancel preview',self.cancel_workflow_preview,'pcbCancelWorkflowPreview');preview_row.addWidget(self.preview_cancel,1,1)
        self.workflow_cancel=push('계산 취소 / Cancel calculation',self.cancel_workflow,'pcbCancelWorkflow');preview_row.addWidget(self.workflow_cancel,1,2)
        undo_row=QHBoxLayout();root.addLayout(undo_row)
        self.undo_button=push('PCB 초안 되돌리기 / Undo',self.undo_draft,'pcbDraftUndo');undo_row.addWidget(self.undo_button)
        self.redo_button=push('PCB 초안 다시 실행 / Redo',self.redo_draft,'pcbDraftRedo');undo_row.addWidget(self.redo_button)
        note=QLabel('미리보기 적용은 PCB 초안만 바꿉니다. 전체 CAD 저장은 상단 버튼으로 따로 적용하세요. / Preview applies to the PCB draft only; save to CAD separately.');note.setWordWrap(True);undo_row.addWidget(note,1)
        splitter=QSplitter();splitter.setObjectName('pcbEditorSplitter');splitter.setChildrenCollapsible(False);splitter.setMinimumHeight(360);root.addWidget(splitter,1)
        left=QWidget();left.setMinimumWidth(360);ll=QVBoxLayout(left);ll.setContentsMargins(0,0,0,0);splitter.addWidget(left);self.canvas=PCBBoardCanvas();splitter.addWidget(self.canvas);splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,1);splitter.setSizes([460,420])
        self.tabs=QTabWidget();self.tabs.setUsesScrollButtons(True);self.tabs.setElideMode(Qt.TextElideMode.ElideRight);ll.addWidget(self.tabs)
        def tab_page(title):
            page=QScrollArea();page.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);page.setWidget(body);self.tabs.addTab(page,title)
            return page,layout
        layout_page,lp=tab_page('배치 / 배선');self.layout_page=layout_page
        form=QFormLayout();lp.addLayout(form);self.board_name=QLineEdit(self.project.name);self.width=number(self.project.width_mm,2,500);self.height=number(self.project.height_mm,2,500);self.nets=QLineEdit(', '.join(self.project.nets));self.clearance=number(self.project.clearance_mm,.05,5);self.edge=number(self.project.edge_clearance_mm,0,10)
        self.layer_count=QComboBox();self.layer_count.setObjectName('pcbLayerCount')
        for count in (2,4,6,8):self.layer_count.addItem(f'{count}층 / {count} layers',count)
        self.layer_count.setCurrentIndex(self.layer_count.findData(self.project.layer_count))
        for title,w in [('이름',self.board_name),('보드 폭 mm',self.width),('보드 높이 mm',self.height),('구리 층 수',self.layer_count),('net (쉼표 구분)',self.nets),('net 간격 mm',self.clearance),('경계 여유 mm',self.edge)]:form.addRow(title,w)
        lp.addWidget(push('보드 조건 적용',self.edit_board))
        self.components=QTableWidget(0,3);self.components.setHorizontalHeaderLabels(['참조','값 / 모델','net']);self.components.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.components.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.components.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.components.cellDoubleClicked.connect(lambda *_:self.edit_component());self.components.itemSelectionChanged.connect(self.component_selection_changed);lp.addWidget(self.components)
        row=QHBoxLayout();self.add_kind=QComboBox();self.add_kind.addItems(['resistor','capacitor','voltage_source','none','unsupported']);row.addWidget(self.add_kind);row.addWidget(push('추가',self.add_component,'pcbAdd'));row.addWidget(push('핀 / 모델 / 가격 편집',lambda:self.edit_component(),'pcbComponentEdit'));row.addWidget(push('삭제',self.delete_component));lp.addLayout(row)
        row=QHBoxLayout();self.route_button=QCheckBox('배선 연결하기 · Connect traces');self.route_button.toggled.connect(self.set_routing);row.addWidget(self.route_button);self.layer=QComboBox();self.layer.setObjectName('pcbActiveLayer');self.layer.addItems(copper_layers(self.project));self.layer.currentTextChanged.connect(self.layer_changed);row.addWidget(self.layer);self.track_width=number(.25,.05,10);self.track_width.setToolTip('배선 폭 mm / Trace width in mm');row.addWidget(self.track_width);lp.addLayout(row)
        row=QGridLayout();row.addWidget(QLabel('표시 / Visible'),0,0,1,4);self.layer_visibility={}
        for index,layer in enumerate(COPPER_COLORS):
            box=QCheckBox(layer);box.setObjectName('pcbVisible'+layer.replace('.',''));box.setChecked(True);box.setStyleSheet('color: '+COPPER_COLORS[layer]);box.toggled.connect(self.visibility_changed);self.layer_visibility[layer]=box;row.addWidget(box,1+index//4,index%4)
        lp.addLayout(row)
        help_label=QLabel('부품 드래그로 배치 · 배선: 패드/비아 → 꺾임점 → 같은 net 패드/비아\n우클릭 / Esc 취소 · 다층 패드 또는 비아에서 층을 바꿔 배선');help_label.setWordWrap(True);lp.addWidget(help_label)
        self.tracks=QComboBox();lp.addWidget(self.tracks);lp.addWidget(push('선택 배선 삭제',self.delete_track));lp.addWidget(push('배치 / 구리 연결 검사',self.check_layout,'pcbLayoutCheck'))
        sim_page,sl=tab_page('시뮬레이션 / AI');sf=QFormLayout();sl.addLayout(sf)
        self.analysis=QComboBox();self.analysis.addItems(['dc','ac']);self.analysis.setCurrentText(self.project.simulation.analysis);self.frequency=number(self.project.simulation.frequency_hz,.001,1e9)
        sf.addRow('해석',self.analysis);sf.addRow('AC 주파수 Hz',self.frequency);sl.addWidget(push('명시 실행 · Simulate',self.simulate,'pcbSimulate'))
        self.sim_text=QPlainTextEdit();self.sim_text.setReadOnly(True);sl.addWidget(self.sim_text,1)
        self.question=QPlainTextEdit('이 PCB의 net·배치·배선과 회로 모델을 검토하고, 개선안을 설명해 주세요.');self.question.setMaximumHeight(90);sl.addWidget(self.question)
        row=QHBoxLayout();row.addWidget(push('Codex PCB 설계 자문',self.review,'pcbAI'));self.cancel_button=push('자문 취소',self.stop_advice,'pcbAICancel');self.cancel_button.setEnabled(False);row.addWidget(self.cancel_button);sl.addLayout(row)
        self.advice=QPlainTextEdit();self.advice.setReadOnly(True);sl.addWidget(self.advice,1)
        bom_page,bl=tab_page('BOM / 예산');self.bom_page=bom_page;bf=QFormLayout();bl.addLayout(bf);self.quantity=QSpinBox();self.quantity.setRange(1,100000);self.quantity.setValue(self.project.budget.board_quantity);self.currency=QLineEdit(self.project.budget.currency);self.limit=QLineEdit(str(self.project.budget.limit) if self.project.budget.limit is not None else '')
        for title,w in [('보드 수량',self.quantity),('예산 통화',self.currency),('예산 한도 (빈칸=미정)',self.limit)]:bf.addRow(title,w)
        bl.addWidget(push('BOM / 예산 계산',self.update_budget,'pcbBOM'));self.bom_text=QPlainTextEdit();self.bom_text.setReadOnly(True);bl.addWidget(self.bom_text)
        bl.addWidget(push('제품 중복 제외 · 입력 견적 계산',self.cost_estimate,'pcbCostEstimate'))
        bl.addWidget(push('수량별 단가 · 제작·배송·세금 입력',self.edit_cost_inputs,'pcbCostInputs'))
        self.cost_question=QLineEdit('이 BOM의 누락된 견적 조건과 구매 모듈 중복 여부를 검토해 주세요.');bl.addWidget(self.cost_question)
        bl.addWidget(push('Codex 가격·견적 자문',lambda:self.review('cost'),'pcbCostAI'))
        bl.addWidget(push('AI 가격 범위 제안 생성',lambda:self.review('cost_proposal'),'pcbCostProposal'))
        self.cost_preview_button=push('AI 가격안 미리보기 · 명시 채택',self.preview_cost_proposal,'pcbCostProposalPreview');self.cost_preview_button.setEnabled(False);bl.addWidget(self.cost_preview_button)
        via_page,vl=tab_page('비아 / 구리 영역');self.via_page=via_page
        self.vias=QTableWidget(0,6);self.vias.setObjectName('pcbVias');self.vias.setHorizontalHeaderLabels(['ID','net','X / Y mm','구리 / 드릴 mm','연결 층','실제 층']);self.vias.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.vias.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.vias.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.vias.cellDoubleClicked.connect(lambda *_:self.edit_via());self.vias.itemSelectionChanged.connect(self.via_selection_changed);vl.addWidget(self.vias)
        row=QHBoxLayout();row.addWidget(push('비아 추가',self.add_via,'pcbViaAdd'));row.addWidget(push('선택 비아 편집',self.edit_via,'pcbViaEdit'));row.addWidget(push('선택 비아 삭제',self.delete_via,'pcbViaDelete'));vl.addLayout(row)
        self.zones=QTableWidget(0,4);self.zones.setObjectName('pcbZones');self.zones.setHorizontalHeaderLabels(['ID','net','층','구리 상태']);self.zones.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.zones.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);vl.addWidget(self.zones)
        note=QLabel('저장된 채움 polygon만 구리로 표시합니다. outline / 미채움은 점선 경계이며 구리 채움이 아닙니다.\n비아·구리 영역 편집도 초안입니다. 검토 후 상단 저장 버튼으로 명시 적용하세요.');note.setWordWrap(True);vl.addWidget(note)
        review_page,rl=tab_page('제품·전원 조건 검사')
        condition_note=QLabel('실제 동작 조건을 아는 값만 입력하세요. 빈칸은 미확인입니다. 제품의 권장 어댑터 전류는 소비전류가 아닙니다.\n전압은 공통 기준 전위이며 핀 검사에서는 지정한 GND 반환 net과의 차이를 사용합니다.');condition_note.setWordWrap(True);rl.addWidget(condition_note)
        self.net_conditions=QTableWidget(0,6);self.net_conditions.setHorizontalHeaderLabels(['net','전위 V','전원 한도 A','전체 부하 A','출처','동작 조건']);self.net_conditions.itemChanged.connect(self.operating_conditions_changed);rl.addWidget(self.net_conditions)
        control=push('배치·전압·전류 조건 검사',lambda:self.start_workflow('stability'),'pcbEmbeddedReview');rl.addWidget(control);self._workflow_controls.append(control)
        self.embedded_report=QPlainTextEdit();self.embedded_report.setReadOnly(True);rl.addWidget(self.embedded_report,1)
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        for control in self.findChildren(QWidget):
            if isinstance(control,QPushButton):control.setMinimumHeight(max(32,control.sizeHint().height()))
            elif isinstance(control,(QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox)):control.setMinimumHeight(max(28,control.sizeHint().height()))
        for table in (self.components,self.vias,self.zones,self.net_conditions):table.setMinimumHeight(120)
        for text in (self.sim_text,self.advice,self.bom_text,self.embedded_report):text.setMinimumHeight(120)
        self.question.setMinimumHeight(72);self.workflow_report.setMinimumHeight(72)
        self.canvas.placementChanged.connect(self.move_component);self.canvas.componentSelected.connect(self.select_component);self.canvas.viaSelected.connect(self.select_via);self.canvas.routeClicked.connect(self.route_click);self.redraw();self.update_workflow_controls()

    def error(self,exc):self.status.setText(str(exc))

    def set_project(self,project):
        if self._workflow_workers or self.preview_project is not None:
            raise ValueError('계산/미리보기를 취소하거나 적용한 뒤 편집하세요. / Finish or cancel calculation/preview before editing.')
        self.project=self.workflow.replace(project);self.draft_changed()

    def replace_project(self,project):
        self.set_project(project.model_dump(mode='json'));self.invalidate_embedded_review(clear_conditions=True);self.redraw();self.sync_fields()

    def invalidate_embedded_review(self,clear_conditions=False):
        self.embedded_report.setPlainText('PCB·문서 또는 입력 조건이 바뀌었습니다. 조건 검사를 다시 실행하세요.')
        self.bom_text.clear();self.cost_proposal=None;self.cost_preview_button.setEnabled(False)
        if clear_conditions:
            self.net_conditions.blockSignals(True)
            try:self.net_conditions.setRowCount(0)
            finally:self.net_conditions.blockSignals(False)

    def operating_conditions_changed(self,*_):
        self.invalidate_embedded_review()
        if self.workflow_task is not None:self.cancel_workflow()
        self.workflow_report.clear()

    def embedded_product(self):
        from .pcb_embedded_dialog import PCBEmbeddedDialog
        dialog=PCBEmbeddedDialog(self,self.project,self.selected_ref())
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.set_project(dialog.checked)
                self.status.setText('제품·실제 패드 선언을 PCB 초안에 연결했습니다. CAD 저장은 별도입니다.')
        except (ValueError,TypeError) as exc:self.error(exc)
        finally:dialog.deleteLater()

    def align_selected(self):
        if self._workflow_workers or self.preview_project is not None:return
        selected=self.selected_ref()
        if selected in self.locked_refs:self.error('고정한 Source는 정렬 이동할 수 없습니다. / Unlock the source component first.');return
        from .pcb_alignment_dialog import PCBAlignmentDialog
        dialog_base=pcb_digest(self.project);dialog=PCBAlignmentDialog(self,self.project,selected)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted or dialog.checked is None:return
            if pcb_digest(self.project)!=dialog_base:self.error('대화상자 입력 중 PCB가 바뀌었습니다. 다시 선택하세요. / PCB changed while selecting pins.');return
            self.start_workflow('alignment',params=dialog.checked)
        finally:dialog.deleteLater()

    def operating_conditions(self):
        names=('voltage_v','source_current_limit_a','declared_load_current_a','source_url','condition');result={}
        for row in range(self.net_conditions.rowCount()):
            values=[self.net_conditions.item(row,col).text().strip() if self.net_conditions.item(row,col) else '' for col in range(6)]
            condition={key:(float(value) if index<3 else value) for index,(key,value) in enumerate(zip(names,values[1:])) if value}
            if condition:result[values[0]]=condition
        return result

    def cost_estimate(self):
        from ..pcb_cost_workflow import estimate_saved_cost
        try:
            result=estimate_saved_cost(self.project)
            rows=['저장·입력 견적의 부분 합계 · 실시간 가격/완성 견적 아님']
            rows.extend(currency+' '+amount for currency,amount in result['known_subtotals'].items())
            rows.extend(currency+' 조건부 최소 '+value['minimum']+' / 최대 '+value['maximum'] for currency,value in result['conditional_ranges'].items())
            rows.append('가격/구매 소유 미확인: '+(', '.join(result['unpriced_component_refs']) or '없음'))
            rows.append('모듈 내부 모델 제외: '+str(result['excluded_internal_models']))
            rows.append('별도 비용 미입력: '+(', '.join(result['unknown_additional_costs']) or '없음')+' · 통화 자동 환산 없음')
            rows.append('수량/품번 변경으로 사용하지 않은 이전 AI 추정: '+str(len(result['stale_ai_estimates'])))
            rows.extend(', '.join(row['refs'])+' · '+(row.get('mpn') or row.get('value') or '제품 미정')+f" · 필요 {row['required_quantity']} / 구매 {row['purchase_quantity']} · "+str(row.get('rounded_subtotal'))+' '+row['quote']['currency'] for row in result['rows'])
            self.bom_text.setPlainText('\n'.join(rows))
        except (ValueError,TypeError) as exc:self.error(exc)

    def edit_cost_inputs(self):
        from .pcb_cost_dialog import PCBCostInputsDialog
        base=pcb_digest(self.project);dialog=PCBCostInputsDialog(self,self.project)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                if pcb_digest(self.project)!=base:raise ValueError('PCB 초안이 바뀌었습니다. 현재 초안에서 견적 조건을 다시 여세요.')
                self.set_project(dialog.checked);self.cost_estimate()
        except (ValueError,TypeError) as exc:self.error(exc)
        finally:dialog.deleteLater()

    def preview_cost_proposal(self):
        if self.cost_proposal is None:self.error('현재 초안으로 AI 가격안을 먼저 생성하세요.');return
        from .pcb_cost_dialog import PCBCostProposalDialog
        dialog=None;base=pcb_digest(self.project)
        try:
            dialog=PCBCostProposalDialog(self,self.project,self.cost_proposal)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                if pcb_digest(self.project)!=base:raise ValueError('가격안을 보는 동안 PCB 초안이 바뀌었습니다. 오래된 추정은 채택하지 않습니다.')
                self.set_project(dialog.checked);self.cost_estimate()
                self.status.setText('검토한 가격 범위를 AI 추정으로 PCB 초안에 저장했습니다. 실제 부품 견적·CAD 저장은 별도입니다.')
        except (ValueError,TypeError) as exc:self.error(exc)
        finally:
            if dialog is not None:dialog.deleteLater()

    def draft_changed(self):
        self.stop_advice();self.workflow_nonce+=1;self.preview_project=None;self.workflow_result=None
        self.invalidate_embedded_review()
        self.locked_refs.intersection_update(c.ref for c in self.project.components)
        self.dirty=True;self.simulation_result=None;self.sim_text.setPlainText('설계가 변경되었습니다. 시뮬레이션을 다시 실행하세요. / Design changed; rerun simulation.')
        self.advice.clear();self.route=None;self.canvas.route_points=[];self.redraw();self.sync_fields();self.update_workflow_controls()

    def update_workflow_controls(self):
        busy=bool(self._workflow_workers);preview=self.preview_project is not None
        for control in self._workflow_controls:control.setEnabled(not busy and not preview)
        self.tabs.setEnabled(not busy and not preview);self.canvas.setEnabled(not busy and not preview)
        self.workflow_cancel.setEnabled(self.workflow_task is not None)
        self.preview_apply.setEnabled(preview and not busy);self.preview_cancel.setEnabled(preview and not busy)
        trials=(self.workflow_result or {}).get('trials',[])
        if not isinstance(trials,list):trials=[]
        self.trial_choice.setVisible(bool(trials));self.trial_preview.setVisible(bool(trials))
        self.trial_choice.setEnabled(not busy);self.trial_preview.setEnabled(bool(trials) and not busy)
        self.preview_apply.setVisible(preview);self.preview_cancel.setVisible(preview);self.workflow_cancel.setVisible(busy)
        self.workflow_report.setVisible(bool(self.workflow_report.toPlainText()))
        self.undo_button.setEnabled(not busy and not preview and self.workflow.can_undo)
        self.redo_button.setEnabled(not busy and not preview and self.workflow.can_redo)

    def begin_routing(self):
        self.tabs.setCurrentWidget(self.layout_page);self.route_button.setChecked(True);self.canvas.setFocus()
        self.status.setText('시작 패드 → 꺾임점 → 같은 net의 끝 패드. 우클릭/Esc로 취소합니다. / Start pad → corners → same-net end; right-click/Esc cancels.')

    def begin_via(self):
        self.tabs.setCurrentWidget(self.via_page);self.add_via()

    def toggle_locked(self):
        ref=self.selected_ref()
        if ref is None:self.error('먼저 고정할 부품을 선택하세요. / Select a component to lock.');return
        if ref in self.locked_refs:self.locked_refs.remove(ref)
        else:self.locked_refs.add(ref)
        self.status.setText('이 PCB 창의 배치 고정: '+', '.join(sorted(self.locked_refs))+' · 기존 배선 연결 부품도 보호합니다. / Local placement locks; routed components are protected.')
        self.update_stack_status()

    def update_stack_status(self):
        shown=self.preview_project or self.project;layers=copper_layers(shown);active=self.layer.currentText()
        suffix=' · 미리보기 / Preview' if self.preview_project is not None else ''
        self.stack_status.setText(f'현재 {self.project.layer_count}층 · 작업 층 {active} / Active layer · '+
            ' → '.join(layers)+suffix+'\n2·4·6·8층: 앞면 / 내부 구리층 / 뒷면 · 제조 적층·Gerber 출력 승인은 별도입니다. / Copper layers, not fabrication stackup or Gerber approval.'+
            f' · 배치 고정 {len(self.locked_refs)}개 / Local locks')

    def cancel_workflow(self):
        self.workflow_nonce+=1;self.workflow_task=None;self.workflow_result=None
        self.workflow.cancel_preview();self.preview_project=None
        if self.alive:
            self.workflow_report.setPlainText('계산 결과 수신 취소 · 제한 계산이 끝날 때까지 새 계산을 시작하지 않습니다. / Results cancelled; wait for bounded work to finish before restarting.')
            self.redraw();self.update_workflow_controls()
            self.status.setText('계산 결과 수신을 취소했습니다. 진행 중인 제한 계산은 마무리될 수 있습니다. / Results cancelled; bounded work may still finish.')

    def cancel_workflow_preview(self):
        self.workflow.cancel_preview();self.preview_project=None;self.redraw();self.update_workflow_controls()
        self.status.setText('미리보기 취소 · PCB 초안과 CAD 원본 유지 / Preview cancelled; PCB draft and CAD unchanged.')

    def apply_workflow_preview(self):
        try:
            if design_digest(self.current_raw())!=self.base_sha:
                raise ValueError('CAD 문서가 바뀌었습니다. 초안을 보존하고 문서에서 다시 불러오세요. / Stale CAD document; reload before applying.')
            preview=self.workflow.preview
            if preview and preview.get('kind')=='alignment' and set(preview.get('moved_refs',[])) & self.locked_refs:
                raise ValueError('정렬 미리보기의 이동 부품이 고정됐습니다. / Alignment preview contains a locked component.')
            self.project=self.workflow.apply_preview();self.draft_changed()
            self.status.setText('검토한 안을 PCB 초안에 적용했습니다. 되돌릴 수 있습니다. CAD 저장은 별도입니다. / Preview applied to PCB draft; Undo is available. Save to CAD separately.')
        except ValueError as exc:self.error(exc)

    def undo_draft(self):
        if self._workflow_workers or self.preview_project is not None or not self.workflow.can_undo:return
        self.project=self.workflow.undo();self.draft_changed()

    def redo_draft(self):
        if self._workflow_workers or self.preview_project is not None or not self.workflow.can_redo:return
        self.project=self.workflow.redo();self.draft_changed()

    def stage_workflow_preview(self,candidate,label,kind):
        if kind=='alignment':
            old={component.ref:component.model_dump(mode='json') for component in self.project.components}
            moved={component['ref'] for component in candidate['components'] if component!=old.get(component['ref'])}
            if moved & self.locked_refs:raise ValueError('고정 부품을 정렬 이동할 수 없습니다. / Alignment cannot move locked components.')
        preview=self.workflow.stage_candidate(candidate,expected_base_sha256=pcb_digest(self.project),label=label,kind=kind)
        self.preview_project=PCBProject.model_validate(preview['candidate']);self.route=None;self.canvas.route_points=[]
        self.redraw();self.update_workflow_controls()
        self.status.setText(label+' · 미리보기만 표시 · 적용 전 PCB/CAD 불변 / Preview only; no PCB/CAD change before Apply.')

    def preview_trial(self):
        result=self.workflow_result
        if not result or pcb_digest(self.project)!=result.get('base_sha256'):
            self.error('초안이 바뀌어 비교 결과가 오래되었습니다. 다시 검사하세요. / Stale trial; run again.');return
        index=self.trial_choice.currentData();trials=result.get('trials',[])
        if not isinstance(trials,list):return
        if type(index) is not int or not 0<=index<len(trials):return
        trial=trials[index];candidate=trial.get('candidate') or trial.get('qualified_candidate')
        if not candidate:
            self.error('이 시도에는 적용 가능한 배선안이 없습니다. 탐색 실패는 불가능 판정이 아닙니다. / No applicable candidate; search failure is not proof of impossibility.');return
        try:
            self.stage_workflow_preview(candidate,f"{trial['layer_count']}층 배선안 / Routing trial",'routing')
            if not trial.get('candidate'):
                self.status.setText('미리보기: 연결 형상은 확인됐지만 드릴/채움 등 경고가 남습니다. 전체 규칙·제조 통과가 아닙니다. / Preview: geometric connection with warnings; not full DRC/manufacturing approval.')
        except ValueError as exc:self.error(exc)

    @staticmethod
    def placement_summary(result):
        names={'ratsnest_wirelength_mm':'연결 예상 거리 mm / Connection-distance estimate',
            'crossing_estimate':'교차 예상 수 / Estimated crossings','body_clearance_violations':'부품 간격 위반 / Body clearance violations',
            'boundary_violations':'경계 위반 / Boundary violations','unrouted_net_count':'미연결 그룹 / Unrouted nets'}
        before=result.get('before_objective',result.get('before')) or {};after=result.get('after_objective',result.get('after')) or {}
        def shown(value):return f'{value:.3f}' if isinstance(value,float) else str(value) if value is not None else '미확인 / unknown'
        rows=['배치 비교 · 이전 → 제안 / Before → proposal']
        for key,title in names.items():rows.append(title+': '+shown(before.get(key))+' → '+shown(after.get(key)))
        rows.append('이동 / Moved: '+(', '.join(result.get('moved_refs',[])) or '없음 / none'))
        rows.append('고정 / Fixed: '+(', '.join(result.get('fixed_refs',[])) or '없음 / none'))
        if result.get('blocked_reason'):rows.append('기존 배선·고정 조건 또는 검사 작업 한도로 자동 이동 보류 / Held by preserved copper, fixed conditions or inspection budget.')
        rows.append('직선 연결 거리의 배치 지표입니다. 실제 배선 길이·최적해·제조·전기·열 승인이 아닙니다. / Placement proxies, not routed length, optimality or fabrication/electrical/thermal approval.')
        return '\n'.join(rows)

    @staticmethod
    def routing_summary(result):
        states={'routed':'배선·규칙 확인 / Routed', 'partial':'일부 확인·경고 / Partial',
            'blocked':'경로 미확인 / Not routed','budget_exhausted':'작업 한도 / Budget reached'}
        rows=['시험 후보의 성공 여부이며 수학적으로 보장된 최소 층수가 아닙니다. / Tested candidates, not a proven minimum.']
        for trial in result.get('trials',[]):
            report=trial.get('geometric_check') or {};findings=report.get('findings')
            remaining=(str(sum(item.get('code')=='unrouted_net' for item in findings))
                if isinstance(findings,list) and report.get('checked_layers') else '미확인 / unknown')
            rows.append(f"{trial['layer_count']}층 · "+states.get(trial['status'],trial['status'])+f' · 미연결 그룹 {remaining} / Unrouted nets')
            rows.extend('  '+str(blocker.get('message') or blocker.get('code')) for blocker in trial.get('blockers',[])[:6])
        strict=result.get('minimum_successful_tested_layers');qualified=result.get('minimum_geometrically_routed_layers')
        rows.append('완전 규칙 확인 후보 / Full-check candidate: '+(str(strict)+'층' if strict is not None else '미확인 / not found'))
        rows.append('경고 포함 연결 후보 / Geometrically connected candidate with warnings: '+(str(qualified)+'층' if qualified is not None else '미확인 / not found'))
        rows.append('드릴·채움 경고는 완전 규칙 통과와 다릅니다. 탐색 실패/한도는 불가능 판정이 아닙니다. / Drill/fill warnings are not complete rule success; search failure/limits are not impossibility.')
        unsupported=result.get('unsupported_layer_candidates',[])
        if unsupported:rows.append('모델 미지원·미검증 후보 / Unsupported and unverified: '+', '.join(map(str,unsupported)))
        rows.append('시험한 2·4·6·8층 후보만 평가합니다. 제조 적층·Gerber·정격·열 검증은 별도입니다. / Only tested 2/4/6/8-layer candidates; no fabrication, Gerber, rating or thermal qualification.')
        return '\n'.join(rows)

    @staticmethod
    def alignment_summary(result):
        core=result.get('core') or {};pose=result.get('source_assembly_world_pose') or {}
        rows=['대응 핀 정렬 / Pin alignment: '+str(result.get('status'))+' · 수치 코어 / Core: '+str(result.get('core_status'))]
        rows.append('이동 / Source: '+str(result.get('source_ref'))+' → 기준 / Target: '+str(result.get('target_ref')))
        if result.get('target_external'):
            registration=result.get('target_registration') or {}
            if registration.get('status')=='registered':rows.append('사용자 근거로 외부 보드 기준면을 호스트 PCB에 등록 · 대상 부품의 저장 자세까지 합성 / User-declared external board-to-host registration, including the saved target pose.')
            else:rows.append('외부 PCB 로컬 좌표 참조만 사용 · 실제 CAD 월드 조립 위치 아님 / External local reference only, no actual CAD assembly registration.')
            rows.append('외부 보드 몸체·부모 모듈 이동·전체 조립 3D 간섭은 이 PCB 검사에 포함되지 않습니다. / External bodies, parent-board motion and whole-assembly 3D interference are excluded.')
        def shown(value):return f'{value:.6g}' if isinstance(value,(int,float)) else '미확인 / unknown'
        if pose:
            rows.append('참조 좌표계의 제안 XYZ mm / Preview XYZ: '+', '.join(shown(value) for value in pose['translation_xyz_mm']))
            rows.append('제안 회전행렬 / Preview rotation:')
            rows.extend('  ['+', '.join(shown(value) for value in row)+']' for row in pose['rotation'])
        rows.append('핀 최대 / 평균 / RMS 오차 mm: '+' / '.join(shown(core.get(key)) for key in ('max_pin_error_mm','mean_pin_error_mm','rms_pin_error_mm')))
        rows.extend(str(row.get('code',''))+' · '+str(row.get('message','')) for row in [*result.get('issues',[]),*core.get('issues',[])][:12])
        rows.append('PCB 초안 미리보기 가능 / 2D preview available: '+('예 / yes' if result.get('can_apply') is True else '아니오 / no'))
        rows.append('3D 높이·뒤집기·외부 보드 자세는 2D 배치로 바꾸지 않습니다. 성별·접점·삽입/유지력·충돌·정격·제조 승인은 미확인입니다. / Preview only, no physical mating or manufacturing approval.')
        return '\n'.join(rows)

    def start_workflow(self,kind,params=None):
        if self._workflow_workers:
            self.error('앞선 제한 계산이 마무리 중입니다. 잠시 후 다시 실행하세요. / Previous bounded calculation is finishing.');return
        if self.preview_project is not None:
            self.error('먼저 미리보기를 적용하거나 취소하세요. / Apply or cancel the preview first.');return
        if design_digest(self.current_raw())!=self.base_sha:
            self.error('CAD 문서가 바뀌었습니다. 초안을 보존하고 다시 불러오세요. / Stale CAD document; export draft or reload.');return
        alignment=None
        if kind=='alignment':
            if not isinstance(params,dict) or set(params)-{'source_ref','target_ref','mapping','mating','constraints','verification','net_equivalences','target_project','target_registration'}:
                self.error('정렬 입력을 다시 선택하세요. / Invalid alignment inputs.');return
            alignment=deepcopy(params)
            if alignment.get('source_ref') in self.locked_refs:self.error('고정한 Source는 이동할 수 없습니다. / Source component is locked.');return
        self.stop_advice();self.workflow.cancel_preview();self.workflow_result=None;self.workflow_nonce+=1
        nonce=self.workflow_nonce;project=self.project.model_copy(deep=True);base=pcb_digest(project);document_base=self.base_sha
        layer=self.layer.currentText();width=number_value(self.track_width);locked_refs=tuple(sorted(self.locked_refs))
        try:conditions=self.operating_conditions() if kind=='stability' else None
        except ValueError as exc:self.error('동작 조건에는 유한한 숫자를 입력하세요. '+str(exc));return
        def work():
            if kind=='alignment':
                from ..pcb_pin_alignment import align_components
                return align_components(project,**alignment)
            if kind=='placement':
                from ..pcb_placement_aid import optimize_placement
                return optimize_placement(project,locked_refs=locked_refs,max_trials=200)
            if kind=='stability':
                from ..pcb_embedded import review_embedded
                return dict(base_sha256=base,review=review_embedded(project,net_conditions=conditions))
            from ..pcb_routing_aid import assess_routing
            return assess_routing(project,active_layer=layer if kind=='routing' else None,width_mm=width,max_expansions=12000)
        worker=Worker(work);self.workflow_task=worker;self._workflow_workers.append(worker)
        self.workflow_report.setPlainText('PCB 사본에서 제한 계산 중… 원본과 기존 배선을 유지합니다. 취소는 늦게 도착한 결과를 폐기합니다. / Calculating on a copy; cancel discards late results.')
        self.update_workflow_controls()
        def valid():
            return self.alive and self.workflow_task is worker and nonce==self.workflow_nonce and pcb_digest(self.project)==base and design_digest(self.current_raw())==document_base
        def settled():
            if worker in self._workflow_workers:self._workflow_workers.remove(worker)
            if self.alive:self.update_workflow_controls()
        def done(result):
            accepted=valid()
            if self.workflow_task is worker:self.workflow_task=None
            settled()
            if not accepted:
                if self.alive:self.status.setText('취소되거나 초안/문서가 바뀐 계산 결과를 버렸습니다. / Cancelled or stale result discarded.')
                return
            try:
                if result.get('base_sha256')!=base:raise ValueError('계산의 기준 PCB가 다릅니다. / Candidate base mismatch.')
                self.workflow_result=result
                if kind=='placement':
                    self.workflow_report.setPlainText(self.placement_summary(result))
                    if result.get('can_apply',bool(result.get('moved_refs'))) and result.get('candidate'):
                        self.stage_workflow_preview(result['candidate'],'배치 최적화 / Placement optimization','placement')
                    else:self.status.setText('적용할 배치 개선안을 찾지 못했습니다. PCB 초안 유지 / No applicable improvement; draft preserved.')
                elif kind=='alignment':
                    summary=self.alignment_summary(result);self.workflow_report.setPlainText(summary);self.sim_text.setPlainText(summary);self.tabs.setCurrentIndex(1)
                    if result.get('can_apply') is True and result.get('candidate'):
                        self.stage_workflow_preview(result['candidate'],'대응 핀 정렬 / Pin alignment','alignment')
                    else:self.status.setText('정렬 수치·미확인 조건을 표시했습니다. 2D PCB 적용은 보류합니다. / Alignment preview only; no 2D candidate applied.')
                elif kind=='stability':
                    review=result['review'];rows=[f"위반 {review['violations']} · 미확인 {review['unknowns']} · 입력값 비교 {review['declared_checks']}"]
                    for check in review['checks']:
                        rows.append(check['status']+' · '+', '.join(check['refs'])+' · '+check['message']+'\n  '+check['action'])
                    rows.append('입력값·저장 형상 검사입니다. 열/절연/실물 결합·안전 승인은 미확인입니다.')
                    self.embedded_report.setPlainText('\n'.join(rows));self.workflow_report.setPlainText(rows[0]+' · 제품·전원 조건 검사 탭에 상세 결과')
                    self.status.setText('조건 검사 완료 · 미입력은 미확인으로 유지 · PCB/CAD 변경 없음')
                else:
                    self.trial_choice.clear()
                    for index,trial in enumerate(result.get('trials',[])):
                        self.trial_choice.addItem(f"{trial['layer_count']}층 · {trial['status']}",index)
                    self.workflow_report.setPlainText(self.routing_summary(result))
                    self.status.setText('배선 비교 완료 · 선택안 미리보기 후 명시 적용 · 탐색 한도/실패는 불가능 판정 아님 / Choose a trial to preview; a search limit/failure is not impossibility.')
                self.update_workflow_controls()
            except (ValueError,TypeError,KeyError) as exc:self.error(exc)
        def failed(message):
            accepted=valid()
            if self.workflow_task is worker:self.workflow_task=None
            settled()
            if accepted:self.error('계산 결과를 만들지 못했습니다. 초안 유지 / Draft preserved: '+str(message))
        worker.signals.done.connect(done,Qt.ConnectionType.QueuedConnection);worker.signals.failed.connect(failed,Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def redraw(self):
        conditions={}
        if hasattr(self,'net_conditions'):
            self.net_conditions.blockSignals(True)
            for row in range(self.net_conditions.rowCount()):
                net=self.net_conditions.item(row,0)
                if net:conditions[net.text()]=[self.net_conditions.item(row,col).text() if self.net_conditions.item(row,col) else '' for col in range(1,6)]
            self.net_conditions.setRowCount(len(self.project.nets))
            for row,net in enumerate(self.project.nets):
                for col,text in enumerate([net,*conditions.get(net,['']*5)]):
                    item=QTableWidgetItem(text)
                    if col==0:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.net_conditions.setItem(row,col,item)
            self.net_conditions.blockSignals(False)
        selected_ref=self.selected_ref();selected_via=self.selected_via_id();selected_track=self.tracks.currentData()
        self.canvas.project=self.preview_project or self.project;self.sync_layers();self.components.blockSignals(True);self.components.clearSelection();self.components.setCurrentCell(-1,-1);self.components.setRowCount(len(self.project.components))
        for r,c in enumerate(self.project.components):
            for col,text in enumerate([c.ref,c.value or c.model.kind,', '.join(f'{p.number}:{p.net or "NC"}' for p in c.pins)]):self.components.setItem(r,col,QTableWidgetItem(text))
            self.components.item(r,2).setToolTip('\n'.join(pin.number+': '+net_description(self.project,pin.net) for pin in c.pins))
        self.canvas.selected=selected_ref if any(c.ref==selected_ref for c in self.project.components) else None
        if self.canvas.selected:self.select_component(self.canvas.selected)
        self.components.blockSignals(False)
        self.tracks.clear()
        for t in self.project.tracks:
            self.tracks.addItem(t.id+' · '+t.net+' · '+t.layer,t.id);self.tracks.setItemData(self.tracks.count()-1,net_description(self.project,t.net),Qt.ItemDataRole.ToolTipRole)
        if self.tracks.findData(selected_track)>=0:self.tracks.setCurrentIndex(self.tracks.findData(selected_track))
        self.vias.blockSignals(True);self.vias.clearSelection();self.vias.setCurrentCell(-1,-1);self.vias.setRowCount(len(self.project.vias))
        for r,via in enumerate(self.project.vias):
            for col,text in enumerate([via.id,via.net,f'{via.x_mm:g} / {via.y_mm:g}',f'{via.diameter_mm:g} / {via.drill_mm:g}',', '.join(via.layers),', '.join(via_layers(self.project,via))]):self.vias.setItem(r,col,QTableWidgetItem(text))
            self.vias.item(r,1).setToolTip(net_description(self.project,via.net))
        self.canvas.selected_via=selected_via if any(v.id==selected_via for v in self.project.vias) else None
        if self.canvas.selected_via:self.select_via(self.canvas.selected_via)
        self.vias.blockSignals(False);self.zones.setRowCount(len(self.project.zones))
        for r,zone in enumerate(self.project.zones):
            for col,text in enumerate([zone.id,zone.net,zone.layer,f'채움 / filled: {len(zone.filled_polygons)}' if zone.filled_polygons else 'outline / 미채움']):self.zones.setItem(r,col,QTableWidgetItem(text))
            self.zones.item(r,1).setToolTip(net_description(self.project,zone.net))
        self.nets.setToolTip('\n'.join(net_description(self.project,net) for net in self.project.nets))
        self.canvas.drag=None;self.canvas.update()
        self.cost_estimate();self.status.setText(('PCB 초안 수정됨 · CAD에 PCB 저장으로 적용 / Unsaved PCB draft' if self.dirty else 'PCB 문서 준비 · Local draft')+' · R/C/전압원 DC·AC만 지원 · 제조/정격/열/실물 검증 미수행')
        self.update_stack_status();self.update_route_hint()

    def sync_fields(self):
        self.board_name.setText(self.project.name);set_number(self.width,self.project.width_mm);set_number(self.height,self.project.height_mm);self.nets.setText(', '.join(self.project.nets));set_number(self.clearance,self.project.clearance_mm);set_number(self.edge,self.project.edge_clearance_mm);self.analysis.setCurrentText(self.project.simulation.analysis);set_number(self.frequency,self.project.simulation.frequency_hz);self.quantity.setValue(self.project.budget.board_quantity);self.currency.setText(self.project.budget.currency);self.limit.setText(str(self.project.budget.limit) if self.project.budget.limit is not None else '');self.sync_layers()

    def sync_layers(self):
        shown=self.preview_project or self.project;layers=copper_layers(shown);active=self.layer.currentText()
        self.layer.blockSignals(True);self.layer.clear();self.layer.addItems(layers);self.layer.setCurrentText(active if active in layers else layers[0]);self.layer.blockSignals(False)
        self.layer_count.setCurrentIndex(self.layer_count.findData(shown.layer_count));self.canvas.layer=self.layer.currentText()
        for layer,box in self.layer_visibility.items():box.setVisible(layer in layers)
        self.canvas.visible_layers={layer for layer in layers if self.layer_visibility[layer].isChecked()}

    def visibility_changed(self):
        self.canvas.visible_layers={layer for layer in copper_layers(self.preview_project or self.project) if self.layer_visibility[layer].isChecked()}
        if self.canvas.layer not in self.canvas.visible_layers:self.set_routing(self.route_button.isChecked())
        self.canvas.update()

    def selected_ref(self):
        row=self.components.currentRow()
        return self.components.item(row,0).text() if self.components.selectedItems() and row>=0 and self.components.item(row,0) else None

    def component_selection_changed(self):
        self.canvas.selected=self.selected_ref()
        if self.canvas.selected:self.canvas.selected_via=None;self.vias.clearSelection();self.vias.setCurrentCell(-1,-1)
        self.canvas.update()

    def select_component(self,ref):
        self.canvas.selected=ref;self.canvas.selected_via=None;self.vias.clearSelection();self.vias.setCurrentCell(-1,-1)
        for r,c in enumerate(self.project.components):
            if c.ref==ref:self.components.selectRow(r);break
        self.canvas.update()

    def selected_via_id(self):
        row=self.vias.currentRow()
        return self.vias.item(row,0).text() if self.vias.selectedItems() and row>=0 and self.vias.item(row,0) else None

    def select_via(self,identifier):
        for row,via in enumerate(self.project.vias):
            if via.id==identifier:self.vias.selectRow(row);break
        self.canvas.selected_via=identifier;self.canvas.selected=None;self.components.clearSelection();self.components.setCurrentCell(-1,-1);self.canvas.update()

    def via_selection_changed(self):
        self.canvas.selected_via=self.selected_via_id()
        if self.canvas.selected_via:self.canvas.selected=None;self.components.clearSelection();self.components.setCurrentCell(-1,-1)
        self.canvas.update()

    def add_via(self):
        used={via.id for via in self.project.vias};index=1
        while 'VIA'+str(index) in used:index+=1
        point=self.route['points'][-1] if self.route else (self.project.width_mm/2,self.project.height_mm/2)
        net=self.route['net'] if self.route else self.project.nets[0]
        self._edit_via(PCBVia(id='VIA'+str(index),net=net,x_mm=point[0],y_mm=point[1],diameter_mm=.8,drill_mm=.4,layers=[copper_layers(self.project)[0],copper_layers(self.project)[-1]]),True)

    def edit_via(self):
        identifier=self.selected_via_id();via=next((item for item in self.project.vias if item.id==identifier),None)
        if via:self._edit_via(via,False)

    def _edit_via(self,via,adding):
        sha=pcb_digest(self.project);dialog=PCBViaEditor(self,via,self.project.nets,copper_layers(self.project))
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            if pcb_digest(self.project)!=sha:raise ValueError('PCB 초안이 변경되었습니다. 다시 선택하세요. / Stale PCB draft; select again.')
            raw=self.project.model_dump(mode='json');row=dialog.checked.model_dump(mode='json')
            if adding:raw.setdefault('vias',[]).append(row)
            else:raw['vias']=[row if item['id']==via.id else item for item in raw['vias']]
            self.set_project(raw);self.select_via(dialog.checked.id)
        except (ValueError,TypeError) as exc:self.error(exc)
        finally:dialog.deleteLater()

    def delete_via(self):
        identifier=self.selected_via_id()
        if identifier is None:return
        raw=self.project.model_dump(mode='json');raw['vias']=[via for via in raw['vias'] if via['id']!=identifier]
        try:self.set_project(raw)
        except ValueError as exc:self.error(exc)

    def edit_board(self):
        raw=self.project.model_dump(mode='json');raw.update(name=self.board_name.text(),width_mm=number_value(self.width),height_mm=number_value(self.height),layer_count=self.layer_count.currentData(),nets=[n.strip() for n in self.nets.text().split(',')],clearance_mm=number_value(self.clearance),edge_clearance_mm=number_value(self.edge))
        try:self.set_project(raw)
        except ValueError as exc:self.layer_count.setCurrentIndex(self.layer_count.findData(self.project.layer_count));self.error(exc)

    def add_component(self):
        kind=self.add_kind.currentText();prefix={'resistor':'R','capacitor':'C','voltage_source':'V','none':'J','unsupported':'U'}[kind];used={c.ref for c in self.project.components};i=1
        while prefix+str(i) in used:i+=1
        self.edit_component(new_component(kind,prefix+str(i)),adding=True)

    def edit_component(self,component=None,adding=False):
        ref=self.selected_ref()
        if component is None:component=next((c for c in self.project.components if c.ref==ref),None)
        if component is None:return
        sha=pcb_digest(self.project);dialog=PCBComponentEditor(self,component,self.project.nets)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            if pcb_digest(self.project)!=sha:raise ValueError('PCB 초안이 변경되었습니다. 다시 선택하세요. / Stale PCB draft; select again.')
            raw=self.project.model_dump(mode='json');row=dialog.checked.model_dump(mode='json')
            if adding:raw['components'].append(row)
            else:raw['components']=[row if c['ref']==component.ref else c for c in raw['components']]
            self.set_project(raw)
        except (ValueError,TypeError) as exc:self.error(exc)
        finally:dialog.deleteLater()

    def delete_component(self):
        ref=self.selected_ref()
        if not ref:return
        raw=self.project.model_dump(mode='json');raw['components']=[c for c in raw['components'] if c['ref']!=ref];self.set_project(raw)

    def move_component(self,ref,x,y):
        raw=self.project.model_dump(mode='json')
        for c in raw['components']:
            if c['ref']==ref:c.update(x_mm=x,y_mm=y)
        try:self.set_project(raw);self.select_component(ref)
        except ValueError as exc:self.error(exc)

    def update_route_hint(self):
        route=self.route or {};start=route.get('start')
        self.route_hint.setText('작업 층 / Layer: '+self.layer.currentText()+' · 연결 그룹 / Net: '+str(route.get('net') or '선택 전 / none')+
            ' · 시작 / Start: '+('/'.join(start) if start else '패드 선택 / choose pad')+
            '\n시작 패드 → 꺾임점 → 같은 net 끝 패드/비아 · 우클릭/Esc 취소 · 미연결은 배선 검사에서 확인 / Start → corners → same-net end; right-click/Esc cancels; check routing for remaining connections.')

    def set_routing(self,enabled):
        self.canvas.routing=enabled;self.route=None;self.canvas.route_points=[];self.canvas.update();self.update_route_hint()
    def layer_changed(self,layer):
        self.canvas.layer=layer
        if layer in self.layer_visibility:self.layer_visibility[layer].setChecked(True)
        self.set_routing(self.route_button.isChecked())
        self.update_stack_status()

    def route_click(self,packet):
        if packet.get('cancel'):self.route=None;self.canvas.route_points=[];self.canvas.update();self.update_route_hint();return
        if self._workflow_workers or self.preview_project is not None:return
        layer=self.layer.currentText()
        if layer not in self.canvas.visible_layers:self.error('현재 배선 층을 표시하세요. / Show the active routing layer.');return
        pad=packet.get('pad');via=packet.get('via');terminal=None
        if pad:
            current=next((item for item in pad_positions(self.project) if (item['ref'],item['pin'])==(pad['ref'],pad['pin'])),None)
            if current is None or current!=pad or layer not in current['layers']:self.error('패드 또는 층이 변경되었습니다. 다시 선택하세요. / Stale pad or layer; select again.');return
            terminal=dict(net=current['net'],key=('pad',current['ref'],current['pin']),point=(current['x'],current['y']))
        elif via:
            current=next((item for item in self.project.vias if item.id==via.id),None)
            if current is None or current!=via or layer not in via_layers(self.project,current):self.error('비아 또는 층이 변경되었습니다. 다시 선택하세요. / Stale via or layer; select again.');return
            terminal=dict(net=current.net,key=('via',current.id),point=(current.x_mm,current.y_mm))
        point=terminal['point'] if terminal else tuple(round(v,3) for v in packet['point'])
        if self.route is None:
            if not terminal or terminal['net'] is None:self.error('net이 지정된 시작 패드/비아를 선택하세요. / Select a connected start pad or via.');return
            self.route=dict(net=terminal['net'],start=terminal['key'],points=[point],layer=layer)
        elif terminal:
            if terminal['net']!=self.route['net']:self.error('같은 net의 끝 패드/비아를 선택하세요. / End pad or via must share the net.');return
            if terminal['key']==self.route['start']:self.error('다른 끝 패드/비아를 선택하세요. / Select a different end pad or via.');return
            points=self.route['points']+[point];raw=self.project.model_dump(mode='json');raw['tracks'].append(dict(id='T'+uuid4().hex[:12],net=self.route['net'],layer=self.route['layer'],width_mm=number_value(self.track_width),points=[dict(x_mm=x,y_mm=y) for x,y in points]))
            try:self.set_project(raw)
            except ValueError as exc:self.error(exc)
            return
        elif point!=self.route['points'][-1]:self.route['points'].append(point)
        self.canvas.route_points=self.route['points'];self.canvas.update();self.update_route_hint()

    def delete_track(self):
        raw=self.project.model_dump(mode='json');raw['tracks']=[t for t in raw['tracks'] if t['id']!=self.tracks.currentData()];self.set_project(raw)

    def check_layout(self):
        result=inspect_layout(self.project);self.sim_text.setPlainText(json.dumps(result,ensure_ascii=False,indent=2));self.tabs.setCurrentIndex(1);self.status.setText('배치 검사: '+result['status']+' · 제조/정격 승인 아님')

    def simulate(self):
        raw=self.project.model_dump(mode='json');raw['simulation']=dict(analysis=self.analysis.currentText(),frequency_hz=number_value(self.frequency))
        try:
            project=PCBProject.model_validate(raw)
            if pcb_digest(project)!=pcb_digest(self.project):self.set_project(project)
            self.simulation_result=simulate_pcb(self.project);self.sim_text.setPlainText(json.dumps(self.simulation_result,ensure_ascii=False,indent=2));self.status.setText('계산 완료 · 논리 netlist만 해석 · 구리 배선/실물 상태는 별도 확인')
        except ValueError as exc:self.simulation_result=None;self.sim_text.setPlainText('시뮬레이션 차단 / Blocked\n'+str(exc));self.error(exc)

    def update_budget(self):
        raw=self.project.model_dump(mode='json');raw['budget'].update(board_quantity=self.quantity.value(),currency=self.currency.text().strip(),limit=self.limit.text().strip() or None)
        try:self.set_project(raw);self.cost_estimate()
        except ValueError as exc:self.error(exc)

    def current_raw(self):
        from ..models import Design
        return deepcopy(self.host.document.design or Design().model_dump())

    def request_apply(self,electrical=False):
        if self._workflow_workers or self.preview_project is not None:
            self.error('먼저 계산/미리보기를 마치세요. CAD에는 검토한 PCB 초안만 저장합니다. / Finish calculation/preview before saving the PCB draft to CAD.');return
        try:
            raw=self.current_raw();checked=with_pcb(raw,self.project,expected_digest=self.base_sha)
            if electrical:
                # All layout errors must be resolved before claiming a routed
                # board was explicitly transferred into the electrical graph.
                report=inspect_layout(self.project)
                if any(finding.get('severity','error')=='error' for finding in report['findings']):raise ValueError('전장 적용 전에 배치/구리 연결 오류를 해결하세요. / Resolve layout errors before electrical apply.')
                data=checked.model_dump(mode='json');data['electrical']=electrical_preview(self.project,data.get('electrical'))
                from ..models import Design
                checked=Design.model_validate(data)
            self.applyRequested.emit(dict(design=checked.model_dump(mode='json'),base_sha256=self.base_sha,pcb_sha256=pcb_digest(self.project),electrical=electrical))
            if electrical:
                self.sim_text.setPlainText(json.dumps(report,ensure_ascii=False,indent=2));self.tabs.setCurrentIndex(1)
                self.status.setText('PCB + 전장 명시 적용 요청 · 논리 netlist 전달 · 구리 검사: '+report['status']+' · 저장된 채움/드릴 검사는 제한적 · 제조 승인 아님')
        except (ValueError,TypeError) as exc:self.error(exc)

    def document_changed(self,raw):
        # Metadata commits by another editor never silently discard this draft.
        incoming=design_digest(raw)
        if incoming==self.base_sha:return
        self.invalidate_embedded_review(clear_conditions=True)
        self.cancel_workflow()
        if raw.get('pcb') and pcb_digest(raw['pcb'])==pcb_digest(self.project):
            self.base=deepcopy(raw);self.base_sha=incoming;self.workflow.reset(self.project);self.dirty=False;self.simulation_result=None;self.stop_advice();self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();self.update_workflow_controls();return
        if self.dirty:self.stop_advice();self.error('CAD 문서가 변경되었습니다. 초안 내보내기 후 다시 불러오세요. / Stale document; export draft or reload.');return
        self.base=deepcopy(raw);self.base_sha=incoming;self.project=PCBProject.model_validate(raw.get('pcb') or {});self.workflow.reset(self.project);self.locked_refs.intersection_update(c.ref for c in self.project.components);self.simulation_result=None;self.stop_advice();self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();self.sync_fields();self.update_workflow_controls()

    def reload(self):
        self.invalidate_embedded_review(clear_conditions=True)
        self.cancel_workflow();self.stop_advice();self.base=self.current_raw();self.base_sha=design_digest(self.base);self.project=PCBProject.model_validate(self.base.get('pcb') or {});self.workflow.reset(self.project);self.locked_refs.intersection_update(c.ref for c in self.project.components);self.dirty=False;self.simulation_result=None;self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();self.sync_fields();self.update_workflow_controls()

    def load_file(self):
        path,_=QFileDialog.getOpenFileName(self,'PCB 열기','','PCB (*.pcbp *.json)')
        if not path:return
        try:
            target=Path(path)
            if target.stat().st_size>2*1024*1024:raise ValueError('PCB 파일은 2 MiB 이하여야 합니다. / File too large.')
            self.replace_project(PCBProject.model_validate_json(target.read_bytes()))
        except (ValueError,OSError) as exc:self.error(exc)

    def export_file(self,kind):
        if self.preview_project is not None:self.error('내보내려면 미리보기를 PCB 초안에 적용하거나 취소하세요. / Apply or cancel the preview before exporting the draft.');return
        suffix,filters={'pcb':('pcbp','PCB (*.pcbp)'), 'bom':('csv','CSV (*.csv)'), 'spice':('cir','SPICE (*.cir)')}[kind]
        path,_=QFileDialog.getSaveFileName(self,'PCB 내보내기','board.'+suffix,filters)
        if not path:return
        try:
            text=self.project.model_dump_json(indent=2) if kind=='pcb' else bom_csv(self.project) if kind=='bom' else spice_netlist(self.project)
            Path(path).write_text(text,encoding='utf-8-sig' if kind=='bom' else 'utf-8');self.status.setText('내보내기 완료 · '+path)
        except (ValueError,OSError) as exc:self.error(exc)

    def ai_identity(self):
        parent=self.host;config=getattr(parent,'codex_config',{});return config.get('model',''),parent.cloud_effort.currentData() if hasattr(parent,'cloud_effort') else 'medium'

    def stop_advice(self):
        task=self.advice_task;self.advice_task=None
        if task:task.cancel()
        if hasattr(self,'cancel_button'):self.cancel_button.setEnabled(False)

    def review(self,mode='pcb'):
        if self.advice_task:return
        parent=self.host
        if getattr(parent,'ai_task',None):self.advice.setPlainText('CAD AI 요청이 끝난 뒤 실행하세요. / Another CAD AI request is active.');return
        model,effort=self.ai_identity();config=deepcopy(getattr(parent,'codex_config',{}))
        if not model:self.advice.setPlainText('CAD AI 패널의 Codex 계정·모델을 먼저 연결하세요.');return
        try:
            from .pcb_ai import advice_request,cost_advice_request,cost_proposal_request
            question=self.cost_question.text() if mode in ('cost','cost_proposal') else self.question.toPlainText()
            builder=cost_proposal_request if mode=='cost_proposal' else cost_advice_request if mode=='cost' else advice_request
            builder(self.project,question)
        except ValueError as exc:self.error(exc);return
        from .ai_task import AITask
        from .pcb_ai import review_pcb,review_cost,propose_cost
        project=self.project.model_copy(deep=True);sha=pcb_digest(project);base_sha=self.base_sha
        transport=propose_cost if mode=='cost_proposal' else review_cost if mode=='cost' else review_pcb
        task=AITask(lambda control,progress:transport(project,question,model,executable=config.get('executable',''),effort=effort,control=control,progress=progress,deadline=180),parent)
        self.advice_task=task;self.cancel_button.setEnabled(True);self.advice.setPlainText('Codex PCB 자문 중 · PCB와 BOM 입력을 전송 · ChatGPT 구독 사용량 적용')
        if mode in ('cost','cost_proposal'):self.advice.setPlainText('Codex 견적 검토 중 · BOM·저장 견적·제품 출처만 전송 · 실시간 가격 확인 아님')
        if mode=='cost_proposal':self.cost_proposal=None;self.cost_preview_button.setEnabled(False)
        self.tabs.setCurrentIndex(1)
        def valid(sender):return self.alive and sender is self.advice_task and (self.cost_question.text() if mode in ('cost','cost_proposal') else self.question.toPlainText())==question and pcb_digest(self.project)==sha and self.ai_identity()==(model,effort) and design_digest(self.current_raw())==base_sha
        def complete(packet):
            sender,result=packet
            if not valid(sender):
                if sender is self.advice_task:self.stop_advice();self.advice.setPlainText('질문·설계·문서·모델 설정이 변경되어 오래된 자문을 폐기했습니다. / Stale advice discarded.')
                return
            self.advice_task=None;self.cancel_button.setEnabled(False)
            if mode=='cost_proposal':
                self.cost_proposal=deepcopy(result['proposal']);has_rows=bool(self.cost_proposal['rows']);self.cost_preview_button.setEnabled(has_rows)
                heading='AI 가격 추정 제안을 받았습니다. 미리보기에서 수량·범위·근거를 확인한 뒤 명시적으로 채택하세요.' if has_rows else '추정 근거가 부족해 가격을 미정으로 유지합니다. 필요한 견적 자료를 확인하세요.'
                self.bom_text.setPlainText(heading+'\n'+self.cost_proposal['summary'])
                self.advice.setPlainText(heading+'\n실제 견적·설계는 자동 변경하지 않았습니다.');self.tabs.setCurrentWidget(self.bom_page)
            else:self.advice.setPlainText('Codex 자문 · '+model+' / '+effort+'\n'+result['answer']+'\n\n제안은 자동 적용되지 않습니다. 직접 편집하고 검토 후 저장하세요.')
        def failed(packet):
            sender,message=packet
            if not valid(sender):
                if sender is self.advice_task:self.stop_advice();self.advice.setPlainText('질문·설계·문서·모델 설정이 변경되어 오래된 자문을 폐기했습니다. / Stale advice discarded.')
                return
            self.advice_task=None;self.cancel_button.setEnabled(False);self.advice.setPlainText('AI 자문 실패 · PCB 초안 보존\n'+str(message))
        task.completed.connect(complete,Qt.ConnectionType.QueuedConnection);task.failed.connect(failed,Qt.ConnectionType.QueuedConnection);task.start()

    def closeEvent(self,event):self.alive=False;self.cancel_workflow();self.stop_advice();super().closeEvent(event)
