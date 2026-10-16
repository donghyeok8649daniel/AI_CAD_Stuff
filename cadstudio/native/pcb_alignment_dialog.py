"""Input-only pin alignment dialog. Solving and geometry checks run on Worker."""
import math
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QComboBox,QLineEdit,QCheckBox,QPushButton,QTableWidget,QHeaderView,
    QDialogButtonBox,QFileDialog,QScrollArea,QWidget)
from ..pcb import PCBProject,pcb_digest

MAX_REFERENCE_BYTES=2*1024*1024


class PCBAlignmentDialog(QDialog):
    def __init__(self,parent,project,selected_ref=None):
        super().__init__(parent);self.setWindowTitle('대응 핀 정렬 / Match pins');self.resize(930,780)
        self.project=project.model_copy(deep=True);self.external=None;self.checked=None
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);page=QWidget();root=QVBoxLayout(page);scroll.setWidget(page);outer.addWidget(scroll)
        note=QLabel('저장된 실제 패드 좌표·핀 규격만 사용합니다. 카탈로그 논리 핀으로 치수를 만들지 않습니다.\n계산은 미리보기입니다. 3D 높이·뒤집기는 2D PCB에 눌러 적용하지 않습니다. / Saved footprint data only; numerical preview, not mating approval.')
        note.setWordWrap(True);root.addWidget(note)
        form=QFormLayout();root.addLayout(form)
        self.source=QComboBox();self.target=QComboBox();self.source.setObjectName('pcbAlignSource');self.target.setObjectName('pcbAlignTarget')
        for component in self.project.components:self.source.addItem(component.ref+' · '+(component.value or component.mpn),component.ref)
        if self.source.findData(selected_ref)>=0:self.source.setCurrentIndex(self.source.findData(selected_ref))
        form.addRow('움직일 부품 / Source',self.source);form.addRow('대응 부품 / Target',self.target)
        external_row=QHBoxLayout();load=QPushButton('외부 PCB 참조… / External .pcbp');load.clicked.connect(self.load_external);external_row.addWidget(load)
        reset=QPushButton('현재 PCB 사용 / Same PCB');reset.clicked.connect(self.same_project);external_row.addWidget(reset);root.addLayout(external_row)
        self.reference_note=QLabel();self.reference_note.setWordWrap(True);root.addWidget(self.reference_note)
        self.geometry_note=QLabel();self.geometry_note.setWordWrap(True);root.addWidget(self.geometry_note)
        root.addWidget(QLabel('대응 핀을 직접 추가하세요 (최대 32쌍). 이름/net 일치는 전기 호환 확인이 아닙니다. / Explicit pairs; net names alone do not verify compatibility.'))
        self.pairs=QTableWidget(0,3);self.pairs.setObjectName('pcbAlignPinPairs');self.pairs.setHorizontalHeaderLabels(['Source 핀','Target 핀','전기 호환 / Compatibility']);self.pairs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);root.addWidget(self.pairs)
        row=QHBoxLayout();add=QPushButton('대응 쌍 추가 / Add pair');add.clicked.connect(self.add_pair);row.addWidget(add);remove=QPushButton('선택 쌍 삭제 / Remove');remove.clicked.connect(lambda:self.pairs.removeRow(self.pairs.currentRow()));row.addWidget(remove);root.addLayout(row)
        self.verified={};vf=QFormLayout();root.addLayout(vf)
        for side,label in [('source','Source'),('target','Target')]:
            physical=QCheckBox('실제 도면의 패드 좌표·리비전 대조 / Footprint reviewed');mapping=QCheckBox('핀 번호·전압·기능 대조 / Pin map reviewed')
            self.verified[side]=(physical,mapping);vf.addRow(label,physical);vf.addRow('',mapping)
        side_form=QFormLayout();root.addLayout(side_form);self.source_side=QComboBox();self.target_side=QComboBox()
        for widget in (self.source_side,self.target_side):
            widget.addItem('미확인 / Unknown',None);widget.addItem('위 / top','top');widget.addItem('아래 / bottom','bottom')
        side_form.addRow('Source 맞물림 면',self.source_side);side_form.addRow('Target 맞물림 면',self.target_side)
        self.plane=QCheckBox('저장 풋프린트 XY / +Z 기준면을 대조함 (실제 핀 끝 높이 확인 아님) / Local reference plane checked');root.addWidget(self.plane)
        self.allowed=QCheckBox('선택한 면 조합이 설계상 허용됨 / Selected side pair allowed');root.addWidget(self.allowed)
        dimensions=QFormLayout();root.addLayout(dimensions);self.values={}
        for key,label in [('stand_off_height_mm','기준면 간 높이 / Stand-off mm'),('insertion_depth_mm','삽입 깊이 / Insertion mm'),('max_pin_error_mm','핀 오차 허용 / Pin error mm'),('pitch_tolerance_mm','피치 공차 / Pitch mm'),('normal_tolerance_deg','법선·키 각도 공차 / Angle °')]:
            field=QLineEdit();field.setPlaceholderText('빈칸 = 미확인 / Unknown');self.values[key]=field;dimensions.addRow(label,field)
        self.keying=QCheckBox('키 방향 또는 무키 구조를 대조함 / Keying or unkeyed geometry reviewed');root.addWidget(self.keying)
        self.source_key=QLineEdit();self.target_key=QLineEdit()
        for field in (self.source_key,self.target_key):field.setPlaceholderText('로컬 x,y,z 방향 · 무키이면 빈칸 / Local axis; blank if unkeyed')
        dimensions.addRow('Source 키 축',self.source_key);dimensions.addRow('Target 키 축',self.target_key)
        self.tolerances=QCheckBox('입력한 세 공차를 도면과 대조함 / All three tolerances reviewed');root.addWidget(self.tolerances)
        self.registration_enabled=QCheckBox('외부 보드 기준면을 현재 PCB에 직접 등록 / Register external board frame');root.addWidget(self.registration_enabled)
        registration_note=QLabel('외부 PCB의 저장된 부품 위치까지 합성합니다. 값은 실제로 대조한 경우에만 입력하세요.\nXYZ 단위 mm, 회전은 고정축 X(roll)→Y(pitch)→Z(yaw). XY 평면/+Z, 높이 0인 등록만 2D 후보가 됩니다.\n목표 보드 전체/그룹을 옮기거나 3D 간섭을 확인하는 기능은 아닙니다. / Declared frame only; no parent-board move or whole 3D collision check.')
        registration_note.setWordWrap(True);root.addWidget(registration_note)
        registration_form=QFormLayout();root.addLayout(registration_form);self.registration_values={}
        for key,label in [('x','X mm'),('y','Y mm'),('z','Z mm'),('roll','Roll °'),('pitch','Pitch °'),('yaw','Yaw °')]:
            field=QLineEdit();field.setPlaceholderText('빈칸 = 등록 미확인 / Unknown');self.registration_values[key]=field;registration_form.addRow(label,field)
        self.registration_basis=QLineEdit();self.registration_basis.setPlaceholderText('기준점·방향·측정/도면 근거 / Frame datum and basis')
        self.registration_reviewer=QLineEdit();self.registration_date=QLineEdit();self.registration_date.setPlaceholderText('YYYY-MM-DD · 확인한 실제 날짜')
        registration_form.addRow('등록 근거 / Basis',self.registration_basis);registration_form.addRow('대조 담당 / Reviewed by',self.registration_reviewer);registration_form.addRow('대조 날짜 / Review date',self.registration_date)
        self.host_plane=QCheckBox('등록된 외부 보드가 현재 PCB의 XY/+Z 평면과 높이 0임을 대조함 / Host plane reviewed');root.addWidget(self.host_plane)
        self.source_plane=QCheckBox('Source 풋프린트의 XY/+Z 기준면이 현재 PCB와 같음을 대조함 / Source plane reviewed');root.addWidget(self.source_plane)
        unknown=QLabel('성별·실제 접점 높이·삽입/유지력·3D 충돌·전류/열·제조 검증은 별도입니다. / Gender, actual contact geometry, retention, collisions and ratings remain unverified.');unknown.setWordWrap(True);root.addWidget(unknown)
        self.error=QLabel();self.error.setWordWrap(True);outer.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('정렬 미리보기 계산 / Calculate preview');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        self.source.currentIndexChanged.connect(self.reset_mapping);self.target.currentIndexChanged.connect(self.reset_mapping)
        self.populate_target()

    def components(self,target=False):return (self.external if target and self.external is not None else self.project).components

    def chosen(self,target=False):
        ref=(self.target if target else self.source).currentData()
        return next((component for component in self.components(target) if component.ref==ref),None)

    def populate_target(self):
        self.target.blockSignals(True);self.target.clear()
        for component in self.components(True):self.target.addItem(component.ref+' · '+(component.value or component.mpn),component.ref)
        if self.external is None:
            index=next((index for index in range(self.target.count()) if self.target.itemData(index)!=self.source.currentData()),0)
            self.target.setCurrentIndex(index)
        self.target.blockSignals(False);self.reset_mapping();self.registration_enabled.setEnabled(self.external is not None)
        self.reference_note.setText('외부 PCB의 로컬 참조입니다. 아래 기준면 등록을 직접 확인하지 않으면 3D 미리보기만 제공합니다. / External local reference; explicit verified frame registration is required for any 2D candidate.' if self.external is not None else '현재 PCB의 저장된 대상 위치를 사용합니다. / Target stays at its saved same-board pose.')

    def reset_mapping(self,*_):
        self.pairs.setRowCount(0)
        for field in self.values.values():field.clear()
        self.source_key.clear();self.target_key.clear();self.source_side.setCurrentIndex(0);self.target_side.setCurrentIndex(0)
        for box in (self.plane,self.allowed,self.keying,self.tolerances):box.setChecked(False)
        for field in self.registration_values.values():field.clear()
        self.registration_basis.clear();self.registration_reviewer.clear();self.registration_date.clear()
        for box in (self.registration_enabled,self.host_plane,self.source_plane):box.setChecked(False)
        for boxes in self.verified.values():
            for box in boxes:box.setChecked(False)
        rows=[]
        for label,component in [('Source',self.chosen()),('Target',self.chosen(True))]:
            metadata=component.library_metadata if component else None
            rows.append(label+': '+('도면 대조 기록 있음 / source review record' if metadata and metadata.footprint_review_state=='source_reviewed' else '실제 풋프린트 대조 기록 미확인 / physical footprint unverified'))
        self.geometry_note.setText('\n'.join(rows))

    def add_pair(self):
        if self.pairs.rowCount()>=32:self.error.setText('최대 32쌍입니다. / At most 32 pairs.');return
        source,target=self.chosen(),self.chosen(True)
        if source is None or target is None:self.error.setText('양쪽 부품을 고르세요. / Select both components.');return
        row=self.pairs.rowCount();self.pairs.insertRow(row)
        for col,component in enumerate((source,target)):
            choice=QComboBox()
            for pin in component.pins:choice.addItem(pin.number+' · '+(pin.name or '핀')+' · '+(pin.net or 'NC'),pin.number)
            self.pairs.setCellWidget(row,col,choice)
        compatibility=QComboBox()
        for label,value in [('미확인 / Unknown','unverified'),('호환을 대조함 / Compatible','compatible'),('호환 안 됨 / Incompatible','incompatible')]:compatibility.addItem(label,value)
        self.pairs.setCellWidget(row,2,compatibility)

    def load_external(self):
        filename,_=QFileDialog.getOpenFileName(self,'외부 PCB 참조 / Reference only','','PCB (*.pcbp)')
        if not filename:return
        try:
            with Path(filename).open('rb') as stream:raw=stream.read(MAX_REFERENCE_BYTES+1)
            if len(raw)>MAX_REFERENCE_BYTES:raise ValueError('외부 참조는 2 MiB 이하여야 합니다. / Reference too large.')
            self.external=PCBProject.model_validate_json(raw);self.populate_target()
        except (ValueError,OSError) as error:self.error.setText(str(error))

    def same_project(self):self.external=None;self.populate_target()

    @staticmethod
    def numeric(field):
        if not field.text().strip():return None
        value=float(field.text())
        if not math.isfinite(value) or value<0:raise ValueError('유한한 0 이상의 수치를 입력하세요. / Finite nonnegative value required.')
        return value

    @staticmethod
    def axis(field):
        if not field.text().strip():return None
        values=[float(value.strip()) for value in field.text().split(',')]
        if len(values)!=3 or any(not math.isfinite(value) for value in values) or sum(value*value for value in values)<1e-12:raise ValueError('키 축은 0이 아닌 유한한 x,y,z입니다. / Finite nonzero x,y,z axis required.')
        return values

    @staticmethod
    def signed_numeric(field):
        if not field.text().strip():return None
        value=float(field.text())
        if not math.isfinite(value):raise ValueError('등록 좌표와 각도는 유한한 숫자입니다. / Finite coordinates and angles required.')
        return value

    def inputs(self):
        source,target=self.source.currentData(),self.target.currentData()
        if source is None or target is None or self.external is None and source==target:raise ValueError('서로 다른 부품을 선택하세요. / Select distinct components.')
        if not 1<=self.pairs.rowCount()<=32:raise ValueError('대응 핀을 1~32쌍 지정하세요. / Select 1..32 pairs.')
        mapping=[dict(source_pin=self.pairs.cellWidget(row,0).currentData(),target_pin=self.pairs.cellWidget(row,1).currentData(),net_compatibility=self.pairs.cellWidget(row,2).currentData()) for row in range(self.pairs.rowCount())]
        if len({pair['source_pin'] for pair in mapping})!=len(mapping) or len({pair['target_pin'] for pair in mapping})!=len(mapping):raise ValueError('핀은 각각 한 번만 대응시킬 수 있습니다. / Each pin may be mapped once.')
        mating={};constraints={};values={key:self.numeric(field) for key,field in self.values.items()}
        for key in ('stand_off_height_mm','insertion_depth_mm'):
            if values[key] is not None:mating[key]=values[key]
        for side,widget in [('source',self.source_side),('target',self.target_side)]:
            if widget.currentData():mating[side+'_side']=widget.currentData()
        if self.plane.isChecked():mating.update(source_normal=[0,0,1],target_normal=[0,0,1])
        if self.allowed.isChecked():
            if not self.source_side.currentData() or not self.target_side.currentData():raise ValueError('허용 조합을 확인하려면 양쪽 면을 선택하세요.')
            mating['allowed_side_pairs']=[[self.source_side.currentData(),self.target_side.currentData()]]
        source_key,target_key=self.axis(self.source_key),self.axis(self.target_key)
        if (source_key is None)!=(target_key is None):raise ValueError('키 축은 양쪽을 함께 입력하세요. / Provide both key axes.')
        if source_key is not None:mating.update(source_key_axis=source_key,target_key_axis=target_key)
        mating['keying_verified']=self.keying.isChecked()
        keys=('max_pin_error_mm','pitch_tolerance_mm','normal_tolerance_deg')
        for key in keys:
            if values[key] is not None:constraints[key]=values[key]
        if self.tolerances.isChecked() and any(values[key] is None for key in keys):raise ValueError('공차 확인에는 세 수치를 모두 입력하세요. / Supply all three tolerances before confirming.')
        constraints['tolerances_verified']=self.tolerances.isChecked()
        result=dict(source_ref=source,target_ref=target,mapping=mapping,mating=mating,constraints=constraints,
            verification={side:dict(footprint_verified=boxes[0].isChecked(),pin_map_verified=boxes[1].isChecked()) for side,boxes in self.verified.items()})
        if self.external is not None:result['target_project']=self.external.model_dump(mode='json')
        if self.registration_enabled.isChecked():
            if self.external is None:raise ValueError('기준면 등록에는 외부 PCB 참조를 먼저 선택하세요. / Select an external PCB reference.')
            coordinates=[self.signed_numeric(self.registration_values[key]) for key in ('x','y','z','roll','pitch','yaw')]
            registration=dict(units='mm',target_project_sha256=pcb_digest(self.external),host_plane_verified=self.host_plane.isChecked(),source_plane_verified=self.source_plane.isChecked(),
                basis=self.registration_basis.text().strip(),reviewed_by=self.registration_reviewer.text().strip(),reviewed_date=self.registration_date.text().strip())
            if all(value is not None for value in coordinates):
                from ..pcb_pin_alignment import pose_from_xyz_rpy
                registration['target_board_to_host']=pose_from_xyz_rpy(*coordinates)
            result['target_registration']=registration
        return result

    def accept(self):
        self.checked=None
        try:self.checked=self.inputs()
        except (ValueError,TypeError) as error:self.error.setText(str(error));return
        super().accept()
