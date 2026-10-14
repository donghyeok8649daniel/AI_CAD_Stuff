"""PCB workspace with local drafts and explicit CAD/electrical commits."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,
    QTabWidget,QSplitter,QDialog,QDialogButtonBox,QCheckBox,QFileDialog,QHeaderView,QAbstractItemView)
from ..pcb import (PCBProject,PCBComponent,PCBTrack,PCBPoint,new_component,divider_example,pad_positions,
    pcb_digest,inspect_layout,bom_report,bom_csv)
from ..pcb_simulation import simulate_pcb,spice_netlist
from ..pcb_plugin import design_digest,with_pcb,electrical_preview


def number(value,lo,hi,decimals=3):
    w=QDoubleSpinBox();w.setRange(lo,hi);w.setDecimals(decimals);w.setValue(value);return w


def push(text,fn,name=''):
    w=QPushButton(text);w.clicked.connect(fn)
    if name:w.setObjectName(name)
    return w


class PCBComponentEditor(QDialog):
    def __init__(self,parent,component,nets):
        super().__init__(parent);self.setWindowTitle('PCB 부품 · 핀 / 모델 / 가격 · Component');self.resize(850,720);self.checked=None;self.original=component
        root=QVBoxLayout(self);tabs=QTabWidget();root.addWidget(tabs)
        basic=QWidget();form=QFormLayout(basic);tabs.addTab(basic,'부품 / 모델')
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
        pins_layout.addWidget(QLabel('등록 net: '+', '.join(nets)+' · 좌표는 부품 중심 기준 mm · 원형 패드만 지원'))
        self.pins=QTableWidget(0,7);self.pins.setHorizontalHeaderLabels(['번호','이름','net (빈칸=NC)','X mm','Y mm','직경 mm','층']);self.pins.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);pins_layout.addWidget(self.pins)
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
        pin=pin or dict(number='P'+str(self.pins.rowCount()+1),name='',net=None,x_mm=0,y_mm=0,diameter_mm=1,layers=['F.Cu'])
        r=self.pins.rowCount();self.pins.insertRow(r)
        for col,key in enumerate(['number','name','net','x_mm','y_mm','diameter_mm','layers']):
            value=pin.get(key);self.pins.setItem(r,col,QTableWidgetItem(','.join(value) if isinstance(value,list) else str(value) if value is not None else ''))

    def candidate(self):
        def text(r,c):return self.pins.item(r,c).text().strip() if self.pins.item(r,c) else ''
        pins=[dict(number=text(r,0),name=text(r,1),net=text(r,2) or None,x_mm=float(text(r,3)),y_mm=float(text(r,4)),diameter_mm=float(text(r,5)),layers=[s.strip() for s in text(r,6).split(',')]) for r in range(self.pins.rowCount())]
        kind=self.kind.currentText();model=dict(kind=kind)
        if kind in ('resistor','capacitor','voltage_source'):
            model.update(pin_a=self.pa.text().strip(),pin_b=self.pb.text().strip())
            model[{'resistor':'resistance_ohm','capacitor':'capacitance_f','voltage_source':'dc_voltage_v'}[kind]]=float(self.model_value.text())
        if kind=='voltage_source':model.update(ac_voltage_v=float(self.ac.text()) if self.ac.text().strip() else None,ac_phase_deg=self.phase.value())
        status=self.price_status.currentText()
        quote=dict(status=status,unit_price=self.amount.text().strip() or None,currency=self.currency.text().strip(),as_of=self.as_of.text().strip() or None,supplier=self.supplier.text().strip(),source_url=self.price_source.text().strip(),minimum_quantity=self.moq.value(),pack_quantity=self.pack.value(),note=self.note.text())
        return PCBComponent(ref=self.ref.text().strip(),value=self.value.text(),mpn=self.mpn.text(),footprint=self.footprint.text(),footprint_basis=self.basis.currentText(),source_url=self.source.text().strip(),x_mm=self.x.value(),y_mm=self.y.value(),rotation_deg=self.angle.value(),body_width_mm=self.bw.value(),body_height_mm=self.bh.value(),pins=pins,model=model,quote=quote,fitted=self.fitted.isChecked())

    def accept(self):
        try:self.checked=self.candidate()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc));return
        super().accept()


class PCBBoardCanvas(QWidget):
    placementChanged=Signal(str,float,float)
    routeClicked=Signal(object)
    componentSelected=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(320,250);self.project=PCBProject();self.selected=None;self.routing=False;self.layer='F.Cu';self.route_points=[];self.drag=None
        self.setMouseTracking(True);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setObjectName('pcbBoardCanvas')

    def layout_transform(self):
        p=self.project;s=min((self.width()-40)/p.width_mm,(self.height()-40)/p.height_mm)
        return s,(self.width()-p.width_mm*s)/2,(self.height()-p.height_mm*s)/2

    def mm(self,pos):
        s,x,y=self.layout_transform();return ((pos.x()-x)/s,(pos.y()-y)/s)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.fillRect(self.rect(),QColor('#10191c'));s,x,y=self.layout_transform();p=self.project
        painter.translate(x,y);painter.scale(s,s);painter.fillRect(QRectF(0,0,p.width_mm,p.height_mm),QColor('#18352d'));painter.setPen(QPen(QColor('#63907e'),1/s));painter.drawRect(QRectF(0,0,p.width_mm,p.height_mm))
        painter.setPen(QPen(QColor('#284b40'),.6/s))
        for i in range(0,int(p.width_mm)+1,5):painter.drawLine(QPointF(i,0),QPointF(i,p.height_mm))
        for i in range(0,int(p.height_mm)+1,5):painter.drawLine(QPointF(0,i),QPointF(p.width_mm,i))
        for track in p.tracks:
            color=QColor('#f88d55' if track.layer=='F.Cu' else '#659de5');color.setAlpha(255 if track.layer==self.layer else 110);painter.setPen(QPen(color,track.width_mm,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            path=QPainterPath();path.moveTo(track.points[0].x_mm,track.points[0].y_mm)
            for pt in track.points[1:]:path.lineTo(pt.x_mm,pt.y_mm)
            painter.drawPath(path)
        for c in p.components:
            painter.save();painter.translate(c.x_mm,c.y_mm);painter.rotate(c.rotation_deg);painter.setPen(QPen(QColor('#ffffff' if c.ref==self.selected else '#a7c7b8'),1.5/s));painter.drawRect(QRectF(-c.body_width_mm/2,-c.body_height_mm/2,c.body_width_mm,c.body_height_mm));painter.restore()
        for pad in pad_positions(p):
            painter.setPen(QPen(QColor('#e5d888'),1/s));painter.setBrush(QColor('#b3a255' if pad['net'] else '#526765'));r=pad['radius'];painter.drawEllipse(QPointF(pad['x'],pad['y']),r,r)
        painter.resetTransform();painter.setPen(QColor('#d4e6df'))
        for c in p.components:painter.drawText(QPointF(x+c.x_mm*s,y+c.y_mm*s-8),c.ref)
        if self.route_points:
            painter.setPen(QPen(QColor('#f8e682'),2,Qt.PenStyle.DashLine));path=QPainterPath();path.moveTo(x+self.route_points[0][0]*s,y+self.route_points[0][1]*s)
            for pt in self.route_points[1:]:path.lineTo(x+pt[0]*s,y+pt[1]*s)
            painter.drawPath(path)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:self.routeClicked.emit(dict(cancel=True));return
        if event.button()!=Qt.MouseButton.LeftButton:return
        point=self.mm(event.position())
        if self.routing:
            pads=[pad for pad in pad_positions(self.project) if self.layer in pad['layers'] and ((point[0]-pad['x'])**2+(point[1]-pad['y'])**2)**.5 <= max(pad['radius'],.8)]
            self.routeClicked.emit(dict(point=point,pad=pads[0] if pads else None));return
        hits=[c for c in self.project.components if ((point[0]-c.x_mm)**2+(point[1]-c.y_mm)**2)**.5 <= max(3,c.body_width_mm/2,c.body_height_mm/2)]
        if hits:
            c=min(hits,key=lambda c:(point[0]-c.x_mm)**2+(point[1]-c.y_mm)**2);self.selected=c.ref;self.drag=(c.ref,c.x_mm-point[0],c.y_mm-point[1]);self.componentSelected.emit(c.ref);self.update()

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
        root=QVBoxLayout(self);top=QHBoxLayout();root.addLayout(top)
        top.addWidget(QLabel('PCB  /  설계 · 배선 · 시뮬레이션'))
        top.addWidget(push('CAD에 PCB 저장',lambda:self.request_apply(False),'pcbApply'));top.addWidget(push('PCB + 전장에 명시 적용',lambda:self.request_apply(True),'pcbElectricalApply'));top.addWidget(push('문서에서 다시 불러오기',self.reload,'pcbReload'))
        tools=QHBoxLayout();root.addLayout(tools)
        tools.addWidget(push('빈 보드',lambda:self.replace_project(PCBProject())));tools.addWidget(push('분압 예제',lambda:self.replace_project(divider_example()),'pcbExample'));tools.addWidget(push('PCB 열기',self.load_file));tools.addWidget(push('PCB 내보내기',lambda:self.export_file('pcb')));tools.addWidget(push('BOM CSV',lambda:self.export_file('bom')));tools.addWidget(push('SPICE netlist',lambda:self.export_file('spice')))
        splitter=QSplitter();root.addWidget(splitter,1);left=QWidget();ll=QVBoxLayout(left);splitter.addWidget(left);self.canvas=PCBBoardCanvas();splitter.addWidget(self.canvas);splitter.setStretchFactor(1,2)
        self.tabs=QTabWidget();ll.addWidget(self.tabs)
        layout_page=QWidget();lp=QVBoxLayout(layout_page);self.tabs.addTab(layout_page,'배치 / 배선')
        form=QFormLayout();lp.addLayout(form);self.board_name=QLineEdit(self.project.name);self.width=number(self.project.width_mm,2,500);self.height=number(self.project.height_mm,2,500);self.nets=QLineEdit(', '.join(self.project.nets));self.clearance=number(self.project.clearance_mm,.05,5);self.edge=number(self.project.edge_clearance_mm,0,10)
        for title,w in [('이름',self.board_name),('보드 폭 mm',self.width),('보드 높이 mm',self.height),('net (쉼표 구분)',self.nets),('net 간격 mm',self.clearance),('경계 여유 mm',self.edge)]:form.addRow(title,w)
        lp.addWidget(push('보드 조건 적용',self.edit_board))
        self.components=QTableWidget(0,3);self.components.setHorizontalHeaderLabels(['참조','값 / 모델','net']);self.components.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.components.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.components.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.components.cellDoubleClicked.connect(lambda *_:self.edit_component());lp.addWidget(self.components)
        row=QHBoxLayout();self.add_kind=QComboBox();self.add_kind.addItems(['resistor','capacitor','voltage_source','none','unsupported']);row.addWidget(self.add_kind);row.addWidget(push('추가',self.add_component,'pcbAdd'));row.addWidget(push('핀 / 모델 / 가격 편집',self.edit_component));row.addWidget(push('삭제',self.delete_component));lp.addLayout(row)
        row=QHBoxLayout();self.route_button=QCheckBox('수동 배선 · Manual route');self.route_button.toggled.connect(self.set_routing);row.addWidget(self.route_button);self.layer=QComboBox();self.layer.addItems(['F.Cu','B.Cu']);self.layer.currentTextChanged.connect(self.layer_changed);row.addWidget(self.layer);self.track_width=number(.25,.05,10);row.addWidget(self.track_width);lp.addLayout(row)
        help_label=QLabel('부품 드래그로 배치 · 배선: 시작 패드 → 꺾임점 → 같은 net 끝 패드\n우클릭 / Esc 취소 · 서로 다른 층은 다층 패드로만 연결');help_label.setWordWrap(True);lp.addWidget(help_label)
        self.tracks=QComboBox();lp.addWidget(self.tracks);lp.addWidget(push('선택 배선 삭제',self.delete_track));lp.addWidget(push('배치 / 구리 연결 검사',self.check_layout,'pcbLayoutCheck'))
        sim_page=QWidget();sl=QVBoxLayout(sim_page);self.tabs.addTab(sim_page,'시뮬레이션 / AI');sf=QFormLayout();sl.addLayout(sf)
        self.analysis=QComboBox();self.analysis.addItems(['dc','ac']);self.analysis.setCurrentText(self.project.simulation.analysis);self.frequency=number(self.project.simulation.frequency_hz,.001,1e9)
        sf.addRow('해석',self.analysis);sf.addRow('AC 주파수 Hz',self.frequency);sl.addWidget(push('명시 실행 · Simulate',self.simulate,'pcbSimulate'))
        self.sim_text=QPlainTextEdit();self.sim_text.setReadOnly(True);sl.addWidget(self.sim_text,1)
        self.question=QPlainTextEdit('이 PCB의 net·배치·배선과 회로 모델을 검토하고, 개선안을 설명해 주세요.');self.question.setMaximumHeight(90);sl.addWidget(self.question)
        row=QHBoxLayout();row.addWidget(push('Codex PCB 설계 자문',self.review,'pcbAI'));self.cancel_button=push('자문 취소',self.stop_advice,'pcbAICancel');self.cancel_button.setEnabled(False);row.addWidget(self.cancel_button);sl.addLayout(row)
        self.advice=QPlainTextEdit();self.advice.setReadOnly(True);sl.addWidget(self.advice,1)
        bom_page=QWidget();bl=QVBoxLayout(bom_page);self.tabs.addTab(bom_page,'BOM / 예산');bf=QFormLayout();bl.addLayout(bf);self.quantity=QSpinBox();self.quantity.setRange(1,100000);self.quantity.setValue(self.project.budget.board_quantity);self.currency=QLineEdit(self.project.budget.currency);self.limit=QLineEdit(str(self.project.budget.limit) if self.project.budget.limit is not None else '')
        for title,w in [('보드 수량',self.quantity),('예산 통화',self.currency),('예산 한도 (빈칸=미정)',self.limit)]:bf.addRow(title,w)
        bl.addWidget(push('BOM / 예산 계산',self.update_budget,'pcbBOM'));self.bom_text=QPlainTextEdit();self.bom_text.setReadOnly(True);bl.addWidget(self.bom_text)
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status)
        self.canvas.placementChanged.connect(self.move_component);self.canvas.componentSelected.connect(self.select_component);self.canvas.routeClicked.connect(self.route_click);self.redraw()

    def error(self,exc):self.status.setText(str(exc))

    def set_project(self,project):
        checked=PCBProject.model_validate(project)
        self.stop_advice();self.project=checked;self.dirty=True;self.simulation_result=None;self.sim_text.setPlainText('설계가 변경되었습니다. 시뮬레이션을 다시 실행하세요. / Design changed; rerun simulation.');self.advice.clear();self.route=None;self.canvas.route_points=[];self.redraw()

    def replace_project(self,project):self.set_project(project.model_dump(mode='json'));self.sync_fields()

    def redraw(self):
        self.canvas.project=self.project;self.canvas.update();self.components.setRowCount(len(self.project.components))
        for r,c in enumerate(self.project.components):
            for col,text in enumerate([c.ref,c.value or c.model.kind,', '.join(f'{p.number}:{p.net or "NC"}' for p in c.pins)]):self.components.setItem(r,col,QTableWidgetItem(text))
        self.tracks.clear()
        for t in self.project.tracks:self.tracks.addItem(t.id+' · '+t.net+' · '+t.layer,t.id)
        report=bom_report(self.project);self.bom_text.setPlainText(json.dumps(report,ensure_ascii=False,indent=2));self.status.setText(('PCB 초안 수정됨 · CAD에 PCB 저장으로 적용 / Unsaved PCB draft' if self.dirty else 'PCB 문서 준비 · Local draft')+' · R/C/전압원 DC·AC만 지원 · 제조/정격/열/실물 검증 미수행')

    def sync_fields(self):
        self.board_name.setText(self.project.name);self.width.setValue(self.project.width_mm);self.height.setValue(self.project.height_mm);self.nets.setText(', '.join(self.project.nets));self.clearance.setValue(self.project.clearance_mm);self.edge.setValue(self.project.edge_clearance_mm);self.analysis.setCurrentText(self.project.simulation.analysis);self.frequency.setValue(self.project.simulation.frequency_hz);self.quantity.setValue(self.project.budget.board_quantity);self.currency.setText(self.project.budget.currency);self.limit.setText(str(self.project.budget.limit) if self.project.budget.limit is not None else '')

    def selected_ref(self):
        row=self.components.currentRow()
        return self.components.item(row,0).text() if row>=0 and self.components.item(row,0) else None

    def select_component(self,ref):
        for r,c in enumerate(self.project.components):
            if c.ref==ref:self.components.selectRow(r);break

    def edit_board(self):
        raw=self.project.model_dump(mode='json');raw.update(name=self.board_name.text(),width_mm=self.width.value(),height_mm=self.height.value(),nets=[n.strip() for n in self.nets.text().split(',')],clearance_mm=self.clearance.value(),edge_clearance_mm=self.edge.value())
        try:self.set_project(raw)
        except ValueError as exc:self.error(exc)

    def add_component(self):
        kind=self.add_kind.currentText();prefix={'resistor':'R','capacitor':'C','voltage_source':'V','none':'J','unsupported':'U'}[kind];used={c.ref for c in self.project.components};i=1
        while prefix+str(i) in used:i+=1
        self.edit_component(new_component(kind,prefix+str(i)),adding=True)

    def edit_component(self,component=None,adding=False):
        ref=self.selected_ref()
        if component is None:component=next((c for c in self.project.components if c.ref==ref),None)
        if component is None:return
        dialog=PCBComponentEditor(self,component,self.project.nets)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
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

    def set_routing(self,enabled):self.canvas.routing=enabled;self.route=None;self.canvas.route_points=[];self.canvas.update()
    def layer_changed(self,layer):self.canvas.layer=layer;self.set_routing(self.route_button.isChecked())

    def route_click(self,packet):
        if packet.get('cancel'):self.route=None;self.canvas.route_points=[];self.canvas.update();return
        pad=packet['pad'];point=(pad['x'],pad['y']) if pad else tuple(round(v,3) for v in packet['point'])
        if self.route is None:
            if not pad or pad['net'] is None:self.error('net이 지정된 시작 패드를 선택하세요. / Select a connected start pad.');return
            self.route=dict(net=pad['net'],start=(pad['ref'],pad['pin']),points=[point],layer=self.layer.currentText())
        elif pad:
            if pad['net']!=self.route['net']:self.error('같은 net의 끝 패드를 선택하세요. / End pad must share the net.');return
            if (pad['ref'],pad['pin'])==self.route['start']:self.error('다른 끝 패드를 선택하세요. / Select a different end pad.');return
            points=self.route['points']+[point];raw=self.project.model_dump(mode='json');raw['tracks'].append(dict(id='T'+uuid4().hex[:12],net=self.route['net'],layer=self.route['layer'],width_mm=self.track_width.value(),points=[dict(x_mm=x,y_mm=y) for x,y in points]))
            try:self.set_project(raw)
            except ValueError as exc:self.error(exc)
            return
        elif point!=self.route['points'][-1]:self.route['points'].append(point)
        self.canvas.route_points=self.route['points'];self.canvas.update()

    def delete_track(self):
        raw=self.project.model_dump(mode='json');raw['tracks']=[t for t in raw['tracks'] if t['id']!=self.tracks.currentData()];self.set_project(raw)

    def check_layout(self):
        result=inspect_layout(self.project);self.sim_text.setPlainText(json.dumps(result,ensure_ascii=False,indent=2));self.tabs.setCurrentIndex(1);self.status.setText('배치 검사: '+result['status']+' · 제조/정격 승인 아님')

    def simulate(self):
        raw=self.project.model_dump(mode='json');raw['simulation']=dict(analysis=self.analysis.currentText(),frequency_hz=self.frequency.value())
        try:
            project=PCBProject.model_validate(raw)
            if pcb_digest(project)!=pcb_digest(self.project):self.set_project(project)
            self.simulation_result=simulate_pcb(self.project);self.sim_text.setPlainText(json.dumps(self.simulation_result,ensure_ascii=False,indent=2));self.status.setText('계산 완료 · 논리 netlist만 해석 · 구리 배선/실물 상태는 별도 확인')
        except ValueError as exc:self.simulation_result=None;self.sim_text.setPlainText('시뮬레이션 차단 / Blocked\n'+str(exc));self.error(exc)

    def update_budget(self):
        raw=self.project.model_dump(mode='json');raw['budget']=dict(board_quantity=self.quantity.value(),currency=self.currency.text().strip(),limit=self.limit.text().strip() or None)
        try:self.set_project(raw)
        except ValueError as exc:self.error(exc)

    def current_raw(self):
        from ..models import Design
        return deepcopy(self.host.document.design or Design().model_dump())

    def request_apply(self,electrical=False):
        try:
            raw=self.current_raw();checked=with_pcb(raw,self.project,expected_digest=self.base_sha)
            if electrical:
                # All layout errors must be resolved before claiming a routed
                # board was explicitly transferred into the electrical graph.
                report=inspect_layout(self.project)
                if report['findings']:raise ValueError('전장 적용 전에 배치/구리 연결 오류를 해결하세요. / Resolve layout findings before electrical apply.')
                data=checked.model_dump(mode='json');data['electrical']=electrical_preview(self.project,data.get('electrical'))
                from ..models import Design
                checked=Design.model_validate(data)
            self.applyRequested.emit(dict(design=checked.model_dump(mode='json'),base_sha256=self.base_sha,pcb_sha256=pcb_digest(self.project),electrical=electrical))
        except (ValueError,TypeError) as exc:self.error(exc)

    def document_changed(self,raw):
        # Metadata commits by another editor never silently discard this draft.
        incoming=design_digest(raw)
        if incoming==self.base_sha:return
        if raw.get('pcb') and pcb_digest(raw['pcb'])==pcb_digest(self.project):
            self.base=deepcopy(raw);self.base_sha=incoming;self.dirty=False;self.simulation_result=None;self.stop_advice();self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();return
        if self.dirty:self.stop_advice();self.error('CAD 문서가 변경되었습니다. 초안 내보내기 후 다시 불러오세요. / Stale document; export draft or reload.');return
        self.base=deepcopy(raw);self.base_sha=incoming;self.project=PCBProject.model_validate(raw.get('pcb') or {});self.simulation_result=None;self.stop_advice();self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();self.sync_fields()

    def reload(self):
        self.stop_advice();self.base=self.current_raw();self.base_sha=design_digest(self.base);self.project=PCBProject.model_validate(self.base.get('pcb') or {});self.dirty=False;self.simulation_result=None;self.sim_text.clear();self.advice.clear();self.route=None;self.canvas.route_points=[];self.canvas.drag=None;self.canvas.selected=None;self.redraw();self.sync_fields()

    def load_file(self):
        path,_=QFileDialog.getOpenFileName(self,'PCB 열기','','PCB (*.pcbp *.json)')
        if not path:return
        try:
            target=Path(path)
            if target.stat().st_size>2*1024*1024:raise ValueError('PCB 파일은 2 MiB 이하여야 합니다. / File too large.')
            self.replace_project(PCBProject.model_validate_json(target.read_bytes()))
        except (ValueError,OSError) as exc:self.error(exc)

    def export_file(self,kind):
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

    def review(self):
        if self.advice_task:return
        parent=self.host
        if getattr(parent,'ai_task',None):self.advice.setPlainText('CAD AI 요청이 끝난 뒤 실행하세요. / Another CAD AI request is active.');return
        model,effort=self.ai_identity();config=deepcopy(getattr(parent,'codex_config',{}))
        if not model:self.advice.setPlainText('CAD AI 패널의 Codex 계정·모델을 먼저 연결하세요.');return
        try:
            from .pcb_ai import advice_request
            advice_request(self.project,self.question.toPlainText())
        except ValueError as exc:self.error(exc);return
        from .ai_task import AITask
        from .pcb_ai import review_pcb
        project=self.project.model_copy(deep=True);sha=pcb_digest(project);base_sha=self.base_sha;question=self.question.toPlainText()
        task=AITask(lambda control,progress:review_pcb(project,question,model,executable=config.get('executable',''),effort=effort,control=control,progress=progress,deadline=180),parent)
        self.advice_task=task;self.cancel_button.setEnabled(True);self.advice.setPlainText('Codex PCB 자문 중 · PCB와 BOM 입력을 전송 · ChatGPT 구독 사용량 적용')
        def valid(sender):return self.alive and sender is self.advice_task and pcb_digest(self.project)==sha and self.ai_identity()==(model,effort) and design_digest(self.current_raw())==base_sha
        def complete(packet):
            sender,result=packet
            if not valid(sender):
                if sender is self.advice_task:self.stop_advice();self.advice.setPlainText('설계·문서·모델 설정이 변경되어 오래된 자문을 폐기했습니다. / Stale advice discarded.')
                return
            self.advice_task=None;self.cancel_button.setEnabled(False);self.advice.setPlainText('Codex 자문 · '+model+' / '+effort+'\n'+result['answer']+'\n\n제안은 자동 적용되지 않습니다. 직접 편집하고 검토 후 저장하세요.')
        def failed(packet):
            sender,message=packet
            if sender is not self.advice_task:return
            self.advice_task=None;self.cancel_button.setEnabled(False);self.advice.setPlainText('AI 자문 실패 · PCB 초안 보존\n'+str(message))
        task.completed.connect(complete,Qt.ConnectionType.QueuedConnection);task.failed.connect(failed,Qt.ConnectionType.QueuedConnection);task.start()

    def closeEvent(self,event):self.alive=False;self.stop_advice();super().closeEvent(event)
