"""Native parameter preview for an inspectable, unqualified specimen chamber."""
from copy import deepcopy

from PySide6.QtWidgets import (QCheckBox,QFormLayout,QLineEdit,QGroupBox,QVBoxLayout,
    QTabWidget,QScrollArea,QWidget,QPlainTextEdit)

from .workflows import PreviewDialog
from .widgets import number, label
from ..chamber_design import (
    ChamberRequirements, ChamberBounds, ParasiticForceInputs, build_chamber, inspect_chamber_interfaces,
)
from ..models import Design
from ..kernel import preview


def replacement_candidate(base, chamber, replace_ids=()):
    """Replace only the exact generated set while retaining external references.

    A changed generated set is refused rather than discarding a user's mates,
    manufacturing operations or named physical parts. Shared imported assets
    likewise cannot silently alter an unrelated component.
    """
    source=Design.model_validate(base);replace_ids=set(replace_ids)
    if not replace_ids:return chamber.append_to(source)
    present={p.id for p in source.parts};generated={p.id for p in chamber.parts}
    if not replace_ids<=present or replace_ids!=generated:
        raise ValueError('챔버 편집은 저장된 구성품 전체와 동일한 ID를 유지해야 합니다. 포트·인터페이스 종류를 바꾸려면 새 챔버로 추가하세요.')
    raw=source.model_dump();remaining=[p for p in raw['parts'] if p['id'] not in replace_ids]
    for part in remaining:
        key=part['geometry'].get('asset_id')
        if key in chamber.assets and source.assets[key].sha256!=chamber.assets[key].sha256:
            raise ValueError('챔버 BREP를 다른 부품도 공유합니다. 해당 부품을 분리한 뒤 편집하세요.')
    old={p['id']:p for p in raw['parts'] if p['id'] in replace_ids}
    revised=[]
    for part in chamber.parts:
        preserved=deepcopy(old[part.id]);fresh=part.model_dump()
        preserved.update(geometry=fresh['geometry'],transform=fresh['transform'])
        revised.append(preserved)
    revised_by_id={p['id']:p for p in revised}
    raw['parts']=[revised_by_id.get(p['id'],p) for p in raw['parts']]
    raw['assets'].update({k:v.model_dump() for k,v in chamber.assets.items()})
    candidate=Design.model_validate(raw)
    # Validation resolves assembly mates. Preserving a mate must not silently
    # move a newly dimensioned chamber away from its declared world bounds:
    # the protected and bellows envelopes are calculated at those bounds.
    from ..constraints import transform_matrix
    requested={part.id:part.transform for part in chamber.parts}
    misplaced=[]
    for part in candidate.parts:
        if part.id not in requested:continue
        wanted=requested[part.id];actual=part.transform
        position_error=max(abs(getattr(actual,axis)-getattr(wanted,axis)) for axis in ('x','y','z'))
        rotation_error=abs(transform_matrix(actual)-transform_matrix(wanted)).max()
        if position_error>1e-5 or rotation_error>1e-7:misplaced.append(part.id)
    if misplaced:
        raise ValueError('외부 조립 구속이 챔버 부품의 위치·방향을 요청한 보호 영역과 다르게 고정합니다. '
                         '기존 중심·방향을 유지하거나 조립 구속 위치를 재설정한 뒤 편집하세요: '+', '.join(misplaced[:4]))
    return candidate


def _selected_bounds(result, part_ids):
    ids=set(part_ids);meshes=[m for m in (result or {}).get('meshes',[]) if m['id'] in ids]
    if len(meshes)!=len(ids) or not meshes:
        raise ValueError('시편·그립을 선택하거나 챔버 보호 영역을 명시해서 다시 여세요.')
    points=[m['vertices'] for m in meshes]
    low=[min(value for vertices in points for value in vertices[axis::3]) for axis in range(3)]
    high=[max(value for vertices in points for value in vertices[axis::3]) for axis in range(3)]
    return ChamberBounds(minimum_mm=low,maximum_mm=high)


