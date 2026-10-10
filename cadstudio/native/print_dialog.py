"""Output-only plate layouts, with export tied to the latest checked batch."""
from copy import deepcopy
from PySide6.QtCore import QSignalBlocker, QThreadPool
from PySide6.QtWidgets import QCheckBox, QFormLayout, QFileDialog, QWidget, QVBoxLayout, QToolButton, QHBoxLayout
from ..printing import prepare_print_plates, export_print_stl, export_print_stls, print_part_classification
from .workflows import PreviewDialog, choice
from .widgets import label, number, button, Worker


class PrintDialog(PreviewDialog):
    def __init__(self, parent, raw, selected=()):
        super().__init__(parent, '3D 프린팅 · STL 미리보기', '출력할 부품을 선택하세요. 부품이 많으면 여러 출력판에 나누며 원본 설계·관절은 변경하지 않습니다.')
        self.source = deepcopy(raw)
        self.initial_selection = set(selected) & {p['id'] for p in raw['parts']}
        self.part_boxes = {}; self.warnings = []; self.bed_actor = None
        self.placements = {}; self.plate_assignments = {}; self.checked_batch = None
        self.plate_view_initialized = False; self.preferred_part = None
        self.apply_button.setText('이 미리보기로 STL 저장')

        def section(title, opened=False):
            toggle = QToolButton(); toggle.setText(('▾ ' if opened else '▸ ') + title); toggle.setCheckable(True)
            self.controls.addWidget(toggle)
            panel = QWidget(); box = QVBoxLayout(panel); box.setContentsMargins(0, 0, 0, 0)
            panel.setVisible(opened); self.controls.addWidget(panel); toggle.setChecked(opened)
            def changed(value):
                panel.setVisible(value); toggle.setText(('▾ ' if value else '▸ ') + title)
            toggle.toggled.connect(changed)
            return box

        form = QFormLayout(); self.controls.addLayout(form)
        self.plate_choice = choice([(0, '출력판 1')]); form.addRow('미리볼 출력판', self.plate_choice)
        self.plate_choice.currentIndexChanged.connect(self.switch_plate)
        self.batch_summary = label('선택한 부품을 출력판에 배치합니다.', True); self.controls.addWidget(self.batch_summary)
        self.active_part = choice([]); self.active_part.setProperty('cadUserText', True); form.addRow('배치할 부품', self.active_part)
        self.target_plate = choice([]); form.addRow('이 부품의 출력판', self.target_plate); self.target_plate.currentIndexChanged.connect(self.move_to_plate)
        self.pose_inputs = {}
        for key, title in [('x', '바닥 중심 X'), ('y', '바닥 중심 Y'), ('rx', '부품 X 회전'), ('ry', '부품 Y 회전'), ('rz', '부품 Z 회전')]:
            w = number(0, -5000 if len(key) == 1 else -360, 5000 if len(key) == 1 else 360, ' mm' if len(key) == 1 else ' °')
            self.pose_inputs[key] = w; form.addRow(title, w); w.valueChanged.connect(self.change_pose)
        self.active_part.currentIndexChanged.connect(self.sync_pose)
        self.drag_enabled = QCheckBox('부품을 드래그해서 바닥에 배치'); self.drag_enabled.setChecked(True); self.controls.addWidget(self.drag_enabled)
        self.controls.addWidget(button('상면에서 배치', self.top_plate))
        self.controls.addWidget(button('전체 자동 배치 / 방향 초기화', self.auto_pack))
        self.current_stl_button = button('현재 출력판 STL 저장', lambda: self.export_checked(current_only=True))
        self.current_stl_button.setEnabled(False); self.controls.addWidget(self.current_stl_button)
        self.exclude_fasteners = QCheckBox('볼트·너트 제외'); self.controls.addWidget(self.exclude_fasteners)
        self.exclude_fasteners.setToolTip('볼트·너트 판별 근거를 표시합니다. 이름에 따른 추정은 제품 확인이 아니며 와셔·핀과 미분류 부품은 남깁니다.')
        self.exclude_fasteners.toggled.connect(self.schedule)
        self.excluded_summary = label('', True); self.excluded_summary.hide(); self.controls.addWidget(self.excluded_summary)
        row = QHBoxLayout(); self.controls.addLayout(row)
        self.select_current_button = button('현재 선택', lambda: self.select_parts(self.initial_selection))
        self.select_current_button.setEnabled(bool(self.initial_selection)); row.addWidget(self.select_current_button)
        row.addWidget(button('전체 선택', lambda: self.select_parts(self.part_boxes)))
        row.addWidget(button('선택 해제', lambda: self.select_parts(())))
        picks = section('출력할 부품 선택', True)
        for part in raw['parts']:
            box = QCheckBox(part['name']); box.setProperty('cadUserText', True)
            box.setChecked(not self.initial_selection or part['id'] in self.initial_selection)
            box.toggled.connect(self.schedule); picks.addWidget(box); self.part_boxes[part['id']] = box
        settings = section('프린터 / 자동 배치 설정'); form = QFormLayout(); settings.addLayout(form)
        self.orientation = []; self.bed = []
        for axis in 'XYZ':
            w = choice([(0, '0°'), (90, '90°'), (180, '180°'), (270, '270°')]); w.currentIndexChanged.connect(self.auto_pack)
            form.addRow('출력 ' + axis + ' 회전', w); self.orientation.append(w)
        for axis, value in zip('XYZ', (220, 220, 250)):
            w = number(value, 1, 5000, ' mm'); w.valueChanged.connect(self.schedule); form.addRow('출력 영역 ' + axis, w); self.bed.append(w)
        self.gap = number(5, .1, 100, ' mm'); self.gap.valueChanged.connect(self.auto_pack); form.addRow('부품 간격', self.gap)
        self.quality = choice([(.025, '정밀 · 0.025 mm'), (.05, '표준 · 0.05 mm'), (.1, '가벼움 · 0.1 mm'), (.01, '고정밀 · 0.01 mm')]); form.addRow('STL 메시 오차', self.quality)
        self.controls.addWidget(label('선택한 부품의 바운딩 박스 중심을 X/Y로 지정합니다. 회전 후 바닥 Z=0에 놓습니다. 빈 공간 드래그는 시점 회전입니다.', True))
        self.controls.addWidget(label('한 부품이 출력 영역보다 크면 경고합니다. 부품 자체를 자르지 않습니다. 여러 출력판은 판별 STL과 목록을 ZIP으로 저장합니다.', True))
        from .print_placement import PrintPlacementHandle
        self.placement_handle = PrintPlacementHandle(self)
        self.viewport.footer.setText('부품 드래그: 출력 위치 이동 · 휠: 커서 중심 확대 · 빈 공간 드래그: 회전')
        settings.addWidget(label('단위 mm · 현재 형상을 출력하며 보정을 중복 적용하지 않습니다. 서포트·인필·레이어·G-code는 슬라이서에서 설정하세요.', True))
        self.controls.addStretch(); self.sync_pose(); self.schedule()

    def select_parts(self, identifiers):
        selected = set(identifiers)
        for identifier, box in self.part_boxes.items():
            with QSignalBlocker(box): box.setChecked(identifier in selected)
        self.schedule()

    def schedule(self, *args):
        self.checked_batch = None
        if hasattr(self, 'current_stl_button'): self.current_stl_button.setEnabled(False)
        if hasattr(self, 'excluded_summary'):
            details = []
            for part in self.source['parts']:
                box = self.part_boxes.get(part['id'])
                if not self.exclude_fasteners.isChecked() or box is None or not box.isChecked(): continue
                classification = print_part_classification(part)
                if classification['kind'] in ('bolt', 'nut'):
                    details.append(f"{part['name']} [{part['id']}] · {classification['reason']}")
            self.excluded_summary.setVisible(bool(details))
            self.excluded_summary.setText(f'볼트·너트 제외 {len(details)}개\n' + '\n'.join(details[:3]))
            self.excluded_summary.setToolTip('\n'.join(details))
        super().schedule(*args)

    def failed(self, message):
        self.checked_batch = None
        self.current_stl_button.setEnabled(False)
        super().failed(message)

    def candidate(self):
        identifiers = [key for key, box in self.part_boxes.items() if box.isChecked()]; selected = set(identifiers)
        options = dict(raw=self.source, identifiers=identifiers,
                       rotation=[w.currentData() for w in self.orientation], bed=[w.value() for w in self.bed], gap=self.gap.value(),
                       placements=deepcopy({key: value for key, value in self.placements.items() if key in selected}),
                       plate_assignments={key: value for key, value in self.plate_assignments.items() if key in selected},
                       exclude_fasteners=self.exclude_fasteners.isChecked())
        return dict(options=options, plate=self.plate_choice.currentData() or 0, preferred_part=self.preferred_part)

    def auto_pack(self, *_):
        self.placements = {}; self.plate_assignments = {}; self.preferred_part = None
        self.fit_next = True; self.schedule()

    def top_plate(self):
        self.viewport.set_view('top', False); x, y, _ = [w.value() for w in self.bed]
        self.viewport.renderer.ResetCamera(-x / 2, x / 2, -y / 2, y / 2, 0, 0)
        self.viewport.renderer.ResetCameraClippingRange(); self.viewport.render()

    def sync_pose(self, *_):
        identifier = self.active_part.currentData(); pose = self.placements.get(identifier)
        for key, w in self.pose_inputs.items():
            with QSignalBlocker(w): w.setEnabled(pose is not None); w.setValue((pose or {}).get(key, 0))
        with QSignalBlocker(self.target_plate):
            self.target_plate.setEnabled(pose is not None and self.checked_batch is not None)
            self.target_plate.setCurrentIndex(self.target_plate.findData(self.plate_assignments.get(identifier, self.plate_choice.currentData() or 0)))
        self.viewport.select(identifier if identifier in self.viewport.actors else None)

    def change_pose(self, *_):
        identifier = self.active_part.currentData()
        if identifier not in self.placements: return
        self.placements[identifier] = {key: w.value() for key, w in self.pose_inputs.items()}
        self.plate_assignments[identifier] = self.plate_choice.currentData() or 0
        self.schedule()

    def move_to_plate(self, *_):
        identifier = self.active_part.currentData(); target = self.target_plate.currentData()
        if self.checked_batch is None or identifier not in self.placements or target is None: return
        if target == self.plate_assignments.get(identifier): return
        self.plate_assignments[identifier] = target; self.preferred_part = identifier
        self.fit_next = True; self.schedule()

    def compute(self, payload):
        revision = payload.get('revision', self.revision); cancelled = lambda: not self.alive or revision != self.revision
        plates, results, warnings = prepare_print_plates(**payload['options'], cancelled=cancelled)
        if not plates or len(plates) != len(results): raise ValueError('출력할 부품을 하나 이상 선택하세요.')
        index = min(max(0, payload['plate']), len(plates) - 1); preferred = payload.get('preferred_part')
        if preferred: index = next((i for i, plate in enumerate(plates) if any(p.id == preferred for p in plate.parts)), index)
        batch = dict(plates=plates, results=results, warnings=list(warnings), reports=[], selected=index)
        result = dict(results[index]); result['_print_batch'] = batch
        return plates[index], result

    def checked_compute(self, payload, revision):
        from ..interference import assess
        from ..kernel import KERNEL_LOCK
        def check():
            if not self.alive or revision != self.revision: raise RuntimeError('미리보기가 취소되었습니다.')
        with KERNEL_LOCK:
            check(); design, result = self.compute({**payload, 'revision': revision}); check(); batch = result['_print_batch']
            for index, (plate, plate_result) in enumerate(zip(batch['plates'], batch['results'])):
                check(); report = assess(plate, collisions=plate_result['stats']['collisions'], check=check); batch['reports'].append(report)
                if report['blocked']: batch['warnings'].append(f'출력판 {index + 1} · 출력 부품 사이에 간섭이 있습니다. 간격을 늘리세요.')
            check(); return design, result, batch['reports'][batch['selected']], None

    def switch_plate(self, *_):
        if self.running or self.checked_batch is None:
            self.preferred_part = None; self.schedule(); return
        self.placement_handle.drag = None; self.placement_handle.changed = False; self.preferred_part = None
        self.show_plate(self.plate_choice.currentData() or 0)

    def show_plate(self, index):
        batch = self.checked_batch
        if batch is None: return
        index = min(max(0, index), len(batch['plates']) - 1); batch['selected'] = index
        self.checked = batch['plates'][index]; self.result = dict(batch['results'][index]); self.result['_print_batch'] = batch
        self.interference = batch['reports'][index]; self.travel = None
        self.viewport.load(self.result, False); self.apply_button.setEnabled(True); self.present(); self.present_interference()

    def present(self):
        super().present(); batch = self.result['_print_batch']; self.checked_batch = batch
        self.warnings = list(dict.fromkeys(batch['warnings'])); index = batch['selected']; count = len(batch['plates'])
        old_part = self.preferred_part or self.active_part.currentData()
        for result in batch['results']:
            self.placements.update(deepcopy(result['print_placements'])); self.plate_assignments.update(result['print_plate_assignments'])
        with QSignalBlocker(self.plate_choice):
            self.plate_choice.clear()
            for i, plate in enumerate(batch['plates']): self.plate_choice.addItem(f'출력판 {i + 1} · {len(plate.parts)}개 부품', i)
            self.plate_choice.setCurrentIndex(index)
        with QSignalBlocker(self.active_part):
            self.active_part.clear()
            for part in batch['plates'][index].parts: self.active_part.addItem(part.name, part.id)
            self.active_part.setCurrentIndex(max(0, self.active_part.findData(old_part)))
        with QSignalBlocker(self.target_plate):
            self.target_plate.clear()
            for i in range(count): self.target_plate.addItem(f'출력판 {i + 1}', i)
            if count < sum(box.isChecked() for box in self.part_boxes.values()): self.target_plate.addItem('새 출력판', count)
        self.preferred_part = None; self.sync_pose()
        parts = sum(len(plate.parts) for plate in batch['plates']); selected = sum(box.isChecked() for box in self.part_boxes.values())
        self.batch_summary.setText(f'선택 {selected}개 · 출력 {parts}개 · 출력판 {count}개')
        excluded = self.result.get('print_excluded_details', [])
        if excluded:
            details = '\n'.join(f"{item.get('id', '')} · {item.get('reason', '')}" for item in excluded)
            self.batch_summary.setText(self.batch_summary.text() + f' · 볼트·너트 제외 {len(excluded)}개')
            self.batch_summary.setToolTip(details)
        else: self.batch_summary.setToolTip('')
        self.apply_button.setText('전체 출력판 STL · ZIP 저장' if count > 1 else '이 미리보기로 STL 저장')
        from vtkmodules.vtkFiltersSources import vtkCubeSource
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper, vtkActor
        if self.bed_actor: self.viewport.renderer.RemoveActor(self.bed_actor)
        bed = vtkCubeSource(); bed.SetXLength(self.bed[0].value()); bed.SetYLength(self.bed[1].value()); bed.SetZLength(.4); bed.SetCenter(0, 0, -.25)
        mapper = vtkPolyDataMapper(); mapper.SetInputConnection(bed.GetOutputPort()); actor = vtkActor(); actor.SetMapper(mapper)
        actor.GetProperty().SetColor(.25, .36, .4); actor.GetProperty().SetOpacity(.35); actor.GetProperty().EdgeVisibilityOn(); actor.PickableOff()
        self.bed_actor = actor; self.viewport.renderer.AddActor(actor); self.viewport.render()
        if not self.plate_view_initialized: self.plate_view_initialized = True; self.top_plate()
        self.status.setText(f'출력판 {index + 1}/{count} · ' + self.status.text() + ' · 바닥 Z=0 · 출력 영역 안에 배치됨')

    def present_interference(self):
        super().present_interference()
        if self.warnings:
            text = '\n'.join(self.warnings); self.status.setText(text); self.status.setToolTip(text)
            self.status.setStyleSheet('color:#ffab91;'); self.apply_button.setEnabled(False)
        self.current_stl_button.setEnabled(self.can_export(current_only=True))

    def accept(self):
        self.export_checked()

    def can_export(self, current_only=False):
        batch = self.checked_batch
        if batch is None or self.checked is None or self.running: return False
        indexes = [batch['selected']] if current_only else range(len(batch['plates']))
        return not (not current_only and self.warnings) and all(
            not batch['results'][index].get('print_warnings') and not batch['reports'][index]['blocked'] for index in indexes)

    def export_checked(self, current_only=False):
        if not self.can_export(current_only): return
        batch = self.checked_batch; index = batch['selected']; revision = self.revision
        multiple = not current_only and len(batch['plates']) > 1
        if current_only:
            title, default, extension, pattern = '현재 출력판 STL 저장', f'print-plate-{index + 1:03d}.stl', '.stl', 'STL (*.stl)'
        else:
            title, default, extension, pattern = ('출력판 STL 묶음 저장', 'print-plates.zip', '.zip', 'ZIP (*.zip)') if multiple else ('STL 저장', 'print.stl', '.stl', 'STL (*.stl)')
        path, _ = QFileDialog.getSaveFileName(self, title, default, pattern)
        if not path: return
        if not path.lower().endswith(extension): path += extension
        if batch is not self.checked_batch or revision != self.revision or not self.can_export(current_only): return
        if current_only and batch['selected'] != index: return
        selected_indexes = [index] if current_only else range(len(batch['plates']))
        plates = [batch['plates'][i].model_copy(deep=True) for i in selected_indexes]
        results = deepcopy(batch['results']); quality = self.quality.currentData(); cancelled = lambda: not self.alive or revision != self.revision
        self.running = True; self.controls.parentWidget().setEnabled(False); self.apply_button.setEnabled(False)
        self.current_stl_button.setEnabled(False); self.status.setText('STL 메시 생성 중…')
        def export():
            if multiple: return export_print_stls(plates, results, path, tolerance=quality, cancelled=cancelled)
            return export_print_stl(plates[0], path, tolerance=quality, cancelled=cancelled)
        self.worker = Worker(export)
        def done(target):
            self.running = False
            if not self.alive: return
            self.controls.parentWidget().setEnabled(True)
            if revision != self.revision: self.timer.start(); return
            self.status.setText('STL 저장 완료 · ' + str(path)); self.apply_button.setEnabled(self.can_export())
            self.current_stl_button.setEnabled(self.can_export(current_only=True))
        def failed(message):
            self.running = False
            if not self.alive: return
            self.controls.parentWidget().setEnabled(True)
            if revision != self.revision: self.timer.start(); return
            self.failed(message)
        self.worker.signals.done.connect(done); self.worker.signals.failed.connect(failed); QThreadPool.globalInstance().start(self.worker)
