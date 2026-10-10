"""Review generated firmware privately; only explicit save changes the project."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..electrical import ElectricalWorkspace
from .ai_task import AITask
from .codex_model_picker import CodexModelPicker
from .widgets import button, label


class FirmwareDialog(QDialog):
    """Generation, export and build use copied data and cancellable workers.

    ``accepted_workspace`` is populated exclusively by Save to project. Closing,
    exporting or checking a build never commits the draft or executes its code.
    A transport injection uses the same signature as generate_firmware.
    """

    def __init__(self, workspace, parent=None, language="ko", selected_component_id="",
                 codex_config=None, generation_transport=None):
        super().__init__(parent)
        self.language = language
        self.word = lambda ko, en: en if language == "en" else ko
        self.workspace = ElectricalWorkspace.model_validate(
            deepcopy(ElectricalWorkspace.model_validate(workspace).model_dump(mode="json")))
        self.accepted_workspace = None
        self.bundle = None
        self.build_report = None
        self.task = None
        self._closing = False
        self._action = ""
        self._editors = []
        self._loaded_bundle_id = None
        self._active_board_id = ""
        self._active_target = ""
        self._draft_cache = {}
        self._candidates = {}
        self._last_choice = {}
        self._deleted_bundle_ids = set()
        self._request_replace_id = None
        self._libraries = []
        self._new_libraries = {}
        self.codex_config = dict(codex_config or {})
        self.generation_transport = generation_transport
        from ..firmware_generation import firmware_targets
        self.targets = firmware_targets(self.workspace)
        self.setWindowTitle(self.word("Codex 펌웨어 생성 / 검토", "Codex firmware generation / review"))
        self.setObjectName("firmwareDialog2240")
        self.resize(1180, 800)
        root = QVBoxLayout(self)
        root.addWidget(label(self.word(
            "현재 등록한 보드와 배선에 맞춰 코드를 생성합니다. 저장 전 코드를 검토하세요. 전체 MCU·펌웨어 에뮬레이션과 실제 장치 동작 검증은 지원하지 않습니다.",
            "Generate code for the registered board and wiring. Review it before saving. Full MCU / firmware emulation and verification on real devices are not available.")))
        split = QSplitter(Qt.Orientation.Horizontal); root.addWidget(split, 1)
        settings = QWidget(); controls = QVBoxLayout(settings); form = QFormLayout(); controls.addLayout(form)
        self.board = QComboBox(); self.board.setObjectName("firmwareBoard")
        self.board.setMinimumContentsLength(12)
        self.board.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for item in self.targets:
            self.board.addItem(f"{item['name']} · {item['board_model']} [{item['component_id']}]", item["component_id"])
            self.board.setItemData(self.board.count() - 1, self.board.itemText(self.board.count() - 1), Qt.ItemDataRole.ToolTipRole)
        form.addRow(self.word("등록한 보드", "Registered board"), self.board)
        self.saved_bundles = QComboBox(); self.saved_bundles.setObjectName("firmwareSavedBundles")
        self.saved_bundles.setMinimumContentsLength(12)
        self.saved_bundles.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow(self.word("저장 코드 / 초안", "Saved code / drafts"), self.saved_bundles)
        self.delete_bundle_button = button(self.word("선택 코드 연결 해제", "Detach selected code"), self.delete_bundle)
        self.delete_bundle_button.setObjectName("firmwareDeleteBundle"); controls.addWidget(self.delete_bundle_button)
        self.target = QComboBox(); self.target.setObjectName("firmwareTarget")
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(12)
        form.addRow(self.word("코드 형식", "Code target"), self.target)
        self.models = CodexModelPicker(self); self.models.setObjectName("firmwareModel")
        self.models.set_catalog(self.codex_config.get("catalog", []), self.codex_config.get("model", ""))
        self.models.modelSelected.connect(self._select_model)
        form.addRow(self.word("Codex 모델", "Codex model"), self.models)
        self.effort = QComboBox(); self.effort.setObjectName("firmwareEffort")
        form.addRow(self.word("추론 수준", "Reasoning effort"), self.effort)
        self.effort.currentIndexChanged.connect(self._effort_selected)
        self._update_effort()
        self.connect_button = button(self.word("연결 / 모델 목록 새로고침…", "Connect / refresh models…"), self.connect_codex)
        self.connect_button.setObjectName("firmwareConnect"); controls.addWidget(self.connect_button)
        self.reference_summary = label(""); self.reference_summary.setObjectName("firmwareReferences")
        controls.addWidget(self.reference_summary)
        self._reference_status(False)
        controls.addWidget(label(self.word("원하는 동작과 입력 조건", "Desired behavior and input conditions")))
        self.operation = QPlainTextEdit(); self.operation.setObjectName("firmwareOperation")
        self.operation.setPlaceholderText(self.word(
            "예: 연결된 엔코더를 읽고 모터를 제어한다. 속도·정지 조건·핀의 기능을 알려주세요. 미정 값은 추정하지 않고 확인 항목으로 남깁니다.",
            "Example: read the wired encoder and control the motor. Describe speed, stop conditions and pin functions. Unknown values remain items to confirm."))
        controls.addWidget(self.operation, 1)
        self.generate_button = button(self.word("Codex로 코드 생성", "Generate with Codex"), self.generate, True)
        self.generate_button.setObjectName("firmwareGenerate"); controls.addWidget(self.generate_button)
        self.cancel_button = button(self.word("작업 취소 · 기존 초안 유지", "Cancel task · keep existing draft"), self.cancel_task)
        self.cancel_button.setObjectName("firmwareCancel"); self.cancel_button.hide(); controls.addWidget(self.cancel_button)
        self.status = label(""); self.status.setObjectName("firmwareStatus"); controls.addWidget(self.status)
        split.addWidget(settings)
        review = QWidget(); content = QVBoxLayout(review)
        self.tabs = QTabWidget(); content.addWidget(self.tabs, 1)
        source_panel = QWidget(); source_layout = QVBoxLayout(source_panel)
        self.files = QTabWidget(); self.files.setObjectName("firmwareFiles"); source_layout.addWidget(self.files, 1)
        source_actions = QGridLayout()
        self.add_file_button = button(self.word("파일 추가…", "Add file…"), self.add_file)
        self.remove_file_button = button(self.word("현재 파일 삭제", "Remove current file"), self.remove_file)
        source_actions.addWidget(self.add_file_button, 0, 0); source_actions.addWidget(self.remove_file_button, 0, 1)
        source_actions.addWidget(label(self.word("진입 파일", "Entrypoint")), 1, 0)
        self.entrypoint = QComboBox(); self.entrypoint.setObjectName("firmwareEntrypoint"); source_actions.addWidget(self.entrypoint, 1, 1)
        self.entrypoint.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.entrypoint.setMinimumContentsLength(10)
        source_layout.addLayout(source_actions); self.tabs.addTab(source_panel, self.word("코드 편집", "Source"))
        self.mapping = QTableWidget(0, 6); self.mapping.setObjectName("firmwarePinMapping")
        self.mapping.setHorizontalHeaderLabels([self.word("핀", "Pin"), self.word("기능", "Function"),
            self.word("노드", "Node"), self.word("연결 부품 / 단자", "Connected part / terminal"),
            self.word("용도", "Capabilities"), self.word("확인 사항", "Review")])
        self.mapping.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.mapping.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.mapping, self.word("핀 / 배선", "Pins / wiring"))
        libraries_panel = QWidget(); libraries_layout = QVBoxLayout(libraries_panel)
        libraries_layout.addWidget(label(self.word(
            "라이브러리 버전은 사용자가 확인한 고정 버전입니다. 폴더·ZIP의 텍스트 소스만 복사하며 설치·링크는 별도 확인이 필요합니다.",
            "Use an exact library version you have checked. Folder/ZIP text sources are copied; installation and target linking require separate verification."), muted=True))
        self.libraries_table = QTableWidget(0, 5); self.libraries_table.setObjectName("firmwareLibraries")
        self.libraries_table.setHorizontalHeaderLabels([self.word("이름", "Name"), self.word("고정 버전", "Pinned version"),
            self.word("원본", "Origin"), self.word("포함 / 제외 파일", "Included / omitted"), "SHA-256"])
        self.libraries_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.libraries_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.libraries_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.libraries_table.itemSelectionChanged.connect(self._library_selected)
        libraries_layout.addWidget(self.libraries_table)
        library_actions = QGridLayout()
        self.library_folder_button = button(self.word("폴더 가져오기…", "Import folder…"), lambda: self.import_library("directory"))
        self.library_zip_button = button(self.word("ZIP 가져오기…", "Import ZIP…"), lambda: self.import_library("zip"))
        self.library_dependency_button = button(self.word("의존성 추가…", "External dependency…"), self.add_dependency)
        self.library_remove_button = button(self.word("제거", "Remove"), self.remove_library)
        for index, item in enumerate((self.library_folder_button, self.library_zip_button, self.library_dependency_button, self.library_remove_button)):
            library_actions.addWidget(item, index // 2, index % 2)
        libraries_layout.addLayout(library_actions)
        self.library_files = QComboBox(); self.library_files.setObjectName("firmwareLibraryFiles")
        self.library_files.currentIndexChanged.connect(self._library_file_selected)
        libraries_layout.addWidget(self.library_files)
        self.library_source = QPlainTextEdit(); self.library_source.setReadOnly(True)
        self.library_source.setObjectName("firmwareLibrarySource"); libraries_layout.addWidget(self.library_source, 1)
        self.tabs.addTab(libraries_panel, self.word("라이브러리", "Libraries"))
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setObjectName("firmwareReview")
        self.tabs.addTab(self.details, self.word("검토 / 소스 검사", "Review / source check"))
        compiler_form = QFormLayout(); self.compiler = QLineEdit(); self.compiler.setObjectName("firmwareCompiler")
        self.compiler.setPlaceholderText(self.word("선택 사항 · 설치된 C/C++ 컴파일러 경로", "Optional · installed C/C++ compiler path"))
        compiler_form.addRow(self.word("소스 검사 도구", "Source-check tool"), self.compiler); content.addLayout(compiler_form)
        tools = QHBoxLayout()
        self.build_button = button(self.word("빌드 / 소스 확인", "Build / source check"), self.check_build)
        self.build_button.setObjectName("firmwareBuild")
        self.export_button = button(self.word("새 폴더로 내보내기…", "Export to new folder…"), self.export_bundle)
        self.export_button.setObjectName("firmwareExport")
        tools.addWidget(self.build_button); tools.addWidget(self.export_button); content.addLayout(tools)
        content.addWidget(label(self.word(
            "소스 검사는 코드 문법만 확인합니다. 보드 SDK·링커·실장 설정이 없는 경우 전체 대상 빌드는 미검증이며, 플래시·실행은 하지 않습니다.",
            "Source checks cover syntax only. Full target builds remain unverified without the board SDK, linker and hardware settings. Code is never flashed or executed."), muted=True))
        split.addWidget(review); split.setSizes([350, 800])
        box = QDialogButtonBox()
        self.save_button = box.addButton(self.word("코드 변경 전체 저장", "Save all code changes"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("firmwareSave")
        box.addButton(self.word("닫기 · 변경 취소", "Close · discard changes"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject); root.addWidget(box)
        for control in self.findChildren(type(self.generate_button)): control.setAutoDefault(False)
        self.board.currentIndexChanged.connect(self._board_changed)
        self.saved_bundles.currentIndexChanged.connect(self._bundle_changed)
        self.target.currentIndexChanged.connect(self._context_changed)
        self.entrypoint.currentIndexChanged.connect(self._source_edited)
        if selected_component_id and self.board.findData(selected_component_id) >= 0:
            self.board.setCurrentIndex(self.board.findData(selected_component_id))
        self._board_changed()

    def _select_model(self, model):
        self.codex_config["model"] = model
        self._update_effort()

    def _update_effort(self):
        from .codex_models import effort_label
        preferred = self.codex_config.get("effort") or "medium"
        model = next((item for item in self.models.catalog if item["model"] == self.codex_config.get("model")), None)
        available = model.get("efforts") if model else None
        self.effort.blockSignals(True); self.effort.clear()
        for value in available if available is not None else [preferred]:
            title = effort_label(value)
            if available is None: title += self.word(" · 연결 확인 전", " · connection not verified")
            self.effort.addItem(title, value)
        index = self.effort.findData(preferred)
        if index < 0: index = self.effort.findData("medium")
        self.effort.setCurrentIndex(index if index >= 0 else (0 if self.effort.count() else -1))
        self.effort.blockSignals(False); self._effort_selected()

    def _effort_selected(self):
        self.codex_config["effort"] = self.effort.currentData() or ""

    def connect_codex(self):
        if self.task: return
        from .codex_setup import CodexSetupDialog
        dialog = CodexSetupDialog(self)
        dialog.preferred = self.codex_config.get("model", "")
        if self.codex_config.get("executable"): dialog.path.setText(self.codex_config["executable"])
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.codex_config.update(model=dialog.model_name, executable=dialog.executable_path, catalog=dialog.catalog)
                self.models.set_catalog(dialog.catalog, dialog.model_name)
                self._update_effort()
                self._set_status(self.word("Codex 연결 확인 완료", "Codex connection verified"))
        finally: dialog.deleteLater()

    def _set_status(self, text, error=False):
        self.status.setText(str(text)[:2000])
        self.status.setStyleSheet("color:#f4a090" if error else "")

    def _reference_status(self, delivered):
        count = len(self.codex_config.get("references") or ())
        if delivered:
            text = self.word("첨부 참고자료 {count}개를 생성 요청에 전달했습니다.", "Sent {count} attached references with the generation request.")
        else:
            text = self.word("현재 첨부자료 {count}개 · 생성 요청에 함께 전달합니다.", "{count} references attached · included in the generation request.")
        self.reference_summary.setText(text.format(count=count))
        self.reference_summary.setToolTip(self.word("메인 창에 첨부한 GitHub·파일 자료입니다. 이 창은 저장소나 파일을 새로 조회하지 않습니다.",
            "References attached in the main window. This dialog does not fetch repositories or files."))

    def _board_changed(self):
        if self.task: return
        self._cache_active()
        board = next((item for item in self.targets if item["component_id"] == self.board.currentData()), None)
        self._active_board_id = self.board.currentData() or ""
        self.board.setToolTip(self.board.currentText())
        self.target.blockSignals(True); self.target.clear()
        if board:
            for target in board["targets"]: self.target.addItem(target, target)
        self.target.blockSignals(False)
        self._populate_bundles(self._last_choice.get(self._active_board_id))
        self._bundle_changed()
        if not board: self._set_status(self.word("CAD 부품에 대응하는 정확한 보드를 전장에 등록하세요.",
            "Register an exact programmable board linked to a CAD part in the electrical workbench."))

    def _cache_active(self):
        if not self._active_board_id: return
        if not self.bundle:
            self._new_libraries[self._active_board_id] = deepcopy(self._libraries)
            return
        key = (self._active_board_id, self.bundle.id)
        self._draft_cache[key] = dict(bundle=self.bundle.model_copy(deep=True),
            files=[(path, editor.toPlainText(), role) for path, editor, role in self._editors],
            entrypoint=self.entrypoint.currentData(), target=self._active_target, libraries=deepcopy(self._libraries))
        self._last_choice[self._active_board_id] = self.bundle.id

    def _cached_bundle(self, cache):
        from hashlib import sha256
        from ..firmware_bundle import FirmwareBundle
        raw = cache["bundle"].model_dump(mode="json")
        raw["files"] = [dict(path=path, content=source, role=role,
            sha256=sha256(source.encode("utf-8")).hexdigest()) for path, source, role in cache["files"]]
        raw["entrypoint"] = cache["entrypoint"] or ""
        raw["libraries"] = cache.get("libraries", [])
        return FirmwareBundle.model_validate(raw)

    def _cache_changed(self, cache):
        original = [(item.path, item.content, item.role) for item in cache["bundle"].files]
        return (cache["files"] != original or cache["entrypoint"] != cache["bundle"].entrypoint or
                cache.get("libraries", []) != cache["bundle"].libraries)

    def _available_bundles(self):
        rows = {item.id: item for item in getattr(self.workspace, "firmware_bundles", [])
                if item.binding.board_component_id == self._active_board_id and item.id not in self._deleted_bundle_ids}
        rows.update({item.id: item for item in self._candidates.values()
                     if item.binding.board_component_id == self._active_board_id and item.id not in self._deleted_bundle_ids})
        return list(rows.values())

    def _populate_bundles(self, preferred=None):
        self.saved_bundles.blockSignals(True); self.saved_bundles.clear()
        self.saved_bundles.addItem(self.word("새 코드 초안", "New code draft"), "")
        for item in self._available_bundles():
            suffix = self.word(" · 미저장 수정안", " · unsaved revision") if item.id in self._candidates else ""
            self.saved_bundles.addItem(item.name + suffix + " [" + item.id[-8:] + "]", item.id)
            self.saved_bundles.setItemData(self.saved_bundles.count() - 1, self.saved_bundles.itemText(self.saved_bundles.count() - 1), Qt.ItemDataRole.ToolTipRole)
        index = self.saved_bundles.findData(preferred)
        self.saved_bundles.setCurrentIndex(index if index >= 0 else self.saved_bundles.count() - 1)
        self.saved_bundles.blockSignals(False)
        self.saved_bundles.setToolTip(self.saved_bundles.currentText())

    def _bundle_changed(self):
        if self.task: return
        selected = self.saved_bundles.currentData()
        self.saved_bundles.setToolTip(self.saved_bundles.currentText())
        if self.bundle and self.bundle.binding.board_component_id == self._active_board_id: self._cache_active()
        self.bundle = next((item.model_copy(deep=True) for item in self._available_bundles() if item.id == selected), None)
        self.build_report = None; self._loaded_bundle_id = selected
        cache = self._draft_cache.get((self._active_board_id, selected))
        if cache: self.bundle = cache["bundle"].model_copy(deep=True)
        if self.bundle:
            self.target.blockSignals(True)
            self.target.setCurrentIndex(self.target.findData(cache["target"] if cache else self.bundle.target))
            self.target.blockSignals(False)
            generation = getattr(self.bundle, "generation", None)
            if generation and not self.operation.toPlainText().strip(): self.operation.setPlainText(generation.request)
        self._active_target = self.target.currentData() or ""
        self._last_choice[self._active_board_id] = selected or ""
        self._show_bundle()
        if cache:
            for _, editor, _ in self._editors: editor.deleteLater()
            self._editors = []; self.files.clear(); self.entrypoint.clear()
            for path, source, role in cache["files"]: self._insert_file(path, source, role)
            self.entrypoint.setCurrentIndex(self.entrypoint.findData(cache["entrypoint"]))
        self._context_changed(); self._controls(False)

    def delete_bundle(self):
        if self.task or not self.bundle: return
        identifier = self.bundle.id
        if identifier in self._candidates: self._candidates.pop(identifier)
        if any(item.id == identifier for item in getattr(self.workspace, "firmware_bundles", [])):
            self._deleted_bundle_ids.add(identifier)
        self._draft_cache.pop((self._active_board_id, identifier), None)
        self.bundle = None; self._populate_bundles(); self._bundle_changed()
        self._set_status(self.word("코드 연결 해제는 프로젝트에 저장한 뒤 반영됩니다.", "Code is detached only after saving to the project."))

    def _context_changed(self):
        from ..firmware_generation import build_context
        self.mapping.setRowCount(0)
        self._active_target = self.target.currentData() or ""
        if not self.board.currentData(): self.details.setPlainText(""); return
        try:
            context = build_context(self.workspace, self.board.currentData(), target=self.target.currentData())
            for item in context["pins"]:
                row = self.mapping.rowCount(); self.mapping.insertRow(row)
                connections = "; ".join(f"{end['name']} [{end['component_id']}] / {end['terminal']}" for end in item.get("connected_endpoints", []))
                values = (item.get("pin", ""), item.get("label", ""), item.get("node", ""), connections,
                          ", ".join(item.get("functions", [])), item.get("signal_note", ""))
                for col, value in enumerate(values): self.mapping.setItem(row, col, QTableWidgetItem(str(value or "")))
            self.mapping.resizeColumnsToContents()
            self._context = context; self._review()
        except Exception as exc: self._set_status(str(exc), True)

    def _review(self, extra=""):
        from ..firmware_bundle import verify_bundle_binding
        context = getattr(self, "_context", {})
        text = self.word("미정 값 / 필요한 확인", "Unknown values / required confirmations") + "\n"
        text += "\n".join(context.get("missing_parameters", [])) or self.word("등록된 배선 기준 추가 확인 항목 없음", "No additional item from the registered wiring")
        if self.bundle:
            report = verify_bundle_binding(self.bundle, self.workspace)
            text += "\n\n" + self.word("코드와 현재 배선 연결", "Code / current wiring binding") + ": " + report.status
            text += "\n" + "\n".join(issue.message for issue in report.issues)
            text += "\n\n" + self.bundle.notes + "\n" + "\n".join(self.bundle.missing_parameters)
            generation = getattr(self.bundle, "generation", None)
            if generation:
                text += "\n\n" + self.word("생성 기록", "Generation record") + ": " + generation.model
                text += " / " + str(generation.created_utc) + "\n" + generation.request
                text += "\n" + self.word("위 생성 기록 이후 미리보기에서 수동 편집할 수 있습니다.", "The preview can be manually edited after this recorded generation.")
        if extra: text += "\n\n" + str(extra)
        self.details.setPlainText(text)

    def _show_bundle(self):
        for _, editor, _ in self._editors: editor.deleteLater()
        self._editors = []; self.files.clear(); self.entrypoint.clear()
        self._libraries = deepcopy(self.bundle.libraries if self.bundle else self._new_libraries.get(self._active_board_id, []))
        cache = self._draft_cache.get((self._active_board_id, self.bundle.id)) if self.bundle else None
        if cache: self._libraries = deepcopy(cache.get("libraries", self._libraries))
        self._show_libraries()
        if not self.bundle: return
        for item in self.bundle.files: self._insert_file(item.path, item.content, item.role)
        index = self.entrypoint.findData(self.bundle.entrypoint)
        if index >= 0: self.entrypoint.setCurrentIndex(index)

    def _insert_file(self, path, content, role="source"):
        editor = QPlainTextEdit(); editor.setPlainText(content)
        editor.setObjectName("firmwareSource_" + str(len(self._editors)))
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.textChanged.connect(self._source_edited)
        self._editors.append((path, editor, role)); self.files.addTab(editor, path)
        if role == "source": self.entrypoint.addItem(path, path)

    def _show_libraries(self):
        self.libraries_table.setRowCount(0)
        for library in self._libraries:
            row = self.libraries_table.rowCount(); self.libraries_table.insertRow(row)
            values = (library.name, library.version, library.origin,
                f"{len(library.files)} / {len(library.omitted_files)}", library.source_sha256 or
                self.word("미설치 · 미검증", "Not installed / unverified"))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(value)
                self.libraries_table.setItem(row, col, item)
        self.libraries_table.resizeColumnsToContents()
        if self._libraries: self.libraries_table.selectRow(len(self._libraries) - 1)
        else: self._library_selected()

    def _library_selected(self):
        self.library_files.clear(); self.library_source.clear()
        row = self.libraries_table.currentRow()
        if row < 0 or row >= len(self._libraries): return
        library = self._libraries[row]
        for file in library.files: self.library_files.addItem(library.prefix + '/' + file.path, file.path)
        self.library_files.setToolTip(self.word("제외 파일: ", "Omitted files: ") + ', '.join(library.omitted_files))
        self._library_file_selected()

    def _library_file_selected(self):
        row = self.libraries_table.currentRow()
        library = self._libraries[row] if 0 <= row < len(self._libraries) else None
        file = next((item for item in library.files if item.path == self.library_files.currentData()), None) if library else None
        self.library_source.setPlainText(file.content if file else self.word(
            "외부 의존성은 고정 버전 메타데이터만 기록합니다. 대상 환경에서 설치·링크 여부를 확인하세요.",
            "External dependencies record pinned metadata only. Verify installation and linkage in the target environment.") if library else "")

    def _library_ecosystem(self):
        return {'raspberry_python': 'python', 'arduino': 'arduino', 'stm32_hal': 'c_cpp'}.get(self.target.currentData(), 'c_cpp')

    def add_library(self, library):
        from ..firmware_bundle import FirmwareLibrary
        library = FirmwareLibrary.model_validate(library.model_dump() if isinstance(library, FirmwareLibrary) else library)
        if len(self._libraries) >= 8 or any(item.id == library.id for item in self._libraries):
            raise ValueError(self.word("최대 8개이며 라이브러리 이름은 중복할 수 없습니다. 기존 항목을 제거한 뒤 다시 가져오세요.",
                "Select at most 8 unique library names. Remove an existing item before replacing it."))
        self._libraries.append(library); self._show_libraries(); self._source_edited()

    def import_library(self, origin, path=None, *, name=None, version=None):
        if self.task: return
        if path is None:
            path = (QFileDialog.getExistingDirectory(self, self.word("라이브러리 소스 폴더", "Library source folder"))
                    if origin == 'directory' else QFileDialog.getOpenFileName(self,
                    self.word("라이브러리 ZIP", "Library ZIP"), '', 'ZIP (*.zip)')[0])
            if not path: return
        if name is None:
            name, ok = QInputDialog.getText(self, self.word("라이브러리 이름", "Library name"),
                self.word("패키지 / 라이브러리 이름", "Package / library name"), text=Path(path).stem)
            if not ok: return
        if version is None:
            version, ok = QInputDialog.getText(self, self.word("고정 버전", "Pinned version"),
                self.word("확인한 정확한 버전 또는 불변 리비전 (예: 1.2.3)", "Checked exact version or immutable revision (e.g. 1.2.3)"))
            if not ok: return
        from ..firmware_libraries import import_library_directory, import_library_zip, pinned_dependency
        try:
            metadata = pinned_dependency(name, version, self._library_ecosystem())
            if len(self._libraries) >= 8: raise ValueError('Select at most 8 libraries.')
            if any(item.id == metadata.id for item in self._libraries):
                raise ValueError('Remove the existing library before importing its replacement.')
            function = import_library_directory if origin == 'directory' else import_library_zip
            ecosystem = self._library_ecosystem()
            self._start('library', lambda control, progress: function(path, name=name, version=version,
                ecosystem=ecosystem, cancelled=control.cancelled.is_set))
        except Exception as exc: self._set_status(str(exc), True)

    def add_dependency(self):
        if self.task: return
        name, ok = QInputDialog.getText(self, self.word("외부 의존성", "External dependency"), self.word("패키지 이름", "Package name"))
        if not ok: return
        version, ok = QInputDialog.getText(self, self.word("고정 버전", "Pinned version"), self.word("정확한 버전", "Exact version"))
        if not ok: return
        modules = []
        if self._library_ecosystem() == 'python':
            value, ok = QInputDialog.getText(self, self.word("Python 가져오기 이름", "Python import names"),
                self.word("쉼표로 구분한 모듈명 (예: RPi.GPIO)", "Comma-separated module names (e.g. RPi.GPIO)"), text=name.replace('-', '_'))
            if not ok: return
            modules = [item.strip() for item in value.split(',') if item.strip()]
        from ..firmware_libraries import pinned_dependency
        try:
            self.add_library(pinned_dependency(name, version, self._library_ecosystem(), module_names=modules))
            self._set_status(self.word("고정 의존성을 기록했습니다. 실제 설치·링크는 미검증입니다.", "Pinned dependency recorded. Installation and linking are unverified."))
        except Exception as exc: self._set_status(str(exc), True)

    def remove_library(self):
        if self.task: return
        row = self.libraries_table.currentRow()
        if 0 <= row < len(self._libraries):
            self._libraries.pop(row); self._show_libraries(); self._source_edited()

    def add_file(self):
        if not self.bundle or self.task: return
        path, ok = QInputDialog.getText(self, self.word("새 코드 파일", "New source file"), self.word("상대 경로 / 파일명", "Relative path / filename"))
        if not ok or not path: return
        if any(item[0].casefold() == path.casefold() for item in self._editors): self._set_status(self.word("같은 파일명이 있습니다.", "This filename already exists."), True); return
        suffix = Path(path).suffix.casefold()
        role = "documentation" if suffix in (".md", ".txt") else "configuration" if suffix == ".json" else "source"
        self._insert_file(path, "{}\n" if role == "configuration" else "", role)
        self.files.setCurrentIndex(self.files.count() - 1)

    def remove_file(self):
        index = self.files.currentIndex()
        if self.task or index < 0: return
        path, editor, _ = self._editors.pop(index); self.files.removeTab(index); editor.deleteLater()
        entry = self.entrypoint.findData(path)
        if entry >= 0: self.entrypoint.removeItem(entry)
        self._source_edited()

    def _source_edited(self):
        if self.build_report is not None and not self.task:
            self.build_report = None
            self._set_status(self.word("코드가 바뀌었습니다. 현재 소스를 다시 점검하세요.", "The code changed. Check the current source again."))
            self._review()

    def _current_bundle(self, allow_stale=False):
        from ..firmware_bundle import FirmwareBundle, create_bundle, verify_bundle_binding
        if not self.bundle: raise ValueError(self.word("먼저 코드를 생성하세요.", "Generate code first."))
        if allow_stale:
            from hashlib import sha256
            raw = self.bundle.model_dump(mode="json")
            raw["files"] = [dict(path=path, content=editor.toPlainText(), role=role,
                sha256=sha256(editor.toPlainText().encode("utf-8")).hexdigest()) for path, editor, role in self._editors]
            raw["entrypoint"] = self.entrypoint.currentData() or ""
            raw["libraries"] = [item.model_dump(mode="json") for item in self._libraries]
            # Keep the old fingerprint explicitly stale: regeneration may read
            # old sources as context but must bind its new result independently.
            return FirmwareBundle.model_validate(raw)
        binding = verify_bundle_binding(self.bundle, self.workspace)
        if binding.status != "current":
            raise ValueError(self.word("보드 또는 배선이 바뀌었습니다. 현재 배선으로 다시 생성하세요.", "The board or wiring changed. Regenerate for the current wiring."))
        if self.bundle.target != self.target.currentData():
            raise ValueError(self.word("코드 형식이 바뀌었습니다. 다시 생성하세요.", "The code target changed. Regenerate the code."))
        updated = create_bundle(self.bundle.name, self.bundle.target, self.workspace,
            self.board.currentData(), [dict(path=path, content=editor.toPlainText(), role=role)
            for path, editor, role in self._editors], self.entrypoint.currentData() or "",
            notes=self.bundle.notes, missing_parameters=self.bundle.missing_parameters,
            pin_bindings=[item.model_dump(mode="json") for item in self.bundle.pin_bindings], generation=self.bundle.generation,
            libraries=self._libraries)
        return updated.model_copy(update={"id": self.bundle.id})

    def _controls(self, running):
        for item in (self.board, self.saved_bundles, self.target, self.models, self.effort, self.connect_button, self.operation, self.compiler): item.setEnabled(not running)
        for _, editor, _ in self._editors: editor.setReadOnly(running)
        self.generate_button.setEnabled(not running and bool(self.board.currentData()))
        self.generate_button.setText(self.word("선택 코드 수정안 생성", "Generate revision for selected code") if self.bundle
                                     else self.word("Codex로 새 코드 생성", "Generate new code with Codex"))
        for item in (self.add_file_button, self.remove_file_button, self.entrypoint, self.build_button, self.export_button, self.delete_bundle_button):
            item.setEnabled(not running and bool(self.bundle))
        queued = bool(self._candidates or self._deleted_bundle_ids or any(self._cache_changed(cache)
            for (_, identifier), cache in self._draft_cache.items() if identifier not in self._deleted_bundle_ids))
        self.save_button.setEnabled(not running and bool(self.bundle or queued))
        self.cancel_button.setVisible(running)
        for item in (self.library_folder_button, self.library_zip_button, self.library_dependency_button,
                     self.library_remove_button, self.libraries_table, self.library_files):
            item.setEnabled(not running and bool(self.board.currentData()))

    def _start(self, action, fn):
        if self.task or self._closing: return
        self._action = action; self._controls(True)
        self.task = AITask(fn, self)
        self.task.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self.task.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self.task.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self.task.start()

    def generate(self):
        if self.task: return
        operation = self.operation.toPlainText().strip(); model = self.codex_config.get("model", "")
        if not operation or not model:
            self._set_status(self.word("원하는 동작을 입력하고 실제 Codex 모델을 선택하세요.", "Describe the desired behavior and select an actual Codex model."), True); return
        if not self.effort.currentData():
            self._set_status(self.word("이 모델의 지원 추론 수준을 연결 창에서 새로 확인하세요.", "Refresh this model's supported reasoning efforts in the connection dialog."), True); return
        from ..firmware_generation import generate_firmware
        generate = self.generation_transport or generate_firmware
        try: existing = self._current_bundle(allow_stale=True) if self.bundle and self.bundle.target == self.target.currentData() else None
        except Exception as exc: self._set_status(str(exc), True); return
        workspace = self.workspace.model_copy(deep=True); board = self.board.currentData(); target = self.target.currentData()
        config = dict(self.codex_config)
        self._request_replace_id = self.bundle.id if self.bundle else None
        self._reference_status(False)
        self._set_status(self.word("Codex 코드 생성 중 · 통신이 끊기면 재연결을 기다립니다.", "Generating with Codex · waiting for reconnection if communication is interrupted."))
        self._start("generate", lambda control, progress: generate(workspace, board, operation, model,
            target=target, executable=config.get("executable", ""), effort=config.get("effort", "medium"),
            control=control, progress=progress, deadline=config.get("deadline", 600), existing_bundle=existing,
            references=deepcopy(config.get("references") or ()), libraries=deepcopy(self._libraries)))

    def check_build(self):
        if self.task: return
        try: bundle = self._current_bundle()
        except Exception as exc: self._set_status(str(exc), True); return
        from ..firmware_build import check_firmware_bundle
        workspace = self.workspace.model_copy(deep=True); compiler = self.compiler.text().strip() or None
        self._set_status(self.word("소스 검사 중…", "Checking source…"))
        def build(control, progress):
            from ..firmware_generation import audit_bundle_sources
            audit_bundle_sources(bundle, workspace, check=control.check)
            return check_firmware_bundle(bundle, workspace=workspace, compiler_path=compiler, cancelled=control.cancelled.is_set)
        self._start("build", build)

    def export_bundle(self, destination=None):
        if self.task: return
        try: bundle = self._current_bundle()
        except Exception as exc: self._set_status(str(exc), True); return
        if isinstance(destination, bool): destination = None  # QPushButton.clicked
        if destination is None:
            parent = QFileDialog.getExistingDirectory(self, self.word("내보낼 상위 폴더", "Export parent folder"))
            if not parent: return
            name, ok = QInputDialog.getText(self, self.word("새 폴더명", "New folder name"),
                self.word("기존 폴더는 덮어쓰지 않습니다.", "Existing folders are not overwritten."), text="firmware")
            if not ok or not name: return
            if name in (".", "..") or Path(name).name != name or "/" in name or "\\" in name:
                self._set_status(self.word("새 폴더명만 입력하세요.", "Enter a new folder name only."), True); return
            destination = Path(parent) / name
        from ..firmware_bundle import export_bundle_atomic
        path = Path(destination); workspace = self.workspace.model_copy(deep=True)
        self._set_status(self.word("새 폴더로 내보내는 중…", "Exporting to a new folder…"))
        def export(control, progress):
            from ..firmware_generation import audit_bundle_sources
            audit_bundle_sources(bundle, workspace, check=control.check)
            return export_bundle_atomic(bundle, path, cancelled=control.cancelled.is_set)
        self._start("export", export)

    def _progress(self, payload):
        task, message = payload
        if task is self.task and not self._closing: self._set_status(message)

    def _complete(self, payload):
        task, result = payload
        if task is not self.task or self._closing: return
        action = self._action; self.task = None
        if action == "generate":
            self._reference_status(True)
            if result.bundle is not None:
                self._cache_active()
                self.bundle = result.bundle.model_copy(deep=True); self._loaded_bundle_id = None
                if self._request_replace_id:
                    self.bundle = self.bundle.model_copy(update={"id": self._request_replace_id})
                    self._draft_cache.pop((self._active_board_id, self._request_replace_id), None)
                self._candidates[self.bundle.id] = self.bundle.model_copy(deep=True)
                self._populate_bundles(self.bundle.id)
                self.build_report = None; self._show_bundle()
            self._set_status(result.message or self.word("코드 초안 준비 완료 · 검토 후 저장하세요.", "Code draft ready · review it before saving."))
            self._review("\n".join(result.pending_checks))
        elif action == "library":
            self.add_library(result)
            self._set_status(self.word("라이브러리 소스를 가져왔습니다. 포함·제외 파일을 확인하세요.", "Library source imported. Review included and omitted files."))
        elif action == "build":
            self.build_report = result
            titles = {"syntax_ok": self.word("문법 확인 완료 · 실물 검증 필요", "Syntax checked · hardware validation required"),
                "pending": self.word("확인할 SDK·설정·조건이 남아 있습니다", "SDK, configuration or operating conditions remain unverified"),
                "failed": self.word("소스 오류 · 수정 후 다시 확인하세요", "Source errors · revise and check again"),
                "cancelled": self.word("점검 취소됨", "Check cancelled")}
            self._set_status(titles[result.status])
            rows = [result.scope]
            rows += [f"{item.name}: {item.status} · {item.message}" for item in result.checks]
            rows += [f"{item.severity} · {item.path}" + (f":{item.line}" if item.line else "") + ": " + item.message
                     for item in result.diagnostics]
            self._review("\n\n".join(rows))
            self.tabs.setCurrentWidget(self.details)
        elif action == "save":
            self.accepted_workspace, self.bundle = result
            super().accept()
            return
        else: self._set_status(self.word("새 폴더에 내보냈습니다: ", "Exported to a new folder: ") + str(result))
        self._controls(False)

    def _failed(self, payload):
        task, message = payload
        if task is not self.task or self._closing: return
        self.task = None; self._controls(False); self._set_status(message, True)

    def cancel_task(self):
        if self.task:
            self.task.cancel(); self.task = None
            if not self._closing:
                self._controls(False); self._set_status(self.word("작업 취소됨 · 기존 프로젝트와 초안은 유지됩니다.", "Task cancelled · the project and existing draft are preserved."))

    def accept(self):
        if self.task: return
        try:
            raw = self.workspace.model_dump(mode="json")
            rows = list(raw.get("firmware_bundles", []))
            rows = [item for item in rows if item["id"] not in self._deleted_bundle_ids]
            bundle = self._current_bundle() if self.bundle else None
            self._cache_active()
            updates = dict(self._candidates)
            from ..firmware_bundle import verify_bundle_binding
            for (_, identifier), cache in self._draft_cache.items():
                if identifier not in self._deleted_bundle_ids and (identifier in updates or self._cache_changed(cache)):
                    updates[identifier] = self._cached_bundle(cache)
            if bundle: updates[bundle.id] = bundle
            if not updates and not self._deleted_bundle_ids: raise ValueError(self.word("저장할 코드 변경이 없습니다.", "There are no code changes to save."))
            for identifier, candidate in updates.items():
                if verify_bundle_binding(candidate, self.workspace).status != "current":
                    raise ValueError(self.word("편집한 코드 중 현재 배선과 다른 코드가 있습니다. 해당 보드에서 다시 생성하거나 연결을 해제하세요.",
                        "An edited code draft has stale wiring. Regenerate it on its board or detach it before saving."))
                index = next((i for i, item in enumerate(rows) if item["id"] == identifier), -1)
                if index >= 0: rows[index] = candidate.model_dump(mode="json")
                else: rows.append(candidate.model_dump(mode="json"))
            raw["firmware_bundles"] = rows
            accepted = ElectricalWorkspace.model_validate(raw)
        except Exception as exc: self._set_status(str(exc), True); return
        workspace = self.workspace.model_copy(deep=True); candidates = tuple(updates.values())
        def audit(control, progress):
            from ..firmware_generation import audit_bundle_sources
            for candidate in candidates:
                control.check(); audit_bundle_sources(candidate, workspace, check=control.check)
            control.check()
            return accepted, bundle
        self._set_status(self.word("수동 편집과 실제 핀 연결을 확인한 뒤 저장합니다…", "Checking manual edits and actual pin mappings before saving…"))
        self._start("save", audit)

    def done(self, result):
        self._closing = True; self.cancel_task()
        if result != QDialog.DialogCode.Accepted: self.accepted_workspace = None
        super().done(result)
