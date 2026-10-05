"""Choose physical/documented terminals and wire dimensions explicitly."""
from PySide6.QtWidgets import QDialog,QDialogButtonBox,QFormLayout,QLineEdit,QComboBox,QVBoxLayout,QHBoxLayout,QColorDialog
from PySide6.QtGui import QColor

from ..electrical import ElectricalWorkspace
from ..mcu_connections import connection_endpoints
from ..circuit_connections import add_schematic_wire
from .widgets import label,number,button


class WireConnectionDialog(QDialog):
    def __init__(self,parent,workspace,*,english=False,selected_terminal=None):
        super().__init__(parent)
        self.workspace=ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self.english=english;self.checked=None;self.wire_id=None
        self.setObjectName('wireConnectionDialog');self.resize(650,390)
        self.setWindowTitle(self.word('전선 추가 · 핀 / 단자 선택','Add wire / choose endpoints'))
        root=QVBoxLayout(self);form=QFormLayout();root.addLayout(form)
        root.addWidget(label(self.word('실제 시작·도착 단자를 선택하세요. 전선 길이와 도체 단면적은 직접 입력합니다. 같은 노드에 연결된 경우 선택한 도착 단자에만 전선을 삽입합니다. 다른 핀·공유 노드는 유지됩니다.',
            'Choose the source and target terminals. Enter actual length and conductor area. If they share a net, the wire is inserted only at the selected target terminal; other pins and shared nets remain.'),True))
        names={component.id:component.name for component in self.workspace.components}
        self.endpoints={f'{row.component_id}|{row.terminal}':row for row in connection_endpoints(self.workspace)}
        self.source=QComboBox();self.source.setObjectName('wireSourceEndpoint')
        self.target=QComboBox();self.target.setObjectName('wireTargetEndpoint')
        for endpoint in connection_endpoints(self.workspace):
            text=f'{names[endpoint.component_id]} · {endpoint.label} [{endpoint.terminal}] · {endpoint.node or self.word("미연결","unconnected")}'
            key=(endpoint.component_id,endpoint.terminal)
            self.source.addItem(text,'|'.join(key));self.target.addItem(text,'|'.join(key))
        if selected_terminal:
            index=self.source.findData('|'.join(selected_terminal))
            if index>=0:self.source.setCurrentIndex(index)
        source_id=self.source.currentData().split('|')[0] if self.source.currentData() else None
        index=next((i for i in range(self.target.count()) if self.target.itemData(i).split('|')[0]!=source_id),-1)
        if index>=0:self.target.setCurrentIndex(index)
        form.addRow(self.word('시작 핀 / 단자','Source pin / terminal'),self.source)
        form.addRow(self.word('도착 핀 / 단자','Target pin / terminal'),self.target)
        self.name=QLineEdit(self.word('새 전선','New wire'));self.name.setMaxLength(80);form.addRow(self.word('전선 이름','Wire name'),self.name)
        self.length=number(0,0,1e7,' mm',decimals=3);self.length.setObjectName('wireLength')
        self.area=number(0,0,1e5,' mm²',decimals=6);self.area.setObjectName('wireArea')
        self.resistivity=number(.01724,.000001,100,' Ω·mm²/m',decimals=6)
        self.limit=number(0,0,10000,' A',decimals=3)
        form.addRow(self.word('실제 전선 길이','Actual wire length'),self.length)
        form.addRow(self.word('도체 단면적','Conductor cross-section'),self.area)
        form.addRow(self.word('저항률 · 기본은 실온 구리','Resistivity / default room-temperature copper'),self.resistivity)
        form.addRow(self.word('허용 전류 · 0은 미입력','Current limit / 0 means unspecified'),self.limit)
        colors=QHBoxLayout();self.color=QLineEdit('#297DC2');self.color.setMaxLength(7);self.color.setObjectName('wireColor')
        colors.addWidget(self.color);colors.addWidget(button(self.word('색 선택…','Choose color…'),self.choose_color))
        form.addRow(self.word('전선 색','Wire color'),colors)
        self.preview=label('',True);root.addWidget(self.preview)
        self.source.currentIndexChanged.connect(self.update_preview);self.target.currentIndexChanged.connect(self.update_preview)
        self.update_preview()
        self.status=label('',True);root.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);root.addWidget(buttons)

    def word(self,ko,en):return en if self.english else ko

    def update_preview(self,*_):
        source=self.endpoints.get(self.source.currentData());target=self.endpoints.get(self.target.currentData())
        if source and target and source.node is not None and source.node==target.node:
            self.preview.setText(self.word(f'적용 시 {target.component_id} · {target.terminal}만 {target.node}에서 분리해 전선을 삽입합니다. 이 전선을 삭제하면 해당 단자는 분리된 채 남습니다.',
                f'Applying detaches only {target.component_id} · {target.terminal} from {target.node} to insert this wire. Deleting it leaves that terminal disconnected.'))
        else:self.preview.setText(self.word('선택한 단자 사이에 실제 저항을 가진 전선 분기를 추가합니다. 다른 연결은 유지합니다.',
            'Add a wire branch with actual resistance between these terminals. Other connections remain.'))

    def choose_color(self):
        color=QColorDialog.getColor(QColor(self.color.text()),self)
        if color.isValid():self.color.setText(color.name())

    def accept(self):
        source=self.source.currentData();target=self.target.currentData()
        if not source or not target:
            self.status.setText(self.word('두 부품의 핀 또는 단자를 먼저 등록하세요.','Register terminals on two components first.'));return
        try:
            checked=add_schematic_wire(self.workspace,*source.split('|'),*target.split('|'),name=self.name.text().strip(),
                length_mm=self.length.value(),cross_section_mm2=self.area.value(),
                resistivity_ohm_mm2_per_m=self.resistivity.value(),max_current_a=self.limit.value() or None,
                wire_color=self.color.text().strip() or None)
        except ValueError as exc:self.status.setText(str(exc)[:1200]);return
        old={component.id for component in self.workspace.components}
        self.wire_id=next(component.id for component in checked.components if component.id not in old)
        self.checked=checked
        super().accept()