class ChamberDialog(PreviewDialog):
    """`checked` is the full Design; `report` is the latest JSON-safe report.

    Parameters are independent of a named machine. Optional `requirements`
    permits exact prior settings to be restored from document history.
    `replace_ids` must be the complete generated ID set from that history.
    """
    def __init__(self,parent,raw,part_ids=(),*,requirements=None,replace_ids=(),drive_part_ids=()):
        self.base=Design.model_validate(raw).model_dump()
        self.replace_ids=tuple(replace_ids);self.drive_part_ids=tuple(drive_part_ids)
        if requirements is None:
            initial=ChamberRequirements(protected_swept_bounds=_selected_bounds(getattr(parent,'result',None),part_ids))
        else:initial=ChamberRequirements.model_validate(requirements)
        if sum(s.face=='top' for s in initial.static_rod_seals)>1 or sum(s.face=='bottom' for s in initial.rod_interfaces)>1:
            raise ValueError('이 창은 상부 정적 로드 한 개와 하부 이동 로드 한 개를 편집합니다. 여러 로드의 설정은 공통 챔버 요구사항으로 분리해 지정하세요.')
        self.initial=initial;self.inputs={};self.optional_inputs={};self._chamber=None
        super().__init__(parent,'시편 습도 챔버','보호 영역·운동 범위 → 실제 본체·창·밀봉 인터페이스 → 전체 조립 간섭 확인. 누설·내압·벨로즈 수명은 별도 시험이 필요합니다.')
        self.prefix=QLineEdit(initial.prefix);self.prefix.setMaxLength(16)
        self.name=QLineEdit(initial.name);self.name.setMaxLength(60)
        self.controls.addWidget(label('챔버 이름 / 구성품 접두사'));self.controls.addWidget(self.name);self.controls.addWidget(self.prefix)
        self.prefix.setEnabled(not bool(replace_ids))
        self.name.textChanged.connect(self.schedule);self.prefix.textChanged.connect(self.schedule)
        self.inspect_open=QCheckBox('전면 도어 분리해 내부 보기 · 표시만')
        self.controls.addWidget(self.inspect_open);self.inspect_open.toggled.connect(self._display_inspection)
        self.tabs=QTabWidget();self.controls.addWidget(self.tabs,1);self.page_layouts={}
        for key,title in [('housing','보호 범위'),('interfaces','창 / 밀봉'),('review','하중 / 검사')]:
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumHeight(320)
            page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(6,10,6,10)
            self.page_layouts[key]=layout;scroll.setWidget(page);self.tabs.addTab(scroll,title)
        protected=self._group('시편·그립 전체 운동 보호 영역','housing')
        for axis,name in enumerate(('X','Y','Z')):
            self._input(protected,f'min-{axis}',f'{name} 최소',initial.protected_swept_bounds.minimum_mm[axis],-4500,4500)
            self._input(protected,f'max-{axis}',f'{name} 최대',initial.protected_swept_bounds.maximum_mm[axis],-4500,4500)
        self.page_layouts['housing'].addWidget(label('선택 형상의 현재 위치만 가져옵니다. 보호 영역에는 그립의 전체 스트로크와 측정 여유를 직접 포함하세요.',True))
        housing=self._group('본체 · 설치 여유','housing')
        for axis,name in enumerate(('X','Y','Z')):
            self._input(housing,f'clearance-{axis}',f'{name} 내부 여유',initial.clearance_mm[axis],.1,200)
        self._input(housing,'wall','본체 벽 두께',initial.wall_thickness_mm,1,50)
        self._input(housing,'door','전면 도어 두께',initial.door_thickness_mm,1,30)
        self._input(housing,'gasket','가스켓 원두께',initial.gasket_thickness_mm,.2,10)
        self._input(housing,'gasket-compression','가스켓 압축',initial.gasket_compression_fraction*100,0,30,' %')
        window=self._group('관찰창 · 습도 포트','interfaces')
        self.window=QCheckBox('관찰창 포함');self.window.setChecked(initial.observation_window)
        window.addRow(self.window);self.window.toggled.connect(self.schedule)
        cavity=[size+2*gap for size,gap in zip(initial.protected_swept_bounds.size,initial.clearance_mm)]
        self._input(window,'window-width','관찰 개구 폭',initial.window_width_mm or cavity[0]*.6,10,1500)
        self._input(window,'window-height','관찰 개구 높이',initial.window_height_mm or cavity[2]*.65,10,1500)
        self._input(window,'window-thickness','창 두께',initial.window_thickness_mm,1,30)
        self.ports=QCheckBox('정적 습도 포트 포함');self.ports.setChecked(bool(initial.static_ports))
        window.addRow(self.ports);self.ports.toggled.connect(self.schedule)
        self._input(window,'port-bore','포트 유로 내경',initial.static_ports[0].bore_diameter_mm if initial.static_ports else 6,.1,100)
        self.uniform_port_bore=QCheckBox('모든 정적 포트 유로 내경 동일하게')
        self.uniform_port_bore.setChecked(len({port.bore_diameter_mm for port in initial.static_ports})<=1)
        window.addRow(self.uniform_port_bore);self.uniform_port_bore.toggled.connect(self.schedule)
        self.inputs['port-bore'].valueChanged.connect(lambda *_:self.uniform_port_bore.setChecked(True))
        interface=self._group('하중 로드 밀봉 인터페이스','interfaces')
        self.top_static=QCheckBox('상부 고정 로드 · 정적 O링 홈');self.top_static.setChecked(any(s.face=='top' for s in initial.static_rod_seals))
        interface.addRow(self.top_static);self.top_static.toggled.connect(self.schedule)
        static=next((s for s in initial.static_rod_seals if s.face=='top'),None)
        self._input(interface,'top-diameter','상부 고정 로드 지름',static.rod_diameter_mm if static else 20,.1,150)
        self._input(interface,'top-x','상부 로드 X (영역 중심 기준)',static.position_xy_mm[0] if static else 0,-500,500)
        self._input(interface,'top-y','상부 로드 Y (영역 중심 기준)',static.position_xy_mm[1] if static else 0,-500,500)
        self._input(interface,'oring-section','정적 O링 단면 지름',static.cross_section_mm if static else 3,.5,10)
        self._input(interface,'oring-compression','정적 O링 반경 압축',static.radial_compression_fraction*100 if static else 20,1,30,' %')
        self._input(interface,'static-cap','정적 밀봉 캡 외경',static.cap_outer_diameter_mm if static else 46,12,200)
        self.bottom_moving=QCheckBox('하부 이동 로드 · 벨로즈 공간');self.bottom_moving.setChecked(any(s.face=='bottom' for s in initial.rod_interfaces))
        interface.addRow(self.bottom_moving);self.bottom_moving.toggled.connect(self.schedule)
        moving=next((s for s in initial.rod_interfaces if s.face=='bottom'),None)
        self._input(interface,'bottom-diameter','하부 이동 로드 지름',moving.rod_diameter_mm if moving else 20,.1,150)
        self._input(interface,'bottom-x','하부 로드 X (영역 중심 기준)',moving.position_xy_mm[0] if moving else 0,-500,500)
        self._input(interface,'bottom-y','하부 로드 Y (영역 중심 기준)',moving.position_xy_mm[1] if moving else 0,-500,500)
        self._input(interface,'bellows-inner','벨로즈 내경',moving.bellows_inner_diameter_mm if moving else 28,.1,200)
        self._input(interface,'bellows-outer','벨로즈 외경',moving.bellows_outer_diameter_mm if moving else 42,.1,300)
        self._input(interface,'bellows-length','벨로즈 설치 길이 (칼라 제외)',moving.installed_length_mm if moving else 44,5,500)
        self._input(interface,'stroke-min','하부 최소 스트로크',moving.stroke_min_mm if moving else -5,-300,300)
        self._input(interface,'stroke-max','하부 최대 스트로크',moving.stroke_max_mm if moving else 5,-300,300)
        self._optional(interface,'supplier_compressed_length_mm','공급사 최소 압축 길이 (mm)',moving.supplier_compressed_length_mm if moving else None)
        self._optional(interface,'supplier_extended_length_mm','공급사 최대 신장 길이 (mm)',moving.supplier_extended_length_mm if moving else None)
        self.page_layouts['interfaces'].addWidget(label('고정 로드의 정적 O링은 왕복 운동용이 아닙니다. 하부 벨로즈는 실제 공급사 압축·신장 한계와 수명을 확인하세요. 각 칼라는 3 mm입니다.',True))
        force=self._group('기생 하중 입력 · 미정은 빈칸','review')
        for key,title in [('pressure_differential_pa','내외 차압 (Pa)'),('bellows_effective_area_mm2','공급사 유효 면적 (mm²)'),
            ('bellows_spring_rate_n_per_mm','벨로즈 스프링 상수 (N/mm)'),('bellows_deflection_from_free_mm','자유 길이 대비 변위 (mm)'),
            ('seal_friction_n','밀봉 마찰력 (N)'),('preload_n','기타 예하중 (N)'),('test_force_n','비교할 시험 하중 (N)')]:
            self._optional(force,key,title,getattr(initial.parasitic_force,key))
        self.page_layouts['review'].addWidget(label('추정값은 공급사·실측 입력을 사용합니다. 차압 유효 면적은 로드 단면적과 같다고 가정하지 않습니다.',True))
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMinimumHeight(130)
        self.details.setMaximumHeight(240);self.page_layouts['review'].addWidget(self.details)
        for layout in self.page_layouts.values():layout.addStretch()
        self.schedule()

    def _group(self,title,page):
        group=QGroupBox(title);form=QFormLayout(group);form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.page_layouts[page].addWidget(group);return form

    def _input(self,form,key,title,value,low,high,suffix=' mm'):
        widget=number(value,low,high,suffix);widget.setObjectName('chamber-'+key)
        self.inputs[key]=widget;form.addRow(title,widget);widget.valueChanged.connect(self.schedule)
        return widget

    def _optional(self,form,key,title,value):
        widget=QLineEdit('' if value is None else f'{value:g}')
        widget.setPlaceholderText('미정');widget.setObjectName('chamber-'+key)
        self.optional_inputs[key]=widget;form.addRow(title,widget);widget.textChanged.connect(self.schedule)
        return widget

    def _optional_value(self,key):
        text=self.optional_inputs[key].text().strip()
        if not text:return None
        try:return float(text)
        except ValueError:raise ValueError('미정 입력은 비워 두거나 숫자를 입력하세요: '+key) from None

    @property
    def report(self):
        return deepcopy((self.interference or {}).get('chamber_report',{}))

    def candidate(self):
        value=lambda key:self.inputs[key].value()
        raw=self.initial.model_dump(mode='json')
        raw.update(prefix=self.prefix.text().strip(),name=self.name.text().strip(),
            protected_swept_bounds=dict(minimum_mm=[value(f'min-{axis}') for axis in range(3)],
                                       maximum_mm=[value(f'max-{axis}') for axis in range(3)]),
            clearance_mm=[value(f'clearance-{axis}') for axis in range(3)],
            wall_thickness_mm=value('wall'),door_thickness_mm=value('door'),
            gasket_thickness_mm=value('gasket'),gasket_compression_fraction=value('gasket-compression')/100,
            observation_window=self.window.isChecked(),window_width_mm=value('window-width'),
            window_height_mm=value('window-height'),window_thickness_mm=value('window-thickness'))
        if self.ports.isChecked():
            ports=raw['static_ports'] or ChamberRequirements(protected_swept_bounds=raw['protected_swept_bounds']).model_dump(mode='json')['static_ports']
            if self.uniform_port_bore.isChecked():
                for port in ports:port['bore_diameter_mm']=value('port-bore')
            raw['static_ports']=ports
        else:raw['static_ports']=[]
        static=[row for row in raw['static_rod_seals'] if row['face']!='top']
        if self.top_static.isChecked():
            row=next((row for row in raw['static_rod_seals'] if row['face']=='top'),dict(id='upper',face='top'))
            row.update(rod_diameter_mm=value('top-diameter'),position_xy_mm=[value('top-x'),value('top-y')],
                cross_section_mm=value('oring-section'),radial_compression_fraction=value('oring-compression')/100,
                cap_outer_diameter_mm=value('static-cap'));static.append(row)
        raw['static_rod_seals']=static
        moving=[row for row in raw['rod_interfaces'] if row['face']!='bottom']
        if self.bottom_moving.isChecked():
            row=next((row for row in raw['rod_interfaces'] if row['face']=='bottom'),dict(id='lower',face='bottom'))
            row.update(rod_diameter_mm=value('bottom-diameter'),position_xy_mm=[value('bottom-x'),value('bottom-y')],
                bellows_inner_diameter_mm=value('bellows-inner'),bellows_outer_diameter_mm=value('bellows-outer'),
                installed_length_mm=value('bellows-length'),stroke_min_mm=value('stroke-min'),stroke_max_mm=value('stroke-max'),
                supplier_compressed_length_mm=self._optional_value('supplier_compressed_length_mm'),
                supplier_extended_length_mm=self._optional_value('supplier_extended_length_mm'))
            moving.append(row)
        raw['rod_interfaces']=moving
        raw['parasitic_force']={key:self._optional_value(key) for key in ParasiticForceInputs.model_fields}
        return ChamberRequirements.model_validate(raw).model_dump(mode='json')

    def compute(self,raw):
        def check():
            if not self.alive or self._active_revision!=self.revision:raise RuntimeError('미리보기가 취소되었습니다.')
        chamber=build_chamber(raw,check=check);candidate=replacement_candidate(self.base,chamber,self.replace_ids)
        check();rendered=preview(candidate);check();self._chamber=chamber
        return candidate,rendered

    def checked_compute(self,raw,revision):
        self._active_revision=revision
        candidate,rendered,interference,travel=super().checked_compute(raw,revision)
        # Compare service/motion envelopes only against existing components.
        # Generated chamber parts are never counted as their own obstructions.
        def check():
            if not self.alive or revision!=self.revision:raise RuntimeError('미리보기가 취소되었습니다.')
        hits=inspect_chamber_interfaces(self._chamber,self.base,drive_part_ids=self.drive_part_ids,
                                        exclude_part_ids=self.replace_ids,check=check)
        report=self._chamber.report();report['installation_obstructions']=hits
        interference=dict(interference,chamber_report=report)
        return candidate,rendered,interference,travel

    def present(self):
        super().present();report=self.report;estimate=report.get('parasitic_estimate',{})
        hits=report.get('installation_obstructions',[])
        summary=['실제 밀봉·내압·벨로즈 수명: 검증 전',f'설치·운동·공구 영역 장애물: {len(hits)}개']
        bound=estimate.get('conservative_force_bound_n')
        summary.append('기생 하중: 입력 미정 · 정격으로 사용하지 마세요.' if bound is None else f'입력값 기준 기생 하중 상한 추정: {bound:g} N')
        for hit in hits:summary.append(f"{hit['envelope']} ↔ {hit['part_id']}")
        self.details.setPlainText('\n'.join([*summary,'',*report.get('warnings',[])]))
        self.status.setText(self.status.text()+'\n밀봉·내압·벨로즈 수명: 검증 전')
        self._display_inspection()

    def _display_inspection(self,*args):
        # Disassembly is a visual aid only. The checked design and collision
        # calculation always retain the complete real door, pane and hardware.
        prefix=self.report.get('requirements',{}).get('prefix',self.initial.prefix)+'-'
        surfaces={'door','door-seal','window','window-seal','window-retainer'}
        for identifier,(actor,edge_actor) in self.viewport.actors.items():
            if not identifier.startswith(prefix):continue
            suffix=identifier[len(prefix):]
            if suffix in surfaces or suffix.startswith(('bolt-','nut-')):
                visible=not self.inspect_open.isChecked();actor.SetVisibility(visible)
                edge_actor.SetVisibility(visible and self.viewport.show_edges)
        if self.alive:self.viewport.render()

    def present_interference(self):
        super().present_interference()
        hits=[hit for hit in self.report.get('installation_obstructions',[]) if hit['kind'] in ('bellows_motion','interior_volume')]
        if hits:
            self.apply_button.setEnabled(False)
            self.status.setStyleSheet('color:#ffab91;')
            self.status.setText('구동기·벨로즈 운동 공간이 기존 부품과 겹칩니다. 적용 전 배치와 운동 범위를 수정하세요.\n'+
                '\n'.join(hit['envelope']+' ↔ '+hit['part_id'] for hit in hits[:3]))
