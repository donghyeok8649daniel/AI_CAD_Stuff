"""Qt Widgets workbench: manual modeling, timeline, assembly and optional AI."""
from copy import deepcopy
from ..assembly_motion import prune_joint_references
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt,QTimer,QThreadPool,QSize,Slot,QSignalBlocker
from PySide6.QtGui import QAction,QActionGroup,QKeySequence,QColor,QIcon
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QDockWidget,QTreeWidget,QTreeWidgetItem,QTreeWidgetItemIterator,QListWidget,QListWidgetItem,QAbstractItemView,QStackedWidget,QScrollArea,QToolBar,QToolButton,QMenu,QLineEdit,QComboBox,QCheckBox,QPlainTextEdit,QFileDialog,QMessageBox,QDialog,QDialogButtonBox,QColorDialog,QProgressBar,QLabel,QSplitter,QInputDialog,QLayout)
from .document import Document,read_project
from .widgets import icon,number,label,button,clear_layout,Worker
from .viewport import CADViewport
from .sketch import SketchEditor,combo
from .geometry import uid
from ..parameters import parameter_values,binding_for,set_binding,remove_bindings
from .parameters import ExpressionField
from ..models import Design,Part,Project,DraftRequest
from ..catalog import TITLES,FIELDS,EXAMPLES,preset,part_default
from ..kernel import preview,export,KERNEL_LOCK
from ..constraints import anchors
from ..native_export import conversion_package
from .. import __version__
from .part_ui import PartSelectionUI

APP_NAME='Prompt CAD Studio'
DATA_DIR=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(os.getenv('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PromptCADStudio')))
ROOT=Path(__file__).resolve().parents[2]

class MainWindow(QMainWindow,PartSelectionUI):
    def __init__(self,restore=False):
        super().__init__();self.setObjectName('nativeCADMainWindow');self.resize(1500,920);self.setMinimumSize(820,560)
        self.selected_joint=None;self.selected_feature=None
        self.document=Document();self.result=None;self.selected=None;self.selected_parts=[];self.selected_sketch=None;self.selected_profile=None;self.busy=False;self.worker=None;self.sketching=False;self.joint_picks=None;self.last_draft=None;self.ai_task=None;self.ai_stage='';self.ai_started=0;self.data_dir=DATA_DIR;self.data_dir.mkdir(parents=True,exist_ok=True);self.autosave=self.data_dir/'native-autosave.cad.json';self.operation_serial=0
        from .i18n import install_language
        self.language_service=install_language(self.data_dir/'ui-settings.json')
        from .notifications import CompletionNotifier
        self.completion_notifier=CompletionNotifier(self)
        self.stack=QStackedWidget();self.setCentralWidget(self.stack);self.viewport=CADViewport();self.editor=SketchEditor();self.stack.addWidget(self.viewport);self.stack.addWidget(self.editor);self.viewport.part_selected.connect(self.select_part);self.viewport.face_selected.connect(self.face_selected);self.viewport.message.connect(self.message);self.editor.apply_requested.connect(self.apply_sketch);self.editor.finished_requested.connect(self.finish_sketch);self.viewport.sketch_selected.connect(self.select_sketch);self.viewport.profile_selected.connect(self.select_profile_3d);self.editor.cancelled.connect(self.cancel_sketch)
        self.actions={};brand=QLabel('PROMPT  /  CAD');brand.setStyleSheet('color:#76d5c2;font-size:11px;font-weight:600;padding:0 14px;');self.menuBar().setCornerWidget(brand,Qt.Corner.TopRightCorner);self.make_menus();self.make_toolbar();self.make_browser();self.make_properties();self.make_timeline();self.make_ai()
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setFixedWidth(140);self.progress.setMaximumHeight(12);self.progress.hide();self.statusBar().addPermanentWidget(self.progress);self.statusBar().addPermanentWidget(QLabel(f'  mm  ·  NATIVE {__version__}  '));self.message('새 스케치에서 시작하거나 부품을 추가하세요.');self.rebuild_tree();self.show_properties();self.title()
        self.ai_timer=QTimer(self);self.ai_timer.setInterval(500);self.ai_timer.timeout.connect(self.ai_tick)
        self.ai_status_button=button('AI 생성 취소',self.cancel_ai);self.ai_status_button.hide();self.statusBar().addPermanentWidget(self.ai_status_button)
        if os.getenv('CADSTUDIO_RENDERER')=='software':
            self.graphics_status=button('소프트웨어 3D · 안정 모드',self.graphics_diagnostics)
            self.graphics_status.setToolTip('그래픽 드라이버 초기화에 실패해 CPU 렌더링을 사용합니다. 큰 조립품은 표시가 느려질 수 있습니다.')
            self.statusBar().addPermanentWidget(self.graphics_status)
        from .shortcuts import ShortcutRouter
        self.shortcut_router=ShortcutRouter(self)
        self.provider.setCurrentIndex(self.provider.findData('codex' if self.codex_config['model'] else 'ollama'));self.ai_dock.show();self.ai_dock.raise_()
        if restore and self.autosave.exists():QTimer.singleShot(120,lambda:self.open_project(self.autosave,recovery=True))
    def action(self,key,title,fn,shortcut=None,ico=None):
        a=QAction(icon(ico),title,self) if ico else QAction(title,self);a.triggered.connect(fn)
        if shortcut:a.setShortcut(QKeySequence(shortcut))
        self.actions[key]=a;return a
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'timeline_dock') or self.sketching:return
        if self.height()<680 and self.timeline_dock.isVisible():
            self._compact_history=True;self.timeline_dock.hide()
        elif self.height()>=680 and getattr(self,'_compact_history',False):
            self._compact_history=False;self.timeline_dock.show()
    def make_menus(self):
        file=self.menuBar().addMenu('파일(&F)');file.addAction(self.action('new','새 설계',self.new_document,'Ctrl+N','file'));file.addAction(self.action('open','열기…',lambda:self.open_project(),'Ctrl+O','open'));file.addAction(self.action('save','저장',self.save,'Ctrl+S','save'));file.addAction(self.action('save_as','다른 이름으로 저장…',lambda:self.save(True),'Ctrl+Shift+S'));file.addSeparator()
        file.addAction(self.action('recover','최근 자동저장 복구…',self.recover_autosave,None,'history'))
        file.addAction(self.action('references','연구 저장소 · AI 참고자료…',self.reference_dialog))
        export_menu=file.addMenu('내보내기')
        export_menu.addAction(self.action('research_package','피로시험 조건 / 데이터 양식…',self.research_package_dialog))
        file.addAction(self.action('import_model','CAD 부품 가져오기 · STEP / IGES / STL…',self.import_model,'Ctrl+Shift+I','open'))
        for fmt,title in [('step','STEP · CAD 교환'),('stl','STL · 메시'),('f3d','F3D · Fusion 변환'),('ipt','IPT · Inventor 부품 변환'),('zip','Fusion / Inventor 변환 패키지')]:export_menu.addAction(title,lambda f=fmt:self.export_file(f))
        examples=file.addMenu('예제 열기')
        for name,path in [('면 스케치 · 구속 · 전체 기록','analytic_history.cad.json'),('스케치 피처 기록','feature_history.cad.json')]:
            if (ROOT/'examples'/path).exists():examples.addAction(name,lambda p=path:self.open_project(ROOT/'examples'/p))
        examples.addAction('2링크 조립',lambda:self.add_preset('robot_arm'));file.addSeparator();file.addAction('종료',self.close)
        edit=self.menuBar().addMenu('편집(&E)');edit.addAction(self.action('undo','실행 취소',self.undo,'Ctrl+Z','undo'));edit.addAction(self.action('redo','다시 실행',self.redo,'Ctrl+Y','redo'));edit.addAction(self.action('delete','선택 부품 삭제',self.delete_part,None,'delete'))
        model=self.menuBar().addMenu('모델링(&M)');model.addAction(self.action('sketch','새 스케치 · XY',lambda:self.start_sketch('XY'),None,'sketch'));model.addAction(self.action('face_sketch','면 스케치',self.start_face_sketch,None,'sketch'));model.addAction(self.action('edit_sketch','스케치 편집 · Shift+E',self.edit_sketch,None,'sketch'));model.addSeparator()
        model.addAction(self.action('work_plane','작업 평면 · 오프셋 / 기울기…',self.work_plane_dialog,None,'origin'))
        for kind,title in TITLES.items():
            if kind not in ('sweep','loft','revolve','imported','sheetmetal'):model.addAction(title,lambda k=kind:self.add_preset(k))
        model.addSeparator();model.addAction(self.action('sweep','스윕 편집…',lambda:self.modelling_dialog('sweep'),None,'extrude'));model.addAction(self.action('loft','로프트 편집…',lambda:self.modelling_dialog('loft'),None,'extrude'));model.addAction(self.action('surface','곡면 만들기…',lambda:self.modelling_dialog('loft',surface=True),None,'sketch'));model.addAction(self.action('edge_finish','3D 필렛 / 모따기…',self.edge_finish_dialog,None,'extrude'))
        model.addAction(self.action('extrude','3D 돌출 / 깊이 편집 · E',self.extrude_dialog,None,'extrude'));edit.addAction(self.action('parameters','변수 / 연결 치수 · U',self.parameter_dialog,None,'dimension'))
        assembly=self.menuBar().addMenu('조립(&A)');assembly.addAction(self.action('joint_hardware','실제 관절 구조…',self.joint_hardware_dialog,None,'assembly'));assembly.addAction(self.action('face_joint','면으로 조인트',self.start_face_joint,None,'assembly'));self.actions['face_joint'].setCheckable(True);assembly.addAction(self.action('drive','관절 구동',self.drive_joints,None,'origin'));assembly.addAction(self.action('robot','로봇 치수',self.robot_dialog,None,'assembly'));assembly.addAction(self.action('mate','기준점으로 연결…',self.mate_dialog,None,'assembly'));model.addAction(self.action('specimen','시편 설계',self.specimen_dialog,None,'specimen'))
        assembly.addAction(self.action('loop','폐루프 연결…',self.closure_dialog,None,'assembly'));assembly.addAction(self.action('four_bar','4절 링크 추가',self.add_four_bar,None,'assembly'))
        model.addAction(self.action('hole','구멍 뚫기…',self.hole_dialog,None,'cut'));model.addAction(self.action('measure','길이 측정…',self.measure_dialog,None,'dimension'))
        model.addAction(self.action('thread','나사산 · 수나사 / 암나사 · T',self.thread_dialog,None,'thread'))
        model.addAction(self.action('revolve','스케치 회전 · Revolve…',self.revolve_dialog,None,'extrude'))
        model.addAction(self.action('solid_tools','셸 / 구배 / 몸체 연산 / 패턴…',self.solid_dialog,None,'extrude'))
        model.addAction(self.action('sheetmetal','판금 · 단일 절곡 / 전개…',self.sheetmetal_dialog,None,'extrude'))
        model.addAction(self.action('feature_manager','피처 순서 / 삽입 / 억제…',self.feature_manager,None,'history'))
        assembly.addAction(self.action('gears','실제 스퍼 기어 구동…',self.gear_dialog,None,'assembly'))
        assembly.addAction(self.action('motion_links','관절 운동 한계 / 모션 연결…',self.motion_dialog,None,'assembly'))
        assembly.addAction(self.action('joint_alignment','관절 축 · 구멍 동심 정렬…',self.joint_alignment_dialog,None,'assembly'))
        engineering=self.menuBar().addMenu('도면 / 해석');engineering.addAction(self.action('drawing','정투상 도면…',lambda:self.study_dialog('drawing'),None,'file'));engineering.addAction(self.action('robot_study','로봇 도달 / 토크 / 운동…',lambda:self.study_dialog('robot'),None,'assembly'));engineering.addAction(self.action('tensile','시편 응력 / 변형…',lambda:self.study_dialog('tensile'),None,'specimen'))
        assembly.addAction(self.action('fit_tolerance','축 / 구멍 공차…',lambda:self.study_dialog('fit'),None,'dimension'));assembly.addAction(self.action('interference','간섭 검사…',self.interference_dialog,None,'assembly'));model.addAction(self.action('shaft','축 만들기',lambda:self.add_preset('cylinder'),None,'extrude'));model.addAction(self.action('color','선택 부품 색상…',self.color_selection,None,'ai'))
        file.addAction(self.action('print_mode','3D 프린팅 · STL 미리보기…',self.print_mode_dialog,None,'file'))
        file.addAction(self.action('print_profile','3D 프린터 · 전체 여유 / 공차…',self.print_profile_dialog,None,'dimension'));assembly.addAction(self.actions['print_profile'])
        model.addAction(self.action('electronics_mount','전장부품 장착 자리…',self.electronics_mount_dialog,None,'assembly'));assembly.addAction(self.actions['electronics_mount'])
        engineering.addAction(self.action('electrical','전장 회로 · 배선 / 전압강하…',self.electrical_dialog,None,'assembly'))
        engineering.addAction(self.action('circuit_workspace','메인 회로도 작업 공간',self.show_circuit_workspace,None,'assembly'))
        engineering.addAction(self.action('wiring_diagram','회로도',self.open_wiring_diagram,None,'assembly'))
        engineering.addAction(self.action('drive_simulation','모터 / 엔코더 · 폐루프 시뮬레이션…',self.open_drive_simulation,None,'assembly'))
        engineering.addAction(self.action('electrical_register','CAD 부품 · 전장 등록 / 모식도…',self.electrical_part_dialog,None,'assembly'))
        engineering.addAction(self.action('mcu_pins','MCU 선택 / 핀 연결…',self.mcu_pin_dialog,None,'assembly'))
        engineering.addAction(self.action('power_path','전원 연결 설계…',self.power_path_dialog,None,'assembly'))
        engineering.addAction(self.action('mechanical_catalog','기계 · 전원 규격 DB…',self.mechanical_catalog_dialog,None,'dimension'))
        engineering.addAction(self.action('fastener_check','볼트 축방향 검토…',self.fastener_check_dialog,None,'dimension'))
        assembly.addAction(self.actions['electrical'])
        assembly.addAction(self.actions['mcu_pins']);assembly.addAction(self.actions['electrical_register'])
        assembly.addAction(self.actions['power_path']);model.addAction(self.actions['mechanical_catalog'])
        assembly.addAction(self.action('component_specs','제품 스펙 · URL 가져오기…',self.component_specs_dialog,None,'open'))
        assembly.addAction(self.action('part_product','부품 제품 스펙 / 구매 링크…',self.part_product_dialog,None,'open'))
        self.make_selection_tools(edit,assembly)
        edit.addAction(self.action('configurations','설계 구성표…',self.configuration_dialog,None,'dimension'))
        model.addAction(self.action('inspection','각도 / 간격 / 질량 / 단면 검사…',self.inspection_dialog,None,'dimension'))
        assembly.addAction(self.action('linked_copy','연결 복제 · 원본 수정 추적',self.linked_copy,None,'assembly'))
        edit.addAction(self.action('search','도구 찾기…',self.command_palette,'Ctrl+K','ai'))
        edit.addAction(self.action('find','부품 / 기능 검색…',self.find_parts_commands,'Ctrl+F','ai'))
        view=self.menuBar().addMenu('보기(&V)');view.addAction(self.action('fit','모델에 맞춤',self.fit,None,'fit'));self.view_menu=view;edge=view.addAction('모서리 표시');edge.setCheckable(True);edge.setChecked(True);edge.toggled.connect(self.viewport.edges)
        for key,title in [('grid','격자 표시'),('axes','좌표축 표시')]:
            a=self.action(key,title,lambda checked,k=key:self.toggle_display(k,checked));a.setCheckable(True);a.setChecked(True);view.addAction(a)
        language=view.addMenu('언어 / Language');group=QActionGroup(self);group.setExclusive(True)
        view.addAction(self.action('display_style','격자 · 축 색상 / 밝기 / 선 굵기…',self.display_style_dialog))
        notify=self.action('ai_notifications','AI 설계 완료 알림',lambda:None);notify.setCheckable(True);notify.setChecked(self.completion_notifier.enabled);notify.toggled.connect(self.completion_notifier.set_enabled);view.addAction(notify)
        for code,title in [('ko','한국어'),('en','English')]:
            a=language.addAction(title);a.setCheckable(True);a.setChecked(self.language_service.language==code);group.addAction(a);a.triggered.connect(lambda checked,c=code:self.change_language(c))
        help=self.menuBar().addMenu('도움말(&H)');help.addAction(self.action('manual','사용 방법 · 단축키 매뉴얼',self.help_dialog,'F1'));help.addAction(self.action('update','업데이트 확인…',self.check_updates));help.addAction(self.action('about','버전 / 앱 정보…',self.about_dialog))
        help.addAction(self.action('openai_setup','OpenAI 연결 · API 키 발급…',self.openai_setup))
        help.addAction(self.action('codex_setup','Codex 연결 · ChatGPT 구독…',self.codex_setup))
        help.addAction(self.action('graphics_diagnostics','그래픽 시작 진단…',self.graphics_diagnostics))
    def graphics_diagnostics(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        box=QMessageBox(self);box.setWindowTitle('그래픽 시작 진단');box.setText('현재 렌더러: '+('소프트웨어 3D (CPU)' if os.getenv('CADSTUDIO_RENDERER')=='software' else '기본 그래픽 드라이버'))
        box.setInformativeText('시작할 때 실제 3D 렌더링을 별도 프로세스에서 검사합니다. 기본 드라이버가 실패하면 소프트웨어 렌더링으로 전환합니다. 설계 데이터와 형상 계산은 동일합니다.')
        try:box.setDetailedText((self.data_dir/'graphics-status.json').read_text(encoding='utf-8'))
        except OSError:pass
        open_log=box.addButton('진단 폴더 열기',QMessageBox.ButtonRole.ActionRole);box.addButton(QMessageBox.StandardButton.Close);box.exec()
        if box.clickedButton()==open_log:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))
    def make_toolbar(self):
        self.toolbar=QToolBar('작업 공간');self.toolbar.setObjectName('modelToolbar');self.toolbar.setMovable(False);self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);self.toolbar.setIconSize(QSize(25,25));self.addToolBar(self.toolbar)
        for key in ('new','open','save'):self.toolbar.addAction(self.actions[key])
        self.toolbar.addSeparator();self.workspace=combo([('model','설계'),('assembly','조립'),('specimen','시편'),('print','3D 프린팅'),('circuit','회로도')]);self.workspace.setMinimumWidth(95);self.workspace.setToolTip('작업 공간을 선택하면 필요한 도구가 나타납니다.');self.toolbar.addWidget(self.workspace);self.toolbar.addSeparator();self.mode_tools={'model':[],'assembly':[],'specimen':[],'print':[],'circuit':[]}
        self.plane=combo([('XY','XY 평면'),('XZ','XZ 평면'),('YZ','YZ 평면'),('custom','사용자 작업 평면…')]);self.mode_tools['model'].append(self.toolbar.addWidget(self.plane));self.mode_tools['model'].append(self.toolbar.addAction(icon('sketch'),'스케치 작성',lambda:self.start_sketch(self.plane.currentData())))
        for key in ('extrude','face_sketch','edit_sketch'):self.add_mode_tool('model',key)
        advanced=QToolButton();advanced.setText('3D 도구');advanced.setIcon(icon('extrude'));advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);advanced.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);advanced_menu=QMenu(advanced)
        for key in ('hole','thread','revolve','solid_tools','feature_manager','sweep','loft','surface','edge_finish'):advanced_menu.addAction(self.actions[key])
        advanced.setMenu(advanced_menu);self.mode_tools['model'].append(self.toolbar.addWidget(advanced))
        b=QToolButton();b.setText('부품 추가');b.setIcon(icon('extrude'));b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(b)
        for kind,title in TITLES.items():menu.addAction(title,lambda k=kind:self.add_preset(k))
        b.setMenu(menu);self.add_part_action=self.toolbar.addWidget(b)
        for key in ('face_joint','drive','joint_hardware','gears','robot','mate'):self.add_mode_tool('assembly',key)
        self.add_mode_tool('assembly','electrical')
        self.add_mode_tool('circuit','electrical');self.add_mode_tool('circuit','electrical_register');self.add_mode_tool('circuit','mcu_pins')
        self.add_mode_tool('assembly','loop');self.add_mode_tool('assembly','robot_study')
        self.add_mode_tool('print','print_mode');self.add_mode_tool('print','print_profile');self.add_mode_tool('print','interference');self.add_mode_tool('specimen','specimen');self.add_mode_tool('specimen','tensile');self.toolbar.addAction(self.actions['measure']);self.toolbar.addAction(self.actions['color']);self.toolbar.addAction(self.actions['wiring_diagram']);self.toolbar.addAction(self.actions['parameters']);self.toolbar.addSeparator()
        for key in ('undo','redo','fit'):self.toolbar.addAction(self.actions[key])
        self.toolbar.addAction(icon('ai'),'설계 명령',lambda:self.ai_dock.setVisible(not self.ai_dock.isVisible()));self.workspace.currentIndexChanged.connect(self.workspace_changed);self.workspace_changed()
    def add_mode_tool(self,mode,key):
        source=self.actions[key];copy=self.toolbar.addAction(source.icon(),source.text(),source.trigger);copy.setCheckable(source.isCheckable());source.toggled.connect(copy.setChecked);self.mode_tools[mode].append(copy)
    def find_parts_commands(self):
        from .search_dialog import SearchDialog,activate_result
        dialog=SearchDialog(self)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted and dialog.result_row:activate_result(self,dialog.result_row)
        finally:dialog.deleteLater()
    def command_palette(self):
        dialog=QDialog(self);dialog.setWindowTitle('도구 찾기 · Ctrl+K');dialog.resize(530,480);layout=QVBoxLayout(dialog);search=QLineEdit();search.setPlaceholderText('예: 구멍, 측정, 스윕, 구속, 로봇, 도면');layout.addWidget(search);items=QListWidget();layout.addWidget(items)
        def update():
            items.clear()
            for key,action in self.actions.items():
                if key!='search' and action.isEnabled() and search.text().casefold() in action.text().casefold():
                    item=QListWidgetItem(action.icon(),action.text());item.setData(Qt.ItemDataRole.UserRole,key);items.addItem(item)
            if items.count():items.setCurrentRow(0)
        def activate(item=None):
            item=item or items.currentItem()
            if item:key=item.data(Qt.ItemDataRole.UserRole);dialog.accept();QTimer.singleShot(0,self.actions[key].trigger)
        search.textChanged.connect(update);search.returnPressed.connect(activate);items.itemActivated.connect(activate);update();search.setFocus();dialog.exec()
    def select_profile_3d(self,identifier,index):
        self.select_sketch(identifier);self.selected_profile=(identifier,index);self.property_layout.insertWidget(1,label(f'선택 영역 {index+1} · E로 3D 돌출'))
    def parameter_dialog(self):
        if self.busy or self.sketching:return
        from .parameters import ParameterDialog
        base=self.document.design or Design(name='변수 설계',parts=[]).model_dump();dialog=ParameterDialog(self,base)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'변수 / 연결 치수 편집',{'tool':'parameters'},fit=False)
    def independent_shape(self):
        part=self.part()
        if part and part.get('source_part_id'):
            source=part['source_part_id'];self.select_part(source);self.message('연결 복제의 형상은 원본에서 편집합니다. 원본을 선택했습니다. 도구를 다시 실행하세요. 독립 편집은 연결 해제를 사용하세요.');return False
        return True
    def sheetmetal_dialog(self,checked=False,part_id=None):
        if part_id and not self.independent_shape():return
        if self.busy or self.sketching:return
        from .sheetmetal_dialog import SheetMetalDialog
        dialog=SheetMetalDialog(self,self.document.design or Design().model_dump(),part_id)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'판금 절곡 / 전개',{'tool':'sheetmetal'},fit=True)
    def configuration_dialog(self):
        if self.busy or self.sketching or not self.document.design:return
        from .configuration_dialog import ConfigurationDialog
        dialog=ConfigurationDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'설계 구성 적용',{'tool':'configuration','name':dialog.name.text()},fit=True)
    def material_dialog(self):
        if self.busy or self.sketching or not self.part():return
        from .inspection_dialog import MaterialDialog
        dialog=MaterialDialog(self,self.document.design,self.selected)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'부품 재질 변경',{'tool':'material','part_id':self.selected})
    def inspection_dialog(self):
        if self.busy or self.sketching or not self.document.design or not self.document.design['parts']:return
        from .inspection_dialog import InspectionDialog
        InspectionDialog(self,self.document.design,self.selected).exec()
    def linked_copy(self):
        if self.busy or self.sketching or not self.part():return
        raw=deepcopy(self.document.design);p=deepcopy(self.part());p['source_part_id']=p['id'];p['id']='part-'+uid();p['name']+=' 연결 복제';p['fixed']=False;p['transform']['x']+=60;raw['parts'].append(p);self.apply_design(raw,'부품 연결 복제',{'source_part_id':self.selected},fit=True)
    def unlink_part(self):
        if self.busy or not self.part():return
        raw=deepcopy(self.document.design);next(p for p in raw['parts'] if p['id']==self.selected).pop('source_part_id',None);self.apply_design(raw,'부품 연결 해제',{'part_id':self.selected})
    def import_model(self):
        if self.busy or self.sketching:return
        path,_=QFileDialog.getOpenFileName(self,'CAD 부품 가져오기','','CAD 파일 (*.step *.stp *.iges *.igs *.stl *.brep)')
        if not path:return
        from ..imported import import_asset
        from ..kernel import KERNEL_LOCK
        def work():
            with KERNEL_LOCK:return import_asset(path)
        def done(asset):
            raw=deepcopy(self.document.design) if self.document.design else Design(name=Path(path).stem).model_dump();identifier='asset-'+asset.sha256;raw.setdefault('assets',{})[identifier]=asset.model_dump();raw['parts'].append(Part(id='part-'+uid(),name=Path(path).stem[:80],geometry={'kind':'imported','asset_id':identifier}).model_dump());self.apply_design(raw,'CAD 부품 가져오기',{'tool':'import','format':asset.format,'name':asset.name},fit=True)
        self.run(work,done,'CAD 파일을 읽고 검증하는 중…')
    def revolve_dialog(self,checked=False,part_id=None):
        if part_id and not self.independent_shape():return
        if self.busy or self.sketching:return
        from .solid_dialog import RevolveDialog
        raw=self.document.design or Design().model_dump();dialog=RevolveDialog(self,raw,part_id)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'회전 피처 편집',{'tool':'revolve'},fit=True)
    def solid_dialog(self,checked=False,feature_id=None):
        if not self.independent_shape():return
        if self.busy or self.sketching:return
        if not self.part():self.message('작업할 부품을 먼저 선택하세요.');return
        from .solid_dialog import SolidDialog
        face=self.viewport.face[1] if self.viewport.face and self.viewport.face[0]==self.selected else None
        dialog=SolidDialog(self,self.document.design,self.selected,feature_id=feature_id,face=face)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'솔리드 피처 편집',{'tool':'solid','feature_id':dialog.feature_id},fit=True)
    def feature_manager(self):
        if not self.independent_shape():return
        if self.busy or self.sketching or not self.part():return
        from .feature_manager import FeatureManager
        dialog=FeatureManager(self,self.document.design,self.selected)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'피처 순서 / 억제 편집',{'tool':'feature-manager'},fit=True)
    def motion_dialog(self):
        if self.busy or self.sketching or not self.document.design:return
        from .motion_dialog import MotionDialog
        dialog=MotionDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'관절 한계 / 모션 연결',{'tool':'motion-links'},fit=True)
    def extrude_dialog(self,checked=False,*,sketch_id=None,feature_id=None):
        if self.busy:return
        if not self.sketching and not sketch_id and not self.selected_sketch and not self.independent_shape():return
        if self.sketching:self.editor.prepare_extrude();return
        if not self.document.design:return
        from .extrude import ExtrudeDialog
        sketch_id=sketch_id or (self.selected_sketch if not feature_id else None)
        if sketch_id:
            saved=next((s for s in self.document.design.get('sketches',[]) if s['id']==sketch_id),None)
            if not saved:return
            g=saved['geometry'];context=deepcopy(saved['context']);context['sketch_id']=sketch_id
        else:
            p=self.part()
            if not p:self.message('스케치의 닫힌 영역 또는 돌출 부품을 먼저 선택하세요.');return
            if feature_id:
                f=next(f for f in p['features'] if f['id']==feature_id)
                if f.get('kind') in ('fillet','chamfer','thread','solid'):return
                g=f['sketch'];context=dict(part_id=p['id'],feature_id=feature_id,operation=f['operation'],support_feature=f['support_feature'],face=dict(index=f['face'],face_count=f['support_face_count'],origin=f['origin'],normal=f['normal'],x_direction=f['x_direction']))
            elif p['geometry']['kind']=='extrusion':g=p['geometry'];context=dict(part_id=p['id'],edit_base=True)
            else:self.message('스케치 영역을 선택하세요. 구멍은 평평한 면 선택 → H로 만들 수 있습니다.');return
        profile=self.selected_profile[1] if self.selected_profile and self.selected_profile[0]==sketch_id else None
        try:dialog=ExtrudeDialog(self,self.document.design,g,context,profile)
        except Exception as exc:self.show_error(str(exc));return
        if dialog.exec()==QDialog.DialogCode.Accepted:
            history={**context,'tool':'extrude-3d','profiles':dialog.selected_profiles,'depth':dialog.depth.value(),'expression':dialog.depth.formula(),'operation':dialog.operation.currentData()}
            self.apply_design(dialog.checked.model_dump(),'3D 돌출 / 깊이 편집',history,after=lambda:self.select_part(dialog.part_id))
    def measure_dialog(self):
        if self.busy or self.sketching:return
        if not self.document.design or not self.document.design['parts']:self.message('측정할 부품을 먼저 만드세요.');return
        from .inspect_tools import MeasurementDialog
        try:MeasurementDialog(self,self.document.design).exec()
        except Exception as exc:self.show_error(str(exc))
    def interference_dialog(self):
        if self.busy or self.sketching:return
        if not self.document.design or not self.document.design['parts']:self.message('검사할 부품을 먼저 만드세요.');return
        from .inspect_tools import InterferenceDialog
        def opened(data):InterferenceDialog(self,*data).exec()
        from .inspect_tools import interference_data
        self.run(lambda:interference_data(self.document.design),opened,'정확한 형상으로 간섭 검사 중…')
    def electronics_mount_dialog(self):
        if self.busy or self.sketching or not self.independent_shape():return
        if not self.viewport.face or not self.viewport.face[1] or not self.viewport.face[1]['planar']:self.message('장착 자리를 만들 평평한 면을 먼저 선택하세요.');return
        from .electronics_dialog import ElectronicsMountDialog
        identifier,face=self.viewport.face
        dialog=ElectronicsMountDialog(self,self.document.design,identifier,face)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'전장부품 장착 자리',{'tool':'electronics-mount','part_id':identifier,'face':face,'dimensions':dialog.candidate()['spec'],'product_source':dialog.source_record})

    def electrical_dialog(self):
        if self.busy or self.sketching:return
        from .electrical_dialog import ElectricalDialog
        dialog=ElectricalDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            raw=deepcopy(self.document.design) if self.document.design else Design().model_dump()
            raw['electrical']=dialog.workspace.model_dump()
            self.apply_design(raw,'전장 회로 / 배선 편집',{'tool':'electrical','component_ids':[c.id for c in dialog.workspace.components]})

    def show_circuit_workspace(self):
        if self.busy or self.sketching:return
        index=self.workspace.findData('circuit')
        if self.workspace.currentIndex()!=index:self.workspace.setCurrentIndex(index)
        else:self.refresh_circuit_workspace()

    def refresh_circuit_workspace(self):
        from ..electrical import ElectricalWorkspace,evaluate_electrical
        from .electrical_schematic import ElectricalSchematicDialog
        raw=(self.document.design or {}).get('electrical') or {'nodes':['GND'],'components':[]}
        identity=json.dumps([self.language_service.language,raw,[(p['id'],p['name']) for p in (self.document.design or {}).get('parts',[])]],ensure_ascii=False,sort_keys=True)
        if getattr(self,'circuit_identity',None)==identity and getattr(self,'circuit_panel',None):
            self.stack.setCurrentWidget(self.circuit_panel);return
        workspace=ElectricalWorkspace.model_validate(raw)
        try:result=evaluate_electrical(workspace)
        except (ValueError,TypeError):result=None
        old=getattr(self,'circuit_panel',None)
        panel=ElectricalSchematicDialog(self,workspace,result,(self.document.design or {}).get('parts',[]),editable=False)
        panel.setWindowFlags(Qt.WindowType.Widget)
        panel.setObjectName('mainCircuitWorkspace')
        panel.editRequested.connect(self.edit_main_circuit)
        panel.simulationRequested.connect(self.open_drive_simulation)
        panel.focusRequested.connect(self.toggle_circuit_focus)
        panel.partActivated.connect(self.show_electrical_cad_part)
        self.circuit_panel=panel;self.stack.addWidget(panel);self.stack.setCurrentWidget(panel)
        self.circuit_identity=identity
        if old:self.stack.removeWidget(old);old.deleteLater()

    def toggle_circuit_focus(self):
        docks=(self.browser_dock,self.property_dock,self.ai_dock,self.timeline_dock)
        saved=getattr(self,'circuit_focus_panels',None)
        if saved is None:
            self.circuit_focus_panels=[dock.isVisible() for dock in docks]
            for dock in docks:dock.hide()
        else:
            for dock,visible in zip(docks,saved):dock.setVisible(visible)
            self.circuit_focus_panels=None
        QTimer.singleShot(0,self.circuit_panel.fit_scene)

    def edit_main_circuit(self):
        if self.busy or self.sketching:return
        from .electrical_schematic import ElectricalSchematicDialog
        raw=deepcopy(self.document.design) if self.document.design else Design().model_dump()
        dialog=ElectricalSchematicDialog(self,raw.get('electrical') or {'nodes':['GND'],'components':[]},parts=raw['parts'])
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
            raw['electrical']=dialog.accepted_workspace.model_dump()
            self.apply_design(raw,'회로도 부품 / 핀 / 배치 편집',{'tool':'electrical-schematic','component_ids':[c.id for c in dialog.accepted_workspace.components]},fit=False)

    def open_wiring_diagram(self,component_id=None):
        if self.busy or self.sketching:return
        if isinstance(component_id,bool):component_id=None
        from .electrical_schematic import ElectricalSchematicDialog
        raw=(self.document.design or {}).get('electrical') or {'nodes':['GND'],'components':[]}
        panel=getattr(self,'wiring_window',None)
        if panel is None:
            panel=self.make_wiring_panel(raw);self.wiring_window=panel
        else:self.refresh_wiring_diagram();panel=self.wiring_window
        panel.show();panel.raise_();panel.activateWindow()
        if component_id:QTimer.singleShot(0,lambda:panel.focus_component(component_id))

    def open_drive_simulation(self):
        if self.busy or self.sketching:return
        from .drive_simulation_dialog import DriveSimulationDialog
        raw=deepcopy(self.document.design) if self.document.design else Design().model_dump()
        dialog=DriveSimulationDialog(self,raw)
        dialog.exec()
        dialog.deleteLater()

    def make_wiring_panel(self,raw):
        from .electrical_schematic import ElectricalSchematicDialog
        panel=ElectricalSchematicDialog(self,raw,parts=(self.document.design or {}).get('parts',[]),editable=False)
        panel.setObjectName('floatingWiringDiagram');panel.setWindowFlags(Qt.WindowType.Window)
        panel.editRequested.connect(self.edit_main_circuit);panel.partActivated.connect(self.show_electrical_cad_part)
        panel.simulationRequested.connect(self.open_drive_simulation)
        panel.close_button.show();return panel

    def refresh_wiring_diagram(self):
        panel=getattr(self,'wiring_window',None)
        if panel is None:return
        from ..electrical import ElectricalWorkspace,evaluate_electrical
        raw=(self.document.design or {}).get('electrical') or {'nodes':['GND'],'components':[]}
        parts=(self.document.design or {}).get('parts',[])
        english=self.language_service.language=='en'
        if panel.english!=english:
            selected=panel._selected_id();visible=panel.isVisible();geometry=panel.geometry();mode=panel.view_mode
            replacement=self.make_wiring_panel(raw);self.wiring_window=replacement
            replacement.mode_picker.setCurrentIndex(replacement.mode_picker.findData(mode));replacement.setGeometry(geometry)
            panel.close();panel.deleteLater()
            if visible:replacement.show()
            if selected:replacement.focus_component(selected)
            return
        if panel.workspace.model_dump()==ElectricalWorkspace.model_validate(raw).model_dump() and panel.parts==tuple(parts) and panel.english==english:return
        panel.english=english
        selected=panel._selected_id();panel.parts=tuple(parts);panel.workspace=ElectricalWorkspace.model_validate(raw).model_copy(deep=True)
        try:panel.result=evaluate_electrical(panel.workspace)
        except (ValueError,TypeError):panel.result=None
        panel._draw();panel.refresh_mcu_list();panel.workspace_changed=False
        if selected:panel.focus_component(selected)

    def show_electrical_cad_part(self,part_id):
        if self.busy or self.sketching:return
        if not any(p['id']==part_id for p in (self.document.design or {}).get('parts',[])):
            self.message('이 전자제품에 연결된 CAD 부품이 없습니다. CAD 부품을 전장으로 등록하세요.');return
        if self.workspace.currentData()=='circuit':self.open_wiring_diagram(next((c['id'] for c in self.document.design.get('electrical',{}).get('components',[]) if c.get('part_id')==part_id),None))
        self.workspace.setCurrentIndex(self.workspace.findData('model'));self.reset_role_view(restore=True)
        if part_id in self.viewport.hidden:self.viewport.visibility(part_id,True)
        self.select_parts([part_id]);actor=self.viewport.actors.get(part_id)
        if actor is not None:self.viewport.renderer.ResetCamera(actor[0].GetBounds());self.viewport.renderer.ResetCameraClippingRange();self.viewport.window.Render()
        self.message('회로도와 연결된 CAD 부품: '+next(p['name'] for p in self.document.design['parts'] if p['id']==part_id))

    def electrical_part_dialog(self,part_id=None):
        if self.busy or self.sketching:return
        if isinstance(part_id,bool):part_id=None
        if not self.document.design or not self.document.design['parts']:
            self.message('전장으로 등록할 CAD 부품을 먼저 만들거나 가져오세요.');return
        from .electrical_part_dialog import ElectricalPartDialog
        try:dialog=ElectricalPartDialog(self,self.document.design,part_id or self.selected)
        except (ValueError,TypeError) as exc:self.show_error(str(exc));return
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked is not None:
            self.apply_design(dialog.checked.model_dump(),'CAD 부품 전장 등록 / 핀 연결',
                              {'tool':'electrical-register','part_id':dialog.current_part_id()},
                              after=lambda:self.select_parts([dialog.current_part_id()]))

    def component_specs_dialog(self):
        from .component_specs_dialog import ComponentSpecsDialog
        dialog=ComponentSpecsDialog(self);dialog.use.hide()
        if dialog.exec()==QDialog.DialogCode.Accepted:self.use_component_source(dialog.record)

    def part_product_dialog(self,part_id=None):
        if self.busy or self.sketching:return
        identifier=part_id if isinstance(part_id,str) else self.selected
        if not identifier or not self.document.design:
            self.message('제품 자료를 연결할 부품을 선택하세요.');return
        from .part_product_dialog import PartProductDialog
        dialog=PartProductDialog(self,self.document.design,identifier)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked is not None:
            checked=dialog.checked.model_dump()
            if checked!=self.document.design:
                self.apply_design(checked,'부품 제품 스펙 / 링크',{'tool':'part-product','part_id':identifier},
                                  after=lambda:self.select_parts([identifier]))
        dialog.deleteLater()

    def mcu_pin_dialog(self):
        if self.busy or self.sketching:return
        from .mcu_pin_dialog import McuPinDialog
        from ..models import Design
        raw=deepcopy(self.document.design) if self.document.design else Design(name='전장 설계',parts=[]).model_dump()
        dialog=McuPinDialog(self,raw.get('electrical') or {'nodes':['GND'],'components':[]},raw['parts'])
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
            raw['electrical']=dialog.accepted_workspace.model_dump()
            self.apply_design(raw,'MCU 핀 연결 편집',{'tool':'electrical-mcu-pins','component_ids':[c.id for c in dialog.accepted_workspace.components if c.kind=='mcu']})

    def power_path_dialog(self):
        if self.busy or self.sketching:return
        from .power_path_dialog import PowerPathDialog
        raw=deepcopy(self.document.design) if self.document.design else Design().model_dump()
        dialog=PowerPathDialog(self,raw.get('electrical') or {'nodes':['GND'],'components':[]},raw['parts'])
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.build is not None:
            raw['electrical']=dialog.build.workspace.model_dump()
            self.apply_design(raw,'전원 연결 설계',{'tool':'electrical-power-path','component_ids':list(dialog.build.ids.values())})

    def mechanical_catalog_dialog(self):
        if self.busy or self.sketching:return
        from .mechanical_catalog_dialog import MechanicalCatalogDialog
        from ..mechanical_catalog import format_ai_spec
        dialog=MechanicalCatalogDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.entry is not None:
            spec=format_ai_spec(dialog.entry)
            current=self.prompt.toPlainText().strip()
            self.prompt.setPlainText((current+'\n\n' if current else '')+spec)
            self.ai_dock.show();self.ai_dock.raise_()
            self.message('품번·치수·조건·출처를 AI 요청에 추가했습니다.')

    def fastener_check_dialog(self):
        if self.busy or self.sketching:return
        from .fastener_check_dialog import FastenerCheckDialog
        FastenerCheckDialog(self).exec()

    def use_component_source(self,record):
        from ..component_specs import spec_prompt
        self.prompt.setPlainText(spec_prompt(record));self.ai_dock.show();self.ai_dock.raise_();self.message('출처와 치수를 AI 요청에 넣었습니다. 요청을 확인하고 설계 초안 생성을 누르세요.')

    def hole_dialog(self):
        if not self.independent_shape():return
        if self.busy or self.sketching:return
        if not self.viewport.face or not self.viewport.face[1] or not self.viewport.face[1]['planar']:self.message('구멍을 시작할 평평한 면을 먼저 클릭하세요.');return
        from .inspect_tools import HoleDialog
        part_id,face=self.viewport.face
        try:dialog=HoleDialog(self,self.document.design,part_id,face)
        except Exception as exc:self.show_error(str(exc));return
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'구멍 절삭',{'tool':'hole','part_id':part_id,'feature_id':dialog.feature_id,'face':face,'standard_source':dialog.standard_record()})
    def study_dialog(self,kind,identifier=None):
        if self.busy or self.sketching:return
        if not self.document.design or not self.document.design['parts']:self.message('먼저 설계할 부품을 만드세요.');return
        from .studies import RobotStudy,TensileStudy,DrawingDialog
        from .fit_dialog import FitDialog
        cls={'robot':RobotStudy,'tensile':TensileStudy,'drawing':DrawingDialog,'fit':FitDialog}[kind]
        try:dialog=cls(self,self.document.design,identifier,**({'part_id':self.selected} if kind in ('drawing','tensile') else {}))
        except Exception as exc:self.show_error(str(exc));return
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.candidate,dialog.windowTitle()+' 저장',{'tool':kind,'study_id':dialog.identifier})
    def workspace_changed(self):
        for mode,actions in self.mode_tools.items():
            for action in actions:action.setVisible(mode==self.workspace.currentData())
        self.add_part_action.setVisible(self.workspace.currentData() not in ('specimen','circuit'))
        if self.workspace.currentData()=='circuit':self.refresh_circuit_workspace()
        elif not self.sketching:
            if getattr(self,'circuit_focus_panels',None) is not None:self.toggle_circuit_focus()
            self.stack.setCurrentWidget(self.viewport)
    def print_mode_dialog(self):
        if self.busy or self.sketching:return
        if not self.document.design or not self.document.design['parts']:self.message('출력할 부품을 먼저 만드세요.');return
        from .print_dialog import PrintDialog
        PrintDialog(self,self.document.design,self.selected_parts).exec()
    def research_package_dialog(self):
        if self.busy or self.sketching or not self.document.design:return
        from .research_dialog import ResearchDialog
        dialog=ResearchDialog(self,self.document.design,self.selected)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            path,_=QFileDialog.getSaveFileName(self,'피로시험 준비 패키지 저장','fatigue-research.zip','ZIP (*.zip)')
            if not path:return
            from ..research_package import export_package
            raw=deepcopy(self.document.design);part_id=dialog.part.currentData();protocol=dialog.protocol
            self.run(lambda:export_package(raw,part_id,protocol,path),lambda p:self.message('연구 패키지 내보내기 완료: '+str(p)),'시편 형상과 데이터 양식 내보내는 중…')
        finally:dialog.deleteLater()

    def specimen_dialog(self):
        if self.busy or self.sketching:return
        from .workflows import SpecimenDialog
        part=self.part();identifier=part['id'] if part and part['geometry']['kind'] in ('round_specimen','flat_specimen','wafer') else None;dialog=SpecimenDialog(self,self.document.design,identifier)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'시편 치수 설계',{'tool':'specimen','part_id':dialog.part_id},fit=True,after=lambda:self.select_part(dialog.part_id))
    def modelling_dialog(self,kind='sweep',surface=False,part_id=None):
        if part_id and not self.independent_shape():return
        if self.busy or self.sketching:return
        from .modelling import ModellingDialog
        part=self.part();identifier=part_id or (part['id'] if part and part['geometry']['kind']==kind and not surface else None)
        dialog=ModellingDialog(self,self.document.design,kind,surface,identifier)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),('곡면 ' if not dialog.solid.isChecked() else '')+TITLES[kind]+' 설계',{'tool':kind,'part_id':dialog.identifier},fit=True,after=lambda:self.select_part(dialog.identifier))
    def edge_finish_dialog(self,feature_id=None):
        if not self.independent_shape():return
        if self.busy or self.sketching:return
        if not self.part():self.message('처리할 부품을 먼저 선택하세요.');return
        from .modelling import EdgeFinishDialog
        try:dialog=EdgeFinishDialog(self,self.document.design,self.selected,feature_id if isinstance(feature_id,str) else None)
        except Exception as exc:self.show_error(str(exc));return
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'3D 필렛 / 모따기',{'tool':'edge-finish','part_id':self.selected,'feature_id':dialog.feature_id})
    def thread_dialog(self,feature_id=None):
        if not self.independent_shape():return
        if self.busy or self.sketching:return
        if not self.part():self.message('나사를 만들 축 또는 구멍이 있는 부품을 먼저 선택하세요.');return
        from .threading_tool import ThreadDialog
        part_id=self.selected;face=self.viewport.face
        index=face[1]['index'] if face and face[0]==part_id and face[1] and face[1].get('cylinder') else None
        dialog=ThreadDialog(self,self.document.design,part_id,feature_id if isinstance(feature_id,str) else None,index)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            feature=next(f for p in dialog.checked.parts if p.id==part_id for f in p.features if f.id==dialog.feature_id)
            self.apply_design(dialog.checked.model_dump(),'나사산 편집' if feature_id else '나사산 생성',{'tool':'thread','part_id':part_id,'feature':feature.model_dump()})
    def closure_dialog(self,identifier=None):
        if self.busy or self.sketching:return
        if not self.document.design or len(self.document.design['parts'])<2:self.message('부품과 회전 조인트를 먼저 만들거나 조립 메뉴에서 4절 링크를 추가하세요.');return
        from .modelling import ClosureDialog
        dialog=ClosureDialog(self,self.document.design,identifier if isinstance(identifier,str) else None)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'폐루프 조립 연결',{'tool':'closure','loop_id':dialog.identifier},fit=True)
    def add_four_bar(self):
        if self.busy or self.sketching:return
        from ..mechanisms import four_bar
        mechanism=four_bar().model_dump()
        if self.document.design:
            raw=deepcopy(self.document.design);prefix='mech-'+uid()[:5]+'-';shift=self.result['stats']['max'][0]+100 if self.result else 150
            for part in mechanism['parts']:part['id']=prefix+part['id'];part['transform']['x']+=shift
            for mate in mechanism['mates']:
                for key in ('id','parent','child'):mate[key]=prefix+mate[key]
            for loop in mechanism['loops']:
                for key in ('id','parent','child'):loop[key]=prefix+loop[key]
                loop['passive_joints']=[prefix+j for j in loop['passive_joints']]
            raw['parts']+=mechanism['parts'];raw['mates']+=mechanism['mates'];raw.setdefault('loops',[]).extend(mechanism['loops'])
        else:raw=mechanism
        self.apply_design(raw,'4절 링크 폐루프 추가',{'tool':'four-bar'},fit=True)
    def robot_dialog(self):
        if self.busy or self.sketching:return
        from .workflows import RobotDialog
        dialog=RobotDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'로봇 링크 / 핀 / 관절 치수 편집',{'tool':'robot','dimensions':{k:w.value() for k,w in dialog.inputs.items()}},fit=True)
    def print_profile_dialog(self):
        if self.busy or self.sketching:return
        from .print_profile_dialog import PrintProfileDialog
        dialog=PrintProfileDialog(self,self.document.design,self.selected_ids())
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'프린터 전체 여유 / 공차 적용',{'tool':'print-profile'},fit=True)

    def gear_dialog(self):
        if self.busy or self.sketching:return
        from .gear_dialog import GearDialog
        dialog=GearDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked:
            self.apply_design(dialog.checked.model_dump(),'실제 스퍼 기어 구동 추가',{'tool':'gear-pair'},fit=True)

    def joint_hardware_dialog(self):
        if self.busy or self.sketching:return
        from .joint_hardware_dialog import JointHardwareDialog
        dialog=JointHardwareDialog(self,self.document.design,self.selected_joint)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked:
            payload=dialog.candidate();payload.pop('raw');self.apply_design(dialog.checked.model_dump(),'실제 회전 관절 구조 추가',{'tool':'joint-hardware',**payload},fit=True,after=lambda:self.select_parts(dialog.part_ids))
    def joint_alignment_dialog(self):
        if self.busy or self.sketching:return
        if not self.document.design or not any(m['kind'] in ('revolute','cylindrical','slider') for m in self.document.design['mates']):self.message('회전, 원통 또는 슬라이더 관절을 먼저 만드세요.');return
        from .joint_alignment_dialog import JointAlignmentDialog
        dialog=JointAlignmentDialog(self,self.document.design,self.selected_joint)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked:
            self.apply_design(dialog.checked.model_dump(),'관절 축 · 구멍 동심 정렬',{'tool':'joint-alignment','mate_id':dialog.mate.currentData(),'parent_face':dialog.parent_face.currentData(),'child_face':dialog.child_face.currentData(),'alignment':dialog.alignment})
    def drive_joints(self):
        if self.busy or self.sketching:return
        if not self.document.design or not any(m['kind']!='rigid' for m in self.document.design['mates']):self.message('회전·슬라이더·원통 조인트를 먼저 만들거나 로봇 조립을 추가하세요.');return
        from .workflows import JointDriveDialog
        dialog=JointDriveDialog(self,self.document.design,getattr(self,'selected_joint',None))
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'관절 자세 적용',{'tool':'joint-drive','joint_values':[{'mate_id':k[0],'axis':k[1],'value':dialog.inputs[k].value()} for k in sorted(dialog.changed_axes)]})
    def start_face_joint(self):
        if self.busy or self.sketching:return
        if self.joint_picks is not None:self.cancel_joint_pick();return
        if not self.document.design or len(self.document.design['parts'])<2:self.actions['face_joint'].setChecked(False);self.message('부품이 두 개 이상 있어야 조인트를 만들 수 있습니다.');return
        self.joint_picks=[];self.actions['face_joint'].setChecked(True);self.viewport.footer.setText('면 조인트  ① 기준 부품의 평면 클릭  →  ② 움직일 부품의 평면 클릭');self.message('먼저 기준 부품의 평평한 면을 클릭하세요.')
    def cancel_joint_pick(self):
        self.joint_picks=None;self.actions['face_joint'].setChecked(False);self.viewport.footer.setText('드래그: 회전 · 가운데: 이동 · 휠: 확대 · 클릭: 면 선택 · F: 맞춤')
    def receive_joint_face(self,identifier,face):
        if not face or not face['planar']:self.message('면 조인트에는 평평한 면을 선택하세요.');return
        if self.joint_picks and self.joint_picks[0][0]==identifier:self.message('두 번째 면은 다른 부품에서 선택하세요.');return
        self.joint_picks.append((identifier,deepcopy(face)))
        if len(self.joint_picks)==1:
            clear_layout(self.property_layout);self.property_layout.addWidget(label('기준 면 선택됨',True));self.property_layout.addWidget(label('이제 움직일 다른 부품의 평면을 클릭하세요.'));self.property_layout.addWidget(button('면 선택 취소',self.cancel_joint_pick));self.property_layout.addStretch();self.viewport.footer.setText('면 조인트  ② 움직일 다른 부품의 평면을 클릭하세요.');return
        first,second=self.joint_picks;self.cancel_joint_pick()
        from .workflows import FaceJointDialog
        dialog=FaceJointDialog(self,self.document.design,first,second)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'면 조인트 생성',{'tool':'face-joint','mate_id':dialog.mate_id,'parent_face':first[1],'child_face':second[1]},fit=True)
    def dock(self,title,name,area,widget):
        dock=QDockWidget(title,self);dock.setObjectName(name);dock.setWidget(widget);dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable|QDockWidget.DockWidgetFeature.DockWidgetClosable);self.addDockWidget(area,dock);self.view_menu.addAction(dock.toggleViewAction());return dock
    def make_browser(self):
        self.tree=QTreeWidget();self.tree.setObjectName('designBrowser');self.tree.setHeaderHidden(True);self.tree.setMinimumWidth(190);self.tree.itemClicked.connect(self.tree_clicked);self.tree.itemDoubleClicked.connect(self.tree_edit);self.tree.itemChanged.connect(self.visibility_changed);self.browser_dock=self.dock('설계 브라우저','browserDock',Qt.DockWidgetArea.LeftDockWidgetArea,self.tree);self.resizeDocks([self.browser_dock],[225],Qt.Orientation.Horizontal)
        self.prepare_tree_selection()
    def make_properties(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.properties=QWidget();self.property_layout=QVBoxLayout(self.properties);self.property_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize);self.property_layout.setContentsMargins(14,14,14,14);scroll.setWidget(self.properties);scroll.setMinimumWidth(270);self.property_dock=self.dock('속성 / 선택','propertiesDock',Qt.DockWidgetArea.RightDockWidgetArea,scroll);self.resizeDocks([self.property_dock],[305],Qt.Orientation.Horizontal)
    def make_timeline(self):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(10,8,10,8);row=QHBoxLayout();row.addWidget(label('작업 기록 · 클릭: 상세 · 더블클릭: 해당 단계로 복원',True));row.addStretch();row.addWidget(button('모든 분기 / 상세',self.history_dialog));v.addLayout(row);self.timeline=QListWidget();self.timeline.setObjectName('featureTimeline');self.timeline.setFlow(QListWidget.Flow.LeftToRight);self.timeline.setWrapping(False);self.timeline.setFixedHeight(66);self.timeline.setIconSize(QSize(24,24));self.timeline.itemClicked.connect(self.history_clicked);self.timeline.itemDoubleClicked.connect(lambda item:self.restore_history(item.data(Qt.ItemDataRole.UserRole)));v.addWidget(self.timeline);self.timeline_dock=self.dock('피처 / 작업 타임라인','historyDock',Qt.DockWidgetArea.BottomDockWidgetArea,w)
    def make_ai(self):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(12,12,12,12)
        self.chat_history=[];self.chat_identity=None
        self.reference_materials=[];self.github_reference_token=''
        self.ai_mode=combo([('design','설계'),('chat','질의응답')]);self.ai_mode.setToolTip('설계: 형상 생성/수정 · 질의응답: 설계 변경 없는 대화')
        self.prompt=QPlainTextEdit();self.prompt.setObjectName('designPrompt');self.prompt.setPlaceholderText('만들 형상과 치수, 바꿀 부분을 입력하세요.\n예: 선택한 구멍을 지름 6 mm로 줄여줘.');self.prompt.setMinimumHeight(84);self.prompt.setMaximumHeight(84);v.addWidget(self.prompt)
        self.reference_button=button('GitHub 연구자료 · 파일 첨부…',self.reference_dialog);v.addWidget(self.reference_button)
        self.reference_status=label('참고자료 없음',True);v.addWidget(self.reference_status)
        self.provider=combo([('local','오프라인 치수 명령 · 키 불필요'),('codex','Codex · ChatGPT 구독'),('openai','OpenAI · 유료 API'),('ollama','로컬 AI · Ollama')]);v.addWidget(self.provider)
        self.openai_setup_button=button('OpenAI 연결 · API 키 발급…',self.openai_setup);self.openai_setup_button.setToolTip('로그인·키 발급·결제 설정 안내를 엽니다.');v.addWidget(self.openai_setup_button)
        self.codex_setup_button=button('Codex 연결 · ChatGPT로 로그인…',self.codex_setup);v.addWidget(self.codex_setup_button)
        from .codex_connection import settings as codex_settings
        self.codex_config=codex_settings();self.codex_catalog=[];self.codex_connection_verified=False
        self.codex_model_label=label('Codex 모델: '+(self.codex_config['model'] or '연결 후 선택'),True);v.addWidget(self.codex_model_label)
        from .codex_model_picker import CodexModelPicker
        self.codex_models=CodexModelPicker(self);self.codex_models.set_catalog([],self.codex_config['model']);self.codex_models.modelSelected.connect(self.select_codex_model);v.addWidget(self.codex_models)
        self.codex_status=label('Codex · 연결 확인 전',True);v.addWidget(self.codex_status);self.codex_probe_task=None
        from .codex_usage import USAGE_NOTE
        self.codex_usage=label('Codex 주간 · 잔여량 확인 전',True);self.codex_usage.setToolTip(USAGE_NOTE);v.addWidget(self.codex_usage)
        self.codex_check_button=button('Codex 연결·사용량 새로고침',self.check_codex_status);v.addWidget(self.codex_check_button)
        self.ai_info=label('',True);v.addWidget(self.ai_info)
        self.ai_result=QPlainTextEdit();self.ai_result.setReadOnly(True);self.ai_result.setPlaceholderText('생성 진행과 검증 결과가 여기에 표시됩니다.');self.ai_result.setMinimumHeight(100)
        self.ai_settings_toggle=button('모델 · 대기 설정',lambda:None);self.ai_settings_toggle.setCheckable(True);self.ai_settings_toggle.setToolTip('모델 선택, 최대 대기 시간, API 키 설정');header=QHBoxLayout();header.addWidget(self.ai_mode);header.addStretch();header.addWidget(self.ai_settings_toggle);v.insertLayout(0,header)
        self.ai_settings=QWidget();settings=QVBoxLayout(self.ai_settings);settings.setContentsMargins(0,0,0,0);v.addWidget(self.ai_settings);self.ai_settings.hide()
        self.ai_settings_toggle.toggled.connect(self.ai_settings.setVisible)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('API 키 · 이번 실행 동안만 사용');self.key.setVisible(False);settings.addWidget(self.key)
        self.model=QLineEdit('gpt-4.1');self.model.setPlaceholderText('모델 이름');self.model.setVisible(False);settings.addWidget(self.model);self.provider.currentIndexChanged.connect(self.provider_changed)
        self.astra_button=button('Astra 모델 선택',lambda:self.model.setText('gpt-6-astra'));self.astra_button.hide();settings.addWidget(self.astra_button)
        self.cloud_effort=combo([('low','추론 · 빠르게'),('medium','추론 · 균형'),('high','추론 · 깊게')]);self.cloud_effort.setCurrentIndex(1);self.cloud_effort.hide();settings.addWidget(self.cloud_effort)
        from .model_picker import LocalModelPicker
        self.ollama_models=LocalModelPicker(self);self.ollama_models.hide();settings.addWidget(self.ollama_models)
        self.ai_timeout=combo([(180,'AI 최대 대기 · 3분'),(300,'AI 최대 대기 · 5분'),(600,'AI 최대 대기 · 10분'),(1200,'AI 최대 대기 · 20분'),(None,'AI 최대 대기 · 무제한 (취소 가능)')]);self.ai_timeout.setCurrentIndex(2);settings.addWidget(self.ai_timeout)
        self.ai_timeout.setToolTip('Codex·Ollama 무제한: 검증을 통과하거나 취소할 때까지 수정합니다. Codex 통신 단절은 자동 재연결하며 복구 대기는 시간 제한에서 제외합니다. 로그인·사용량 문제는 확인이 필요합니다. 재요청은 구독 사용량을 사용할 수 있습니다. 유료 API는 검증 재시도 횟수를 제한합니다.')
        settings.addWidget(button('로컬 AI 설치 / 모델 다운로드',self.install_local_ai))
        v.addWidget(self.ai_result,1)
        self.ai_scroll=QScrollArea();self.ai_scroll.setWidgetResizable(True);self.ai_scroll.setMinimumWidth(270);self.ai_scroll.setWidget(w)
        # Keep the actions reachable while settings, prompts and results scroll.
        panel=QWidget();layout=QVBoxLayout(panel);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.ai_scroll,1)
        footer=QWidget();actions=QVBoxLayout(footer);actions.setContentsMargins(10,6,10,10);row=QHBoxLayout()
        self.ai_target=label('현재 선택: 없음 · 새 형상 또는 전체 설계 명령',True);self.ai_target.setObjectName('aiSelectionTarget');actions.addWidget(self.ai_target)
        self.generate_button=button('초안 생성',self.generate_draft,True);row.addWidget(self.generate_button)
        self.cancel_ai_button=button('생성 취소',self.cancel_ai);self.cancel_ai_button.hide();row.addWidget(self.cancel_ai_button);actions.addLayout(row)
        self.accept_draft=button('미리보기 / 적용',self.preview_draft,True);self.accept_draft.setEnabled(False);row.addWidget(self.accept_draft);layout.addWidget(footer)
        self.ai_mode.currentIndexChanged.connect(self.ai_mode_changed)
        self.ai_dock=self.dock('설계 명령 / AI','aiDock',Qt.DockWidgetArea.RightDockWidgetArea,panel);self.tabifyDockWidget(self.property_dock,self.ai_dock);self.property_dock.raise_();self.ai_dock.hide()
    def reference_dialog(self):
        if self.ai_task:return
        from .reference_dialog import ReferenceDialog
        dialog=ReferenceDialog(self)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:self.set_references(dialog.refs)
        finally:dialog.deleteLater()
    def set_references(self,refs):
        from ..references import merge_references
        self.reference_materials=merge_references([],refs)
        self.chat_history=[];self.chat_identity=None;self.last_draft=None;self.ai_retained_draft=None
        self.accept_draft.setEnabled(False)
        self.reference_status.setText('참고자료 없음' if not refs else f'참고자료 {len(refs)}개 · {sum(len(r.text) for r in self.reference_materials):,}자 · AI에 전송')
        self.reference_status.setToolTip('\n'.join(r.name+' · '+r.source for r in self.reference_materials))
    def openai_setup(self):
        from .openai_setup import OpenAISetupDialog
        dialog=OpenAISetupDialog(self,self.key.text(),self.model.text())
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            key=dialog.key.text().strip()
            if not key and not os.getenv('OPENAI_API_KEY','').strip():return
            self.key.setText(key);self.model.setText(dialog.model.text().strip());self.provider.setCurrentIndex(self.provider.findData('openai'));self.ai_settings_toggle.setChecked(True)
            self.ai_dock.show();self.ai_dock.raise_();self.ai_scroll.ensureWidgetVisible(self.key);self.key.setFocus()
            self.message('API 키를 입력했습니다. 모델을 선택하고 설계 초안 생성을 누르세요. 인증은 요청 시 확인합니다.')
        finally:
            dialog.key.clear();dialog.deleteLater()
    def codex_setup(self):
        if self.ai_task:return
        from .codex_setup import CodexSetupDialog
        dialog=CodexSetupDialog(self)
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            self.codex_config=dict(executable=dialog.executable_path,model=dialog.model_name);self.codex_catalog=dialog.catalog;self.codex_connection_verified=True
            self.codex_models.set_catalog(self.codex_catalog,self.codex_config['model'])
            from .codex_usage import usage_text
            self.codex_usage.setText(usage_text(dialog.usage))
            self.codex_status.setText('✓ Codex 연결 완료');self.codex_status.setStyleSheet('color:#8dd7c0;')
            self.provider.setCurrentIndex(self.provider.findData('codex'));self.provider_changed()
            self.ai_dock.show();self.ai_dock.raise_();self.message('Codex에 연결했습니다. 설계 명령을 입력하고 초안 생성을 누르세요.')
        finally:dialog.deleteLater()
    def check_codex_status(self):
        if self.codex_probe_task or self.ai_task:return
        from .codex_connection import connect
        from .ai_task import AITask
        config=dict(self.codex_config);self.codex_connection_verified=False;self.codex_status.setText('Codex · 연결 확인 중…');self.codex_check_button.setEnabled(False);self.codex_models.setEnabled(False)
        self.codex_usage.setText('Codex 주간 · 조회 중…')
        task=AITask(lambda control,progress:connect(config['executable'],control=control,progress=progress),self);self.codex_probe_task=task
        def completed(packet):
            sender,result=packet
            if sender is not self.codex_probe_task:return
            self.codex_probe_task=None;self.codex_check_button.setEnabled(not self.ai_task);self.codex_models.setEnabled(not self.ai_task)
            if config!=self.codex_config:self.codex_status.setText('Codex · 설정 변경됨 · 다시 확인하세요.');self.codex_usage.setText('Codex 주간 · 잔여량 확인 전');return
            from .codex_usage import usage_text
            self.codex_usage.setText(usage_text(result.get('usage')))
            self.codex_catalog=result['models'];available={m['model'] for m in result['models']};self.codex_connection_verified=True
            self.codex_models.set_catalog(self.codex_catalog,self.codex_config['model'])
            if self.provider.currentData()=='codex':self.update_codex_effort()
            ready=config['model'] in available
            self.codex_status.setText('✓ Codex 연결 완료 · '+result['account'].get('plan','') if ready else 'Codex · 로그인 확인됨 · 사용할 모델을 선택하세요.')
            self.codex_status.setStyleSheet('color:#8dd7c0;' if ready else 'color:#f5c26b;')
        def failed(packet):
            sender,message=packet
            if sender is not self.codex_probe_task:return
            self.codex_probe_task=None;self.codex_connection_verified=False;self.codex_check_button.setEnabled(not self.ai_task);self.codex_models.setEnabled(not self.ai_task);self.codex_status.setText('Codex · 연결 확인 실패');self.codex_status.setStyleSheet('color:#ffab91;');self.codex_status.setToolTip(message)
            self.codex_usage.setText('Codex 주간 · 잔여량 확인 불가')
        task.completed.connect(completed,Qt.ConnectionType.QueuedConnection);task.failed.connect(failed,Qt.ConnectionType.QueuedConnection);task.start()
    def select_codex_model(self,model):
        if self.ai_task or self.codex_probe_task:return
        if not any(item['model']==model for item in self.codex_catalog):return
        from .codex_connection import save_settings
        try:save_settings(self.codex_config['executable'],model)
        except Exception as exc:
            self.codex_models.set_catalog(self.codex_catalog,self.codex_config['model']);self.show_error(str(exc));return
        self.codex_config={**self.codex_config,'model':model};self.codex_model_label.setText('Codex 모델: '+model)
        if self.codex_connection_verified:self.codex_status.setText('✓ Codex 연결 완료 · 모델 선택됨');self.codex_status.setStyleSheet('color:#8dd7c0;')
        if self.provider.currentData()=='codex':self.update_codex_effort()
        self.last_draft=None;self.ai_retained_draft=None;self.accept_draft.setEnabled(False);self.chat_history=[];self.chat_identity=None
        self.message('Codex 모델 선택: '+model+' · 다음 요청부터 적용됩니다.')
    def update_codex_effort(self):
        if not hasattr(self,'cloud_effort'):return
        chosen=self.cloud_effort.currentData() or 'medium'
        selected=next((item for item in self.codex_catalog if item['model']==self.codex_config['model']),None)
        efforts=(selected.get('efforts') or []) if selected else ['low','medium','high']
        names={'none':'추론 없음','minimal':'추론 · 최소','low':'추론 · 빠르게','medium':'추론 · 균형','high':'추론 · 깊게','xhigh':'추론 · 매우 깊게','max':'추론 · 최대','ultra':'추론 · 가장 깊게'}
        self.cloud_effort.blockSignals(True);self.cloud_effort.clear()
        for effort in efforts:
            if effort in names:self.cloud_effort.addItem(names[effort],effort)
        index=self.cloud_effort.findData(chosen)
        if index<0:index=self.cloud_effort.findData('medium')
        self.cloud_effort.setCurrentIndex(index if index>=0 else (0 if self.cloud_effort.count() else -1));self.cloud_effort.blockSignals(False)
    def refresh_ai_target(self):
        if not hasattr(self,'ai_target'):return
        raw=self.document.design or {};names={p['id']:p['name'] for p in raw.get('parts',[])}
        mate=next((m for m in raw.get('mates',[]) if m['id']==getattr(self,'selected_joint',None)),None)
        part=next((p for p in raw.get('parts',[]) if p['id']==self.selected),None)
        feature=next((f for f in (part or {}).get('features',[]) if f['id']==getattr(self,'selected_feature',None)),None)
        if mate:text='관절 '+mate['id']+' · '+names[mate['parent']]+' → '+names[mate['child']]
        elif feature:text=part['name']+' / '+feature['name']
        elif len(self.selected_parts)>1:text=f'부품 {len(self.selected_parts)}개 · 명령에 바꿀 부품을 지정하세요'
        elif part:text=part['name']
        elif self.selected_sketch:text='스케치 · 원본 편집은 스케치 편집 도구를 사용하세요'
        else:text='없음 · 새 형상 또는 전체 설계 명령'
        self.ai_target.setText('현재 선택: '+(text if len(text)<=65 else text[:62]+'…'));self.ai_target.setToolTip(text)
    def message(self,text):self.statusBar().showMessage(text,15000)
    def title(self):
        self.setWindowTitle((self.document.design['name'] if self.document.design else '새 설계')+(' *' if self.document.dirty else '')+' — '+APP_NAME+' v'+__version__+' · Native')
        if self.workspace.currentData()=='circuit' and not self.sketching:self.refresh_circuit_workspace()
        self.refresh_wiring_diagram()
    def about_dialog(self):
        QMessageBox.about(self,APP_NAME,f'Prompt CAD Studio v{__version__}\nWindows native CAD · Qt / VTK / Open CASCADE\n\nUnits: mm\nProject + history: .cad.json\nDirect geometry export: STEP / STL\nF3D: requires Fusion · IPT: requires Inventor\nAutodesk conversion transfers geometry, not the feature timeline.')
    def change_language(self,code):
        try:self.language_service.set_language(code)
        except OSError:self.show_error('언어 설정을 저장하지 못했습니다.')
        self.editor.canvas.update()
        if self.workspace.currentData()=='circuit':self.refresh_circuit_workspace()
        self.refresh_wiring_diagram()
    def display_style_dialog(self):
        from .display_style import DisplayStyleDialog
        DisplayStyleDialog(self).exec()
    def toggle_display(self,key,visible):
        if key=='grid':self.viewport.show_grid(visible);self.editor.grid_visible=visible
        else:self.viewport.show_axes(visible);self.editor.axes_visible=visible
        self.editor.canvas.update()
    def set_busy(self,busy,message=''):
        self.busy=busy;self.progress.setVisible(busy);self.toolbar.setEnabled(not busy and not self.sketching);self.tree.setEnabled(not busy and not self.sketching);self.properties.setEnabled(not busy);self.timeline.setEnabled(not busy and not self.sketching);self.generate_button.setEnabled(not busy and not self.sketching and self.ai_task is None);self.accept_draft.setEnabled(not busy and not self.sketching and self.last_draft is not None);self.editor.setEnabled(not busy)
        for key,a in self.actions.items():a.setEnabled(not busy and (not self.sketching or key in ('undo','redo','fit','grid','axes','about')))
        if message:self.message(message)
    def run(self,fn,done,message='CAD 형상 계산 중…',failed=None):
        if self.busy:return
        self.set_busy(True,message);worker=Worker(fn);self.worker=worker
        def complete(result):
            self.set_busy(False)
            try:done(result)
            except Exception as exc:self.show_error(str(exc))
        def error(text):
            self.set_busy(False)
            if failed:failed(text)
            else:self.show_error(text)
        worker.signals.done.connect(complete);worker.signals.failed.connect(error);QThreadPool.globalInstance().start(worker)
    def show_error(self,text):
        self.message(text[:500]);QMessageBox.warning(self,'작업을 완료하지 못했습니다',text[:2400])
    def apply_design(self,data,title,context=None,fit=False,cursor=None,after=None):
        context=context or {};raw=deepcopy(data);baseline=deepcopy(self.document.design);previous_result=self.result
        def work():
            with KERNEL_LOCK:
                from ..preview_metadata import reuse_preview
                d=Design.model_validate(raw)
                cached=reuse_preview(d,baseline,previous_result)
                r=cached if cached is not None else preview(d)
                if context.get('tool')=='prompt':
                    from ..interference import validate_candidate
                    validate_candidate(d,baseline,collisions=r['stats']['collisions'])
                from ..interference import check_joint_travel,travel_message
                if baseline:
                    travel=check_joint_travel(baseline,d)
                    if travel and travel['blocked']:raise ValueError(travel_message(d,travel))
                return d,r,cached is not None
        def done(result):
            d,preview_result,reused=result;self.document.commit(d,title,context,cursor)
            self.result=preview_result;self.operation_serial+=1
            render=self.viewport.update_metadata if reused else self.viewport.load
            render(self.result,fit or len(d.parts)==1 and not self.selected)
            self.refresh_role_view()
            if self.role_view is None and (not self.selected or all(p.id!=self.selected for p in d.parts)):self.selected=d.parts[0].id if d.parts else None
            self.rebuild_tree();remaining=[i for i in self.selected_parts if any(p.id==i for p in d.parts)];self.select_parts(remaining or ([self.selected] if self.selected else []));self.viewport.joints.set_design(d);self.rebuild_timeline();self.autosave_document();self.title();self.message(title+(' · 간섭 경고: 뷰포트 위의 간섭 버튼을 눌러 확인하세요.' if self.result['stats']['collisions'] else ' · 저장 가능한 유효한 CAD 형상입니다.'))
            if self.workspace.currentData()=='circuit':self.refresh_circuit_workspace()
            if after:after()
        self.run(work,done,failed=self.editor.error if self.sketching else None)
    def autosave_document(self):
        if self.document.design:
            try:self.document.write(self.autosave,autosave=True)
            except Exception as exc:self.message('자동 저장 실패: '+str(exc))
    def part(self):return next((p for p in (self.document.design or {}).get('parts',[]) if p['id']==self.selected),None)
    def rebuild_tree(self):
        self.tree.blockSignals(True);self.tree.clear();root=QTreeWidgetItem([self.document.design['name'] if self.document.design else '새 설계']);root.setIcon(0,icon('assembly'));self.tree.addTopLevelItem(root);origin=QTreeWidgetItem(root,['원점 / 기준 평면']);origin.setIcon(0,icon('origin'))
        for plane in ('XY','XZ','YZ'):
            i=QTreeWidgetItem(origin,[plane+' 평면']);i.setData(0,Qt.ItemDataRole.UserRole,('plane',plane))
        if self.document.design:
            sketches=QTreeWidgetItem(root,['스케치']);sketches.setIcon(0,icon('sketch'));sketches.setExpanded(True)
            for saved in self.document.design.get('sketches',[]):
                item=QTreeWidgetItem(sketches,[saved['name']]);item.setData(0,Qt.ItemDataRole.UserRole,('sketch',saved['id']));item.setIcon(0,icon('sketch'))
            group_nodes={}
            for group in self.document.design.get('part_groups',[]):
                folder=QTreeWidgetItem(root,[group['name']+f" · {len(group['part_ids'])}개"]);folder.setIcon(0,icon('assembly'));folder.setData(0,Qt.ItemDataRole.UserRole,('group',group['id']));folder.setExpanded(True)
                for identifier in group['part_ids']:group_nodes[identifier]=folder
            for part in self.document.design['parts']:
                node=QTreeWidgetItem(group_nodes.get(part['id'],root),[part['name']+(' · 고정' if part['fixed'] else '')]);node.setIcon(0,icon('extrude'));node.setData(0,Qt.ItemDataRole.UserRole,('part',part['id']));node.setFlags(node.flags()|Qt.ItemFlag.ItemIsUserCheckable);node.setCheckState(0,Qt.CheckState.Unchecked if part['id'] in self.viewport.hidden else Qt.CheckState.Checked)
                base=QTreeWidgetItem(node,['기본 · '+TITLES[part['geometry']['kind']]]);base.setData(0,Qt.ItemDataRole.UserRole,('base',part['id']));base.setIcon(0,icon('sketch' if part['geometry']['kind']=='extrusion' else 'extrude'))
                for f in part['features']:
                    item=QTreeWidgetItem(node,[f['name']]);item.setData(0,Qt.ItemDataRole.UserRole,('feature',part['id'],f['id']));item.setIcon(0,icon('cut' if f.get('operation')=='cut' else 'extrude'))
                    if f.get('kind') in ('fillet','chamfer'):QTreeWidgetItem(item,[f"모서리 {len(f['edges'])}개 · {f['size']:g} mm · 기준 {f['support_feature']}"])
                    elif f.get('kind')=='thread':QTreeWidgetItem(item,[f"원통 면 {f['cylinder']['index']+1} · 피치 {f['pitch']:g} mm · 길이 {f['length']:g} mm · 기준 {f['support_feature']}"])
                    elif f.get('kind')=='solid':QTreeWidgetItem(item,[f"{f['operation']} · 기준 {f['support_feature']}"+(' · 억제됨' if f.get('suppressed') else '')])
                    else:
                        support=QTreeWidgetItem(item,[f"면 {f['face']+1} · 기준 {f['support_feature']} · {f['sketch']['thickness']:g} mm"])
                        for c in f['sketch'].get('entity_constraints',[]):QTreeWidgetItem(support,[f"{c['kind']} · {c['a'][:7]} → {c.get('b','')[:7]}"])
                for component in (self.document.design.get('electrical') or {}).get('components',[]):
                    if component.get('part_id')!=part['id']:continue
                    feature=QTreeWidgetItem(node,['전장 피처 · '+component['name']]);feature.setIcon(0,icon('assembly'));feature.setData(0,Qt.ItemDataRole.UserRole,('electrical_feature',part['id'],component['id']))
                    QTreeWidgetItem(feature,[component.get('catalog_id') or '사용자 정의'])
                    QTreeWidgetItem(feature,['DC 계산 포함' if component.get('analysis_enabled',True) else '정격 입력 전 · DC 계산 제외'])
                    feature.setExpanded(True)
                node.setExpanded(True)
            mates=QTreeWidgetItem(root,['조립 구속']);mates.setIcon(0,icon('assembly'))
            for mate in self.document.design['mates']:
                item=QTreeWidgetItem(mates,[mate['kind']+' · '+mate['parent']+' → '+mate['child']]);item.setData(0,Qt.ItemDataRole.UserRole,('mate',mate['id']))
            for loop in self.document.design.get('loops',[]):
                item=QTreeWidgetItem(mates,['폐루프 · '+loop['name']]);item.setData(0,Qt.ItemDataRole.UserRole,('loop',loop['id']))
            mates.setExpanded(True)
            electrical=self.document.design.get('electrical')
            if electrical:
                circuit=QTreeWidgetItem(root,[electrical['name']+f" · 전장 {len(electrical['components'])}개"])
                circuit.setIcon(0,icon('assembly'));circuit.setData(0,Qt.ItemDataRole.UserRole,('electrical',))
                for component in electrical['components']:
                    item=QTreeWidgetItem(circuit,[component['name']+' · '+component['kind']])
                    item.setData(0,Qt.ItemDataRole.UserRole,('electrical',component['id']))
                circuit.setExpanded(True)
            studies=QTreeWidgetItem(root,['도면 / 해석']);studies.setExpanded(True)
            for study in self.document.design.get('studies',[]):
                item=QTreeWidgetItem(studies,[study['name']]);item.setData(0,Qt.ItemDataRole.UserRole,('study',study['id'],study['kind']))
        root.setExpanded(True);self.tree.blockSignals(False)
    def visibility_changed(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if data and data[0]=='part':
            visible=item.checkState(0)==Qt.CheckState.Checked
            if self.role_view is not None:
                self.reset_role_view();self.viewport.visibility(data[1],visible);self.sync_tree_visibility();self.sync_tree_selection()
            else:self.viewport.visibility(data[1],visible)
    def sync_tree_visibility(self):
        # itemChanged is emitted inside QTreeWidgetItem.setCheckState. Clearing
        # the tree here deletes its C++ emitter before that call has returned.
        # Visibility changes only need checkbox updates; preserve every row,
        # current iterator, selection and expanded state.
        with QSignalBlocker(self.tree):
            iterator=QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                item=iterator.value();data=item.data(0,Qt.ItemDataRole.UserRole)
                if data and data[0]=='part':
                    item.setCheckState(0,Qt.CheckState.Unchecked if data[1] in self.viewport.hidden else Qt.CheckState.Checked)
                iterator+=1
    def tree_clicked(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data:return
        if data[0] in ('part','base','feature','group'):self.viewport.clear_face()
        if data[0]=='sketch':self.select_sketch(data[1])
        elif data[0]=='feature' and len(self.selected_parts)==1:self.show_feature(data[2])
        elif data[0]=='mate':self.show_mate(data[1])
        elif data[0]=='loop':self.show_loop(data[1])
        elif data[0]=='study':self.show_study(data[1],data[2])
        elif data[0]=='electrical_feature':self.show_electrical_cad_part(data[1]);self.open_wiring_diagram(data[2])
        elif data[0]=='electrical':self.message('전장 회로를 더블클릭하면 배선과 전압강하를 확인할 수 있습니다.')
        elif data[0]=='plane':self.plane.setCurrentIndex(self.plane.findData(data[1]));self.message(data[1]+' 평면 선택 · 스케치 작성 버튼을 누르세요.')
    def tree_edit(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data or self.busy or self.sketching:return
        if data[0]=='sketch':self.edit_saved_sketch(data[1])
        elif data[0]=='plane':self.start_sketch(data[1])
        elif data[0]=='feature':self.edit_sketch(data[2])
        elif data[0]=='base' and self.part()['geometry']['kind']=='extrusion':self.edit_sketch()
        elif data[0]=='mate':self.mate_dialog(data[1])
        elif data[0]=='loop':self.closure_dialog(data[1])
        elif data[0]=='study' and data[2] in ('robot','tensile','drawing','fit'):self.study_dialog(data[2],data[1])
        elif data[0]=='electrical_feature':self.electrical_part_dialog(data[1])
        elif data[0]=='electrical':self.electrical_dialog()
        elif data[0]=='base' and self.part()['geometry']['kind'] in ('sweep','loft'):self.modelling_dialog(self.part()['geometry']['kind'],part_id=data[1])
    def select_part(self,identifier):
        self.select_clicked_parts([identifier] if identifier else [])
    def select_sketch(self,identifier):
        self.selected_feature=None
        self.selected_joint=None
        self.selected_sketch=identifier;self.selected_profile=None;self.selected=None;self.selected_parts=[];self.viewport.select(None);self.viewport.clear_face();self.sync_tree_selection()
        self.refresh_ai_target();saved=next((s for s in (self.document.design or {}).get('sketches',[]) if s['id']==identifier),None)
        if not saved:return
        clear_layout(self.property_layout);self.property_layout.addWidget(label(saved['name'],user_text=True));self.property_layout.addWidget(label(f"{len(saved['geometry']['entities'])}개 요소 · 단위 mm",True));self.property_layout.addWidget(button('스케치 편집',lambda:self.edit_saved_sketch(identifier),True));self.property_layout.addWidget(button('3D 돌출 / 절삭 · E',lambda:self.extrude_dialog(sketch_id=identifier)))
        if not saved['context'].get('face') and not saved['context'].get('part_id'):
            self.property_layout.addWidget(button('작업 평면 · 위치 / 각도 편집',lambda:self.work_plane_dialog(identifier)))
            self.property_layout.addWidget(button('같은 평면에 새 스케치',lambda:self.start_sketch(context={**deepcopy(saved['context']),'title':saved['name']+' · 같은 평면의 새 스케치'})))
        def remove():
            data=deepcopy(self.document.design);data['sketches']=[s for s in data['sketches'] if s['id']!=identifier];self.selected_sketch=None;remove_bindings(data,['sketches',identifier]);self.apply_design(data,'스케치 삭제',{'sketch_id':identifier})
        self.property_layout.addWidget(button('스케치 삭제',remove));self.property_layout.addStretch();self.property_dock.show();self.property_dock.raise_()
    def edit_saved_sketch(self,identifier,extrude=False):
        if extrude:self.extrude_dialog(sketch_id=identifier);return
        saved=next((s for s in (self.document.design or {}).get('sketches',[]) if s['id']==identifier),None)
        if not saved:return
        context=deepcopy(saved['context']);context.update(sketch_id=identifier,title=saved['name']);self.start_sketch(g=saved['geometry'],context=context)
        if extrude:self.editor.tabs.setCurrentIndex(3)
    def face_selected(self,identifier,face):
        if self.joint_picks is not None:self.receive_joint_face(identifier,face);return
        self.show_properties()
        if face:
            self.property_layout.insertWidget(1,label(f"선택 면 {face['index']+1} · "+('평면' if face['planar'] else '곡면')))
            if face.get('cylinder'):
                self.property_layout.insertWidget(2,button('이 면에 '+('암나사' if face['cylinder']['internal'] else '수나사')+' 만들기 · T',self.thread_dialog,True))
            if face['planar']:
                self.property_layout.insertWidget(2,button('이 면에서 스케치',self.start_face_sketch,True));self.property_layout.insertWidget(3,button('이 면에 구멍 뚫기',self.hole_dialog))
                if self.document.design.get('sketches'):self.property_layout.insertWidget(4,button('저장 스케치 / 그룹 재사용',self.reuse_sketch_on_face))
    def show_properties(self):
        self.selected_feature=None
        self.selected_joint=None;self.refresh_ai_target()
        clear_layout(self.property_layout);part=self.part()
        if len(self.selected_parts)>1:self.selection_properties();return
        if not part:
            self.property_layout.addWidget(label('사람이 설계하고, 필요할 때 AI를 사용하세요.'));self.property_layout.addWidget(label('① 기준 평면 선택\n② 스케치 작성\n③ 닫힌 영역 돌출\n④ 면 선택 → 스케치 → 구멍 / 돌출',True));self.property_layout.addWidget(button('XY 평면에 스케치',lambda:self.start_sketch('XY'),True));self.property_layout.addWidget(button('시편 치수 설계',self.specimen_dialog));self.property_layout.addWidget(button('로봇 조립 설계',self.robot_dialog));self.property_layout.addWidget(button('전장 회로 / 배선 설계',self.electrical_dialog));self.property_layout.addStretch();return
        heading=label(part['name'],user_text=True);heading.setStyleSheet('font-size:17px;font-weight:600;');self.property_layout.addWidget(heading);form=QFormLayout();name=QLineEdit(part['name']);name.setObjectName('partName');form.addRow('부품 이름',name);inputs={};g=part['geometry'];changed_dimensions=set()
        self.property_layout.addWidget(button('부품 이름 변경 · F2',self.rename_part))
        product_button=button('제품 스펙 / 공식 자료 / 구매 링크…',lambda:self.part_product_dialog(part['id']))
        product_button.setObjectName('partProductButton');self.property_layout.addWidget(product_button)
        group=next((g for g in self.document.design.get('part_groups',[]) if part['id'] in g['part_ids']),None)
        self.property_layout.addWidget(button('선택 부품만 보기 / 돌아오기',self.isolate_parts))
        self.property_layout.addWidget(button('이 부품 STEP / STL 내보내기',self.export_selected_parts))
        electrical=(self.document.design.get('electrical') or {}).get('components',[])
        linked=[c['name'] for c in electrical if c.get('part_id')==part['id']]
        registration=button('전장 피처 · 모델 / 모식도 편집' if linked else '이 CAD 부품을 전장으로 등록…',lambda:self.electrical_part_dialog(part['id']),not bool(linked));registration.setObjectName('partElectricalRegister');self.property_layout.addWidget(registration)
        if linked:self.property_layout.addWidget(button('전장 연결 · '+', '.join(linked[:2]),self.electrical_dialog))
        if group:
            self.property_layout.addWidget(button(group['name']+' · 그룹 전체 선택',lambda:self.select_parts(group['part_ids'])))
            self.property_layout.addWidget(button('그룹 해제 · Ctrl+Shift+G',self.ungroup_parts))
        for key,value in g.items():
            if key not in FIELDS:continue
            title,unit=FIELDS[key]
            if key=='pressure_angle':w=combo([(n,str(n)+'°') for n in (20,25)]);w.setCurrentIndex(w.findData(value))
            elif key=='teeth':w=combo([(n,str(n)) for n in range(18,81)]);w.setCurrentIndex(w.findData(value))
            elif key=='hole_count':w=combo([(n,str(n)) for n in (0,2,4)]);w.setCurrentIndex(w.findData(value))
            else:w=ExpressionField(value,0 if key in ('bore_diameter','flat_depth','backlash','shaft_diameter','shaft_length') else .01,2000,' '+unit,variables=parameter_values(self.document.design.get('parameters',{})),expression=binding_for(self.document.design,['parts',part['id'],'geometry',key]) or (g.get('thickness_expression','') if key=='thickness' else ''))
            inputs[key]=w;w.setObjectName('partDimension_'+key);form.addRow(title,w)
            signal=w.currentIndexChanged if isinstance(w,QComboBox) else w.valueChanged
            signal.connect(lambda *args,field=key:changed_dimensions.add(field))
        self.property_layout.addWidget(button('이동 / 회전 · M',self.move_parts))
        color_button=button('●  부품 색상 변경',lambda:self.color_part(part['id']));color_button.setObjectName('partColorButton');color_button.setStyleSheet(f"border-left:6px solid {part['color']};text-align:left;padding:8px;");self.property_layout.addWidget(color_button);self.property_layout.addWidget(button('재질 / 물성',self.material_dialog));self.property_layout.addLayout(form)
        self.property_layout.insertWidget(2,button('부품 역할 / 기본색…',self.role_selection))
        if part.get('source_part_id'):
            self.property_layout.addWidget(label('연결된 원본: '+part['source_part_id']+' · 형상은 원본을 따라갑니다.',True));self.property_layout.addWidget(button('원본 편집',lambda:self.select_part(part['source_part_id'])));self.property_layout.addWidget(button('연결 해제 · 독립 부품으로',self.unlink_part))
            for w in inputs.values():w.setEnabled(False)
        if g['kind'] in ('round_specimen','flat_specimen','wafer'):
            self.property_layout.insertWidget(1,button('시편 치수 · 3D 미리보기',self.specimen_dialog,True))
            self.property_layout.insertWidget(2,button('피로시험 조건 / 데이터 양식…',self.research_package_dialog))
        if any(m['child']==part['id'] and m['kind']!='rigid' for m in self.document.design['mates']):self.property_layout.insertWidget(1,button('관절 구동 · 간섭 확인',self.drive_joints,True))
        if g['kind']=='extrusion':self.property_layout.addWidget(button('돌출 깊이 · 3D 편집 E',self.extrude_dialog,True));self.property_layout.addWidget(button('기본 스케치 편집',lambda:self.edit_sketch()))
        if g['kind'] in ('sweep','loft'):self.property_layout.insertWidget(1,button(TITLES[g['kind']]+' 단면 / 경로 편집',lambda:self.modelling_dialog(g['kind'],part_id=part['id']),True))
        if g['kind']=='sheetmetal':self.property_layout.addWidget(button('판금 치수 / 전개 편집',lambda:self.sheetmetal_dialog(part_id=part['id']),True))
        if g['kind']=='revolve':self.property_layout.insertWidget(1,button('회전 단면 / 축 편집',lambda:self.revolve_dialog(part_id=part['id']),True))
        if g['kind']=='imported':self.property_layout.addWidget(label('가져온 형상은 프로젝트 안에 보관됩니다. 원본 파일 없이 다시 열 수 있습니다.',True))
        self.property_layout.addWidget(label('배치 · 원점 기준'));tform=QFormLayout();trans={};changed_transform=set()
        for key,value in part['transform'].items():
            limit=360 if key.startswith('r') else 5000
            w=ExpressionField(value,-limit,limit,' °' if key.startswith('r') else ' mm',variables=parameter_values(self.document.design.get('parameters',{})),expression=binding_for(self.document.design,['parts',part['id'],'transform',key]))
            w.setObjectName('partPlacement_'+key);trans[key]=w;tform.addRow(key.upper(),w);w.valueChanged.connect(lambda *args,axis=key:changed_transform.add(axis))
        bound=next((m for m in self.document.design['mates'] if m['child']==part['id']),None)
        if bound:
            for w in trans.values():w.setEnabled(False);w.setToolTip('조인트로 배치된 부품입니다. 관절 구동 또는 조인트 오프셋을 편집하세요.')
            self.property_layout.addWidget(button('조인트 오프셋 편집',lambda:self.mate_dialog(bound['id'])))
        self.property_layout.addLayout(tform);fixed=QCheckBox('조립 기준 부품으로 고정');fixed.setChecked(part['fixed']);fixed.setEnabled(bound is None);self.property_layout.addWidget(fixed)
        def apply():
            if self.busy:return
            data=deepcopy(self.document.design);p=next(p for p in data['parts'] if p['id']==part['id']);p['name']=name.text().strip() or part['name'];p['fixed']=fixed.isChecked()
            try:
                for key,w in inputs.items():
                    if key not in changed_dimensions:continue
                    p['geometry'][key]=w.currentData() if isinstance(w,QComboBox) else w.value()
                    if isinstance(w,ExpressionField):
                        if key=='thickness' and p['geometry']['kind']=='extrusion':p['geometry'].pop('thickness_expression',None)
                        set_binding(data,['parts',p['id'],'geometry',key],w.formula())
                for key in changed_transform:
                    w=trans[key];p['transform'][key]=w.value();set_binding(data,['parts',p['id'],'transform',key],w.formula())
            except ValueError as exc:self.show_error(str(exc));return
            self.apply_design(data,'부품 치수 / 배치 편집',{'part_id':part['id'],'tool':'parameters'})
        apply_button=button('치수 / 배치 적용',apply,True);apply_button.setObjectName('applyPartProperties');self.property_layout.addWidget(apply_button);self.property_layout.addWidget(button('부품 복제',self.duplicate_part));self.property_layout.addWidget(button('선택 부품 삭제',self.delete_part));self.property_layout.addStretch()
    def color_part(self,identifier):
        if self.busy or self.sketching:return
        if not identifier:self.message('색을 바꿀 부품을 화면이나 설계 브라우저에서 먼저 선택하세요.');return
        part=next((p for p in self.document.design['parts'] if p['id']==identifier),None)
        if part is None:return
        color=QColorDialog.getColor(QColor(part['color']),self,'부품 색상')
        if color.isValid():data=deepcopy(self.document.design);next(p for p in data['parts'] if p['id']==identifier)['color']=color.name();self.apply_design(data,'부품 색상 변경',{'part_id':identifier})
    def show_feature(self,identifier):
        self.selected_feature=identifier
        self.selected_joint=None;self.refresh_ai_target()
        f=next(f for f in self.part()['features'] if f['id']==identifier)
        if f.get('kind')=='solid':
            clear_layout(self.property_layout);self.property_layout.addWidget(label(f['name'],user_text=True));self.property_layout.addWidget(button('작업 / 치수 편집',lambda:self.solid_dialog(feature_id=identifier),True));self.property_layout.addWidget(button('이 피처와 뒤의 피처 제거',lambda:self.remove_feature(identifier)));self.property_layout.addStretch();return
        if f.get('kind')=='thread':
            clear_layout(self.property_layout);self.property_layout.addWidget(label(f['name'],user_text=True));self.property_layout.addWidget(label(f"원통 면: {f['cylinder']['index']+1}\n기준 피처: {f['support_feature']}\n시작 간격: {f['offset']:g} mm\n반경 여유: {f['clearance']:g} mm\n60° 프로파일 · 실제 모델링",True));self.property_layout.addWidget(button('나사산 / 치수 편집',lambda:self.thread_dialog(identifier),True));self.property_layout.addWidget(button('이 피처와 뒤의 피처 제거',lambda:self.remove_feature(identifier)));self.property_layout.addStretch();return
        if f.get('kind') in ('fillet','chamfer'):
            clear_layout(self.property_layout);self.property_layout.addWidget(label(f['name'],user_text=True));self.property_layout.addWidget(label(f"모서리 {len(f['edges'])}개 · {f['size']:g} mm\n기준 피처: {f['support_feature']}",True));self.property_layout.addWidget(button('모서리 / 치수 편집',lambda:self.edge_finish_dialog(identifier),True));self.property_layout.addWidget(button('이 피처와 뒤의 피처 제거',lambda:self.remove_feature(identifier)));self.property_layout.addStretch();return
        part=self.part();f=next(f for f in part['features'] if f['id']==identifier);clear_layout(self.property_layout);self.property_layout.addWidget(label(f['name'],user_text=True));self.property_layout.addWidget(label(f"부품: {part['name']}\n참조 피처: {f['support_feature']}\n선택 면: {f['face']+1}\n법선: {f['normal']}\n작업: {f['operation']}\n깊이: {f['sketch']['thickness']:g} mm\n스케치 요소: {len(f['sketch']['entities'])}\n구속: {len(f['sketch']['entity_constraints'])}",True));self.property_layout.addWidget(button('돌출 깊이 · 3D 편집',lambda:self.extrude_dialog(feature_id=identifier),True));self.property_layout.addWidget(button('스케치 / 구속 편집',lambda:self.edit_sketch(identifier))); self.property_layout.addWidget(button('이 피처와 뒤의 피처 제거',lambda:self.remove_feature(identifier)));self.property_layout.addStretch()
    def show_loop(self,identifier):
        loop=next(c for c in self.document.design['loops'] if c['id']==identifier);clear_layout(self.property_layout);self.property_layout.addWidget(label(loop['name'],user_text=True));self.property_layout.addWidget(label(loop['parent']+' → '+loop['child']+'\n자동 계산: '+', '.join(loop['passive_joints']),True));self.property_layout.addWidget(button('폐루프 편집',lambda:self.closure_dialog(identifier),True))
        def remove():
            raw=deepcopy(self.document.design);raw['loops']=[c for c in raw['loops'] if c['id']!=identifier];self.apply_design(raw,'폐루프 연결 제거',{'loop_id':identifier})
        self.property_layout.addWidget(button('폐루프 제거',remove));self.property_layout.addStretch()
    def show_study(self,identifier,kind):
        study=next(s for s in self.document.design['studies'] if s['id']==identifier);clear_layout(self.property_layout);self.property_layout.addWidget(label(study['name'],user_text=True));self.property_layout.addWidget(label('저장한 조건을 현재 형상에 적용해 다시 계산할 수 있습니다.',True))
        if kind in ('robot','tensile','drawing','fit'):self.property_layout.addWidget(button('열기 / 다시 계산',lambda:self.study_dialog(kind,identifier),True))
        else:self.property_layout.addWidget(label(json.dumps(study['settings'],ensure_ascii=False,indent=2),True))
        def remove():
            raw=deepcopy(self.document.design);raw['studies']=[s for s in raw['studies'] if s['id']!=identifier];self.apply_design(raw,'도면 / 해석 조건 삭제',{'study_id':identifier})
        self.property_layout.addWidget(button('조건 삭제',remove));self.property_layout.addStretch()
    def remove_feature(self,identifier):
        if not self.independent_shape():return
        data=deepcopy(self.document.design);p=next(p for p in data['parts'] if p['id']==self.selected);i=next(i for i,f in enumerate(p['features']) if f['id']==identifier);removed=p['features'][i:];p['features']=p['features'][:i];remove_bindings(data,*[['parts',p['id'],'features',f['id']] for f in removed]);self.apply_design(data,'피처 제거',{'part_id':p['id'],'removed_features':[f['id'] for f in removed]})
    def add_preset(self,kind):
        if kind=='sheetmetal':self.sheetmetal_dialog();return
        if kind=='revolve':self.revolve_dialog();return
        if kind=='imported':self.import_model();return
        if self.busy or self.sketching:return
        if kind=='robot_arm':self.robot_dialog();return
        if kind in ('sweep','loft'):self.modelling_dialog(kind);return
        if self.document.design:
            data=deepcopy(self.document.design);p=part_default(kind,'part-'+uid()).model_dump();p['transform']['x']=(self.result['stats']['max'][0]+80) if self.result else 100;data['parts'].append(p)
        else:data=preset(kind).model_dump()
        self.apply_design(data,TITLES[kind]+' 생성',{'tool':'primitive','kind':kind},fit=True)
    def duplicate_part(self):
        if not self.part() or self.busy:return
        from ..part_operations import duplicate_parts
        try:data,ids=duplicate_parts(self.document.design,self.selected_ids())
        except Exception as exc:self.show_error(str(exc));return
        self.apply_design(data,'부품 복제',{'part_ids':ids},fit=True,after=lambda:self.select_parts(ids))
    def delete_part(self):
        self.delete_selection()
    def work_plane_dialog(self,sketch_id=None):
        if self.busy or self.sketching:return
        from .work_plane import WorkPlaneDialog
        sketch_id=sketch_id if isinstance(sketch_id,str) else None
        saved=next((s for s in (self.document.design or {}).get('sketches',[]) if s['id']==sketch_id),None)
        ctx=(saved or {}).get('context',{})
        plane=ctx.get('work_plane') or {'plane':ctx.get('plane',self.plane.currentData() if self.plane.currentData()!='custom' else 'XY')}
        dialog=WorkPlaneDialog(self,self.document.design,plane,sketch_id)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            plane,design=dialog.checked
            if sketch_id:self.apply_design(design.model_dump(),'스케치 작업 평면 편집',{'tool':'work-plane','sketch_id':sketch_id,'work_plane':plane.model_dump()},fit=True,after=lambda:self.select_sketch(sketch_id))
            else:self.start_sketch(context={'work_plane':plane.model_dump(),'title':f'사용자 작업 평면 · {plane.plane} · {plane.offset:g} mm'})
    def start_sketch(self,plane='XY',g=None,context=None):
        if self.busy or self.sketching:return
        if plane=='custom' and not context:self.work_plane_dialog();return
        if self.joint_picks is not None:self.cancel_joint_pick()
        context=context or {'plane':plane,'title':f'새 스케치 · {plane} 기준 평면'};self.sketching=True;self.editor.start(g,context,parameter_values((self.document.design or {}).get('parameters',{})));self.stack.setCurrentWidget(self.editor);self.property_dock.hide();self.ai_dock.hide();self.browser_dock.hide();self.timeline_dock.hide();self.toolbar.hide();self.set_busy(False);self.editor.tabs.setCurrentIndex(0)
    def start_face_sketch(self):
        if not self.independent_shape():return
        if not self.viewport.face:self.message('3D 모델의 평평한 면을 먼저 클릭하세요.');return
        identifier,face=self.viewport.face
        if not face or not face['planar']:self.message('곡면에는 스케치를 시작할 수 없습니다. 평평한 면을 선택하세요.');return
        part=next(p for p in self.document.design['parts'] if p['id']==identifier);context={'part_id':identifier,'face':deepcopy(face),'support_feature':part['features'][-1]['id'] if part['features'] else 'base','title':f"{part['name']} · 면 {face['index']+1} 스케치"};self.start_sketch(context=context)
    def reuse_sketch_on_face(self,sketch_id=None):
        if self.busy or self.sketching or not self.viewport.face:return
        identifier,face=self.viewport.face
        if not face or not face['planar']:self.message('스케치를 재사용할 평평한 면을 선택하세요.');return
        sketches=(self.document.design or {}).get('sketches',[])
        if not sketches:return
        if not isinstance(sketch_id,str):
            names=[f"{i+1}. {s['name']} · 그룹 {len(s['geometry'].get('groups',[]))}개" for i,s in enumerate(sketches)]
            choice,ok=QInputDialog.getItem(self,'스케치 / 그룹 재사용','선택 면에 복사할 스케치',names,0,False)
            if not ok:return
            sketch_id=sketches[names.index(choice)]['id']
        saved=next(s for s in sketches if s['id']==sketch_id);part=next(p for p in self.document.design['parts'] if p['id']==identifier)
        context=dict(part_id=identifier,face=deepcopy(face),support_feature=part['features'][-1]['id'] if part['features'] else 'base',title=saved['name']+' · 선택 면에서 재사용',source_sketch_id=sketch_id,operation='cut')
        self.start_sketch(g=saved['geometry'],context=context);self.editor.tabs.setCurrentIndex(3);self.editor.status.setText('선택 면의 좌표계에 복사했습니다. 위치·영역·깊이를 확인하고 돌출 또는 절삭하세요.')
    def edit_sketch(self,feature_id=None):
        if not self.independent_shape():return
        if isinstance(feature_id,bool):feature_id=None
        item=self.tree.currentItem();data=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if feature_id is None and data and data[0]=='feature' and data[1]==self.selected:feature_id=data[2]
        if self.selected_sketch:self.edit_saved_sketch(self.selected_sketch);return
        p=self.part()
        if not p:return
        if feature_id:
            f=next(f for f in p['features'] if f['id']==feature_id)
            if f.get('kind')=='solid':self.solid_dialog(feature_id=feature_id);return
            if f.get('kind') in ('fillet','chamfer'):self.edge_finish_dialog(feature_id);return
            if f.get('kind')=='thread':self.thread_dialog(feature_id);return
            self.start_sketch(g=f['sketch'],context=dict(part_id=p['id'],feature_id=f['id'],operation=f['operation'],title=f['name']+' 편집'));return
        if p['geometry']['kind']!='extrusion':self.message('이 부품은 치수로 편집합니다. 새 구멍은 면을 선택해 스케치를 만드세요.');return
        g=deepcopy(p['geometry']);expr=binding_for(self.document.design,['parts',p['id'],'geometry','thickness'])
        if expr:g['thickness_expression']=expr
        self.start_sketch(g=g,context=dict(part_id=p['id'],edit_base=True,title=p['name']+' · 기본 스케치 편집'))
    def cancel_sketch(self):
        if self.busy:return
        self.sketching=False;self.editor.stop();self.stack.setCurrentWidget(self.viewport);self.toolbar.show();self.ai_dock.show();self.browser_dock.show();self.property_dock.show();self.timeline_dock.show();self.set_busy(False);self.show_properties();self.viewport.window.Render()
    def finish_sketch(self,g,context,operation):
        if self.busy:return
        # Editing a solid's generating sketch still recomputes that feature.
        # New/open sketches can finish without creating a solid at all.
        if context.get('edit_base') or context.get('feature_id'):
            self.apply_sketch(g,context,operation);return
        if not g['entities'] and not context.get('sketch_id'):self.cancel_sketch();return
        data=deepcopy(self.document.design) if self.document.design else dict(name='스케치 설계',parts=[],mates=[],sketches=[])
        identifier=context.get('sketch_id') or 'sketch-'+uid();saved_context={k:deepcopy(v) for k,v in context.items() if k not in ('tool_actions','sketch_id','source_sketch_id')};saved_context['operation']=operation
        old=next((s for s in data.get('sketches',[]) if s['id']==identifier),None)
        saved=dict(id=identifier,name=old['name'] if old else '스케치 '+str(len(data.get('sketches',[]))+1),geometry=g,context=saved_context)
        data['sketches']=[s for s in data.get('sketches',[]) if s['id']!=identifier]+[saved]
        context.update(tool='sketch',sketch_id=identifier,sketch=g)
        def complete():self.cancel_sketch();self.select_sketch(identifier)
        self.apply_design(data,'스케치 종료 · '+saved['name'],context,fit=True,after=complete)
    def apply_sketch(self,g,context,operation):
        if self.busy:return
        from ..associativity import edit_source
        data=deepcopy(self.document.design) if self.document.design else dict(name='스케치 설계',parts=[],mates=[]);title='스케치 돌출 생성'
        source_context=deepcopy(context)
        if context.get('edit_base'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);p['geometry']=g;remove_bindings(data,['parts',p['id'],'geometry','thickness']);title='기본 스케치 편집'
            edit_source(data,p.get('profile_sketch_id'),g)
        elif context.get('feature_id'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);f=next(f for f in p['features'] if f['id']==context['feature_id']);f['sketch']=g;f['operation']=operation;title='면 스케치 피처 편집'
            edit_source(data,f.get('sketch_id'),g)
        elif context.get('face'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);face=context['face'];title='구멍 / 포켓 절삭' if operation=='cut' else '면 스케치 돌출';f=dict(id='feature-'+uid(),name=f"{title} {len(p['features'])+1}",face=face['index'],support_face_count=face['face_count'],support_feature=context['support_feature'],origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'],operation=operation,sketch=g);p['features'].append(f);context['feature_id']=f['id']
            if face.get('reference'):f['reference']=face['reference']
        else:
            from ..sketch_frames import extrusion_transform
            from ..part_roles import new_part_style
            p=Part(id='part-'+uid(),name='스케치 돌출 '+str(len(data['parts'])+1),geometry=g,transform=extrusion_transform(context),**new_part_style('extrusion')).model_dump();data['parts'].append(p);context['part_id']=p['id']
        if not source_context.get('edit_base') and not source_context.get('feature_id'):
            identifier=source_context.get('sketch_id') or 'sketch-'+uid();saved_context={k:deepcopy(v) for k,v in source_context.items() if k not in ('tool_actions','sketch_id','source_sketch_id')};saved_context['operation']=operation
            old=next((s for s in data.get('sketches',[]) if s['id']==identifier),None)
            saved=dict(id=identifier,name=old['name'] if old else f"스케치 {len(data.get('sketches',[]))+1}",geometry=deepcopy(g),context=saved_context)
            data['sketches']=[s for s in data.get('sketches',[]) if s['id']!=identifier]+[saved];context['sketch_id']=identifier
            if source_context.get('face'):f['sketch_id']=identifier
            else:p['profile_sketch_id']=identifier
        context.update(tool='sketch',operation=operation,sketch=g);self.apply_design(data,title,context,fit=True,after=self.cancel_sketch)
    def fit(self):
        if self.sketching:self.editor.canvas.fit()
        elif self.workspace.currentData()=='circuit':self.circuit_panel.fit_scene()
        else:self.viewport.fit()
    def rebuild_timeline(self):
        self.timeline.clear()
        if not self.document.journal:return
        journal=self.document.journal
        for n,e in enumerate(journal.path()):
            item=QListWidgetItem(icon('sketch' if e['context'].get('tool')=='sketch' else 'history'),f"{n+1:02d}  {e['label']}");item.setData(Qt.ItemDataRole.UserRole,e['id']);item.setToolTip(e['created_at']+'\n'+e['label']);self.timeline.addItem(item)
            if e['id']==journal.data['cursor']:item.setBackground(QColor('#244f50'));self.timeline.setCurrentItem(item)
        self.timeline.scrollToItem(self.timeline.currentItem())
    def history_text(self,entry):
        c=entry['context'];lines=[entry['label'],entry['created_at'],f"작업 출처: {entry['source']}",f"변경 필드: {len(entry['changes'])}"]
        if c.get('part_id'):lines.append('부품: '+c['part_id'])
        if c.get('face'):lines.append('선택 면: '+str(c['face']['index']+1)+'\n법선: '+str(c['face']['normal'])+'\n기준 피처: '+c.get('support_feature',''))
        if c.get('tool_actions'):
            from .cad_tools import TOOL_LABELS
            lines.append(('AI 작업: ' if c.get('tool')=='prompt' else '스케치 도구: ')+' → '.join(TOOL_LABELS.get(a['tool'],a['tool']) for a in c['tool_actions']))
        if c.get('sketch'):lines.append('구속: '+', '.join(f"{x['kind']}({x['a'][:7]})" for x in c['sketch'].get('entity_constraints',[])))
        return '\n'.join(lines)+'\n\n'+json.dumps(entry,ensure_ascii=False,indent=2)
    def history_clicked(self,item):
        entry=self.document.journal.index[item.data(Qt.ItemDataRole.UserRole)];clear_layout(self.property_layout);self.property_layout.addWidget(label(entry['label']));text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(self.history_text(entry));self.property_layout.addWidget(text,1);self.property_layout.addWidget(button('이 단계로 복원',lambda:self.restore_history(entry['id']),True));self.property_dock.show();self.property_dock.raise_()
    def history_dialog(self):
        if not self.document.journal:return
        dialog=QDialog(self);dialog.setWindowTitle('모든 작업 기록 · 분기 포함');dialog.resize(1100,690);v=QVBoxLayout(dialog);split=QSplitter();tree=QTreeWidget();tree.setHeaderLabels(['작업','시간']);details=QPlainTextEdit();details.setReadOnly(True);split.addWidget(tree);split.addWidget(details);split.setSizes([390,700]);v.addWidget(split);nodes={}
        for e in self.document.journal.data['entries']:
            item=QTreeWidgetItem([e['label']+(' ← 현재' if e['id']==self.document.journal.data['cursor'] else ''),e['created_at'][:19]]);item.setData(0,Qt.ItemDataRole.UserRole,e['id']);nodes[e['id']]=item
            if e['parent'] in nodes:nodes[e['parent']].addChild(item)
            else:tree.addTopLevelItem(item)
        tree.expandAll();tree.itemClicked.connect(lambda i,c:details.setPlainText(self.history_text(self.document.journal.index[i.data(0,Qt.ItemDataRole.UserRole)])));row=QHBoxLayout();row.addWidget(label('복원 후 새 작업을 하면 이전 분기도 보존됩니다.',True));row.addStretch()
        def restore():
            item=tree.currentItem()
            if item:dialog.accept();self.restore_history(item.data(0,Qt.ItemDataRole.UserRole))
        row.addWidget(button('선택 단계로 복원',restore,True));row.addWidget(button('닫기',dialog.reject));v.addLayout(row);dialog.exec()
    def restore_history(self,identifier):
        if self.busy or self.sketching:return
        journal=self.document.journal;self.apply_design(journal.at(identifier),'작업 기록 복원',cursor=identifier,fit=True)
    def undo(self):
        if self.sketching:self.editor.undo();return
        if self.document.journal:
            parent=self.document.journal.index[self.document.journal.data['cursor']]['parent']
            if parent:self.restore_history(parent)
    def redo(self):
        if self.sketching:self.editor.redo();return
        if self.document.journal:
            j=self.document.journal;path=j.path();i=next(i for i,e in enumerate(path) if e['id']==j.data['cursor'])
            if i+1<len(path):self.restore_history(path[i+1]['id'])
    def show_mate(self,identifier):
        self.selected_joint=identifier;self.selected_feature=None;self.refresh_ai_target()
        from ..assembly_motion import JOINT_TITLES,JOINT_AXES
        mate=next(m for m in self.document.design['mates'] if m['id']==identifier);names={p['id']:p['name'] for p in self.document.design['parts']};clear_layout(self.property_layout);self.property_layout.addWidget(label('조립 구속 · '+JOINT_TITLES[mate['kind']]));self.property_layout.addWidget(label(names[mate['parent']]+' → '+names[mate['child']]));self.property_layout.addWidget(label('운동 축: '+(', '.join(a.upper() for a in JOINT_AXES[mate['kind']]) or '없음 · 강체 연결')+'\n이동 XYZ: '+', '.join(f"{mate[k]:g}" for k in ('x','y','z'))+' mm\n회전 XYZ: '+', '.join(f"{mate[k]:g}" for k in ('rx','ry','rz'))+' °',True));self.property_layout.addWidget(button('연결된 부품 선택',lambda:self.select_parts([mate['parent'],mate['child']])));self.property_layout.addWidget(button('관절 구동 · 간섭 확인',self.drive_joints,True));self.property_layout.addWidget(button('고급 구속 / 오프셋 편집',lambda:self.mate_dialog(identifier)))
        readiness=(self.result or {}).get('stats',{}).get('joint_readiness',{}).get(identifier,{})
        if readiness:
            status=label(readiness['title']+'\n'+'\n'.join(readiness['details']),True);self.property_layout.addWidget(status)
            from ..joint_readiness import COLORS
            color=COLORS[readiness['state']];status.setStyleSheet('color:rgb('+','.join(str(round(v*255)) for v in color)+');')
        if mate['kind']=='revolute':self.property_layout.addWidget(button('이 관절에 실제 축 / 하우징 구조 추가',self.joint_hardware_dialog,True))
        if mate['kind'] in ('revolute','cylindrical','slider'):self.property_layout.addWidget(button('관절 축 · 구멍 동심 정렬…',self.joint_alignment_dialog))
        def remove():data=deepcopy(self.document.design);data['mates']=[m for m in data['mates'] if m['id']!=identifier];data['joint_frames']=[f for f in data.get('joint_frames',[]) if f['mate_id']!=identifier];prune_joint_references(data);self.apply_design(data,'조립 구속 삭제',{'mate_id':identifier})
        self.property_layout.addWidget(button('구속 삭제',remove));self.property_layout.addStretch()
    def mate_dialog(self,identifier=None):
        if isinstance(identifier,bool):identifier=None
        if self.busy or self.sketching:return
        if not self.document.design or len(self.document.design['parts'])<2:self.message('조립 구속에는 부품이 두 개 이상 필요합니다.');return
        existing=next((m for m in self.document.design['mates'] if m['id']==identifier),None);parts=self.document.design['parts'];dialog=QDialog(self);dialog.setWindowTitle('조립 구속');dialog.resize(440,680);v=QVBoxLayout(dialog);f=QFormLayout();kind=combo([('rigid','강체 · 0 자유도'),('revolute','회전 · RZ'),('slider','슬라이더 · Z'),('cylindrical','원통 · Z + RZ'),('pin_slot','핀 슬롯 · X + RZ'),('planar','평면 · X + Y + RZ'),('ball','볼 · RX + RY + RZ')]);parent=combo([(p['id'],p['name']) for p in parts]);child=combo([(p['id'],p['name']) for p in parts]);child.setCurrentIndex(1);pa=QComboBox();ca=QComboBox()
        def populate():
            for c,pick in ((pa,parent),(ca,child)):
                old=c.currentData();c.clear();p=next(p for p in parts if p['id']==pick.currentData());model=Part.model_validate(p)
                for key in anchors(model.geometry):c.addItem(key,key)
                c.setCurrentIndex(max(0,c.findData(old)))
        parent.currentIndexChanged.connect(populate);child.currentIndexChanged.connect(populate);populate();fields={}
        for title,w in [('종류',kind),('부모 부품',parent),('부모 기준점',pa),('자식 부품',child),('자식 기준점',ca)]:f.addRow(title,w)
        for key in ('x','y','z','rx','ry','rz'):w=number(existing[key] if existing else 0,-360 if key.startswith('r') else -5000,360 if key.startswith('r') else 5000,' °' if key.startswith('r') else ' mm');fields[key]=w;f.addRow(key.upper(),w)
        v.addLayout(f);ground=QCheckBox('부모가 최상위 부품이면 조립 기준으로 고정');ground.setChecked(True);v.addWidget(ground);v.addWidget(label('연결된 부모의 치수·배치·관절 값을 바꾸면 자식 부품이 따라갑니다. 하나의 자식에는 한 연결만 허용합니다. 닫힌 기구는 연결 후 조립 메뉴의 폐루프 연결을 추가하세요.',True));buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);v.addWidget(buttons)
        if existing:
            kind.setCurrentIndex(kind.findData(existing['kind']));parent.setCurrentIndex(parent.findData(existing['parent']));child.setCurrentIndex(child.findData(existing['child']));pa.setCurrentIndex(pa.findData(existing['parent_anchor']));ca.setCurrentIndex(ca.findData(existing['child_anchor']))
        if existing and any(f['mate_id']==identifier for f in self.document.design.get('joint_frames',[])):
            for w in (parent,child,pa,ca):w.setEnabled(False);w.setToolTip('선택한 면 좌표계로 연결된 조인트입니다. 부품/면 변경은 조인트를 삭제하고 다시 선택하세요.')
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        m=dict(id=identifier or 'mate-'+uid(),kind=kind.currentData(),parent=parent.currentData(),child=child.currentData(),parent_anchor=pa.currentData(),child_anchor=ca.currentData(),**{key:w.value() for key,w in fields.items()});data=deepcopy(self.document.design);data['mates']=[mate for mate in data['mates'] if mate['id']!=identifier]+[m]
        if existing and existing.get('limits'):m['limits']=deepcopy(existing['limits'])
        if ground.isChecked() and not any(mate['child']==m['parent'] for mate in data['mates']):next(p for p in data['parts'] if p['id']==m['parent'])['fixed']=True
        self.apply_design(data,'조립 구속 '+('편집' if existing else '추가'),{'mate':m},fit=True)
    def check_save(self):
        if not self.document.dirty:return True
        answer=QMessageBox.question(self,'프로젝트 저장','현재 설계의 변경 내용을 저장할까요?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel:return False
        if answer==QMessageBox.StandardButton.Save:return self.save()
        return True
    def new_document(self):
        if self.busy or self.sketching or not self.check_save():return
        self.cancel_ai();self.operation_serial+=1;self.accept_draft.setEnabled(False)
        self.reset_role_view(restore=False)
        self.set_references([])
        self.document=Document();self.result=None;self.selected=None;self.selected_parts=[];self.selected_sketch=None;self.selected_profile=None;self.last_draft=None;self.viewport.load(None);self.viewport.joints.set_design(None);self.viewport.hidden.clear();self.isolation_hidden=None;self.actions['isolate'].setChecked(False);self.rebuild_tree();self.rebuild_timeline();self.show_properties();self.title()
    def recover_autosave(self):
        if self.busy or self.sketching:return
        if not self.autosave.exists():self.message('복구할 자동저장 파일이 없습니다.');return
        if not self.check_save():return
        self.open_project(self.autosave,recovery=True)
    def open_project(self,path=None,recovery=False):
        if self.busy or self.sketching:return
        if not recovery and not self.check_save():return
        if not path:path,_=QFileDialog.getOpenFileName(self,'CAD 프로젝트 열기',str(self.document.path.parent if self.document.path else ROOT/'examples'),'CAD 프로젝트 (*.cad.json *.json)')
        if not path:return
        self.cancel_ai()
        path=Path(path)
        def work():
            with KERNEL_LOCK:project=read_project(path);r=preview(project.design);return project,r
        def done(result):
            self.set_references([])
            self.reset_role_view(restore=False)
            project,self.result=result;self.document.load(project,None if recovery else path);self.operation_serial+=1;self.last_draft=None;self.accept_draft.setEnabled(False);self.document.dirty=recovery;self.selected=project.design.parts[0].id if project.design.parts else None;self.selected_sketch=None;self.prompt.setPlainText(project.prompt);self.viewport.hidden.clear();self.isolation_hidden=None;self.actions['isolate'].setChecked(False);self.viewport.load(self.result,True);self.viewport.joints.set_design(project.design);self.rebuild_tree();self.select_parts([self.selected] if self.selected else []);self.rebuild_timeline();self.title();self.message('자동 저장한 설계를 복구했습니다.' if recovery else '프로젝트와 작업 기록을 열었습니다.')
        self.run(work,done,'프로젝트 · 작업 기록 검증 중…')
    def save(self,save_as=False):
        if self.busy or self.sketching or not self.document.design:return False
        path=self.document.path
        if save_as or not path:
            chosen,_=QFileDialog.getSaveFileName(self,'CAD 프로젝트 저장',str(path or Path.home()/'Documents'/(self.document.design['name']+'.cad.json')),'CAD 프로젝트 (*.cad.json)')
            if not chosen:return False
            path=Path(chosen if chosen.lower().endswith('.cad.json') else chosen+'.cad.json')
        try:self.document.write(path);self.title();self.message('설계와 전체 작업 기록 저장: '+str(path));return True
        except Exception as exc:self.show_error(str(exc));return False
    def export_file(self,fmt):
        if self.busy or self.sketching or not self.document.design:return
        if fmt in ('f3d','ipt'):
            from .autodesk_export import AutodeskExportDialog
            AutodeskExportDialog(self,self.document.project(),fmt,self.selected).exec();return
        title={'step':'STEP 파일 (*.step)','stl':'STL 파일 (*.stl)','zip':'Autodesk 변환 패키지 (*.zip)'}[fmt];path,_=QFileDialog.getSaveFileName(self,'형상 내보내기',str(Path.home()/'Documents'/(self.document.design['name']+'.'+fmt)),title)
        if not path:return
        target=Path(path if path.lower().endswith('.'+fmt) else path+'.'+fmt);project=self.document.project()
        def work():
            temp=target.with_name(target.stem+'.'+uuid4().hex+'.'+fmt)
            try:
                if fmt=='zip':temp.write_bytes(conversion_package(project))
                else:export(project.design,temp,fmt)
                os.replace(temp,target)
            finally:temp.unlink(missing_ok=True)
            return target
        self.run(work,lambda p:self.message('내보내기 완료: '+str(p)),'형상 내보내는 중…')
    def ai_mode_changed(self):
        chat=self.ai_mode.currentData()=='chat';self.generate_button.setText('질문 보내기' if chat else '초안 생성');self.accept_draft.setVisible(not chat)
        self.last_draft=None;self.accept_draft.setEnabled(False)
        self.ai_result.setPlainText('일반 질문이나 현재 설계에 대해 물어보세요. 답변은 형상을 변경하지 않습니다.' if chat else '설계 초안을 생성한 뒤 변경 미리보기에서 확인하세요.')
    def provider_changed(self):
        provider=self.provider.currentData();self.astra_button.setVisible(provider=='openai');self.cloud_effort.setVisible(provider in ('openai','codex'));self.key.setVisible(provider=='openai');self.model.setVisible(provider=='openai');self.ollama_models.setVisible(provider=='ollama')
        self.openai_setup_button.setVisible(provider=='openai');self.codex_setup_button.setVisible(provider=='codex');self.codex_model_label.setVisible(provider=='codex')
        self.codex_models.setVisible(provider=='codex')
        self.codex_status.setVisible(provider=='codex');self.codex_check_button.setVisible(provider=='codex')
        self.codex_usage.setVisible(provider=='codex')
        self.codex_model_label.setText('Codex 모델: '+(self.codex_config['model'] or '연결 후 선택'))
        self.ai_info.setText({'local':'이름·치수를 해석하는 오프라인 명령입니다. 자유로운 문장용 AI는 아닙니다.','codex':'ChatGPT 구독의 Codex 사용량 적용 · 프롬프트와 현재 설계를 전송합니다. API로 자동 전환하지 않습니다.','openai':'유료 API · 프롬프트와 설계를 OpenAI로 전송합니다. 키는 저장하지 않습니다.','ollama':'이 PC의 모델로 실행 · API 키 불필요. 설치된 모델을 자동으로 찾습니다.'}[provider])
        self.ai_info.setToolTip('OpenAI 초안 생성은 최대 4회 요청으로 계획과 형상을 검증합니다. 취소 전 사용량은 청구될 수 있습니다.' if provider=='openai' else self.ai_info.text())
        if provider in ('openai','codex'):self.ai_settings_toggle.setChecked(True)
        if provider=='codex':self.update_codex_effort()
        else:
            selected=self.cloud_effort.currentData();self.cloud_effort.clear()
            for value,text in [('low','추론 · 빠르게'),('medium','추론 · 균형'),('high','추론 · 깊게')]:self.cloud_effort.addItem(text,value)
            self.cloud_effort.setCurrentIndex(max(0,self.cloud_effort.findData(selected or 'medium')))
        self.last_draft=None;self.accept_draft.setEnabled(False)
        if provider=='ollama':self.ollama_models.refresh()
    def install_local_ai(self):
        from .ai_setup import AISetupDialog
        dialog=AISetupDialog(self);dialog.exec()
        if dialog.model_name:self.ollama_models.models.setCurrentIndex(-1);self.ollama_models.preferred=dialog.model_name;self.provider.setCurrentIndex(self.provider.findData('ollama'));self.ollama_models.refresh()
    def generate_draft(self,*,repair_draft=None):
        if self.busy or self.sketching or self.ai_task:return
        if repair_draft and repair_draft['serial']!=self.operation_serial:self.show_error('초안 생성 이후 설계가 변경되었습니다. 다시 생성하세요.');return
        prompt=repair_draft['prompt'] if repair_draft else self.prompt.toPlainText().strip()
        if not prompt:self.ai_result.setPlainText('설계 명령을 입력하세요. 예: 직경 20 mm, 높이 10 mm인 원통을 만들어줘.');self.prompt.setFocus();return
        if len(prompt)>4000:self.show_error('명령은 4,000자 이내로 입력하세요.');return
        provider=self.provider.currentData();key=self.key.text().strip() or os.getenv('OPENAI_API_KEY','');model=self.ollama_models.model_name() if provider=='ollama' else self.model.text().strip();request=DraftRequest(prompt=prompt,current=self.document.design,selected_part=self.selected,selected_feature=getattr(self,'selected_feature',None),selected_joint=getattr(self,'selected_joint',None),mode=(self.document.design or {}).get('mode','specimen'));serial=self.operation_serial;deadline=self.ai_timeout.currentData();effort=self.cloud_effort.currentData();self.last_draft=None;self.accept_draft.setEnabled(False)
        if repair_draft:request=DraftRequest.model_validate(repair_draft['request'])
        else:request.references=deepcopy(self.reference_materials)
        if request.references and provider=='local':self.show_error('참고자료를 읽으려면 Codex, Ollama 또는 OpenAI를 선택하세요.');return
        repair=deepcopy(repair_draft['response'].get('repair')) if repair_draft else None
        self.ai_retained_draft=repair_draft
        self.ai_draft_context=dict(serial=serial,provider=provider,prompt=prompt,request=request.model_dump())
        if provider=='ollama' and not model:self.ai_settings_toggle.setChecked(True);self.ai_result.setPlainText('Ollama 모델을 먼저 선택하세요. 설정에서 새로 찾기 또는 로컬 AI 설치 / 모델 다운로드를 사용하세요.');self.ai_scroll.ensureWidgetVisible(self.ollama_models);return
        codex_config=dict(self.codex_config)
        if provider=='codex' and not codex_config['model']:self.ai_result.setPlainText('Codex 연결 버튼에서 ChatGPT로 로그인하고 모델을 선택하세요.');return
        if provider=='codex' and self.codex_catalog and not any(item['model']==codex_config['model'] for item in self.codex_catalog):self.ai_result.setPlainText('저장된 모델이 현재 Codex 목록에 없습니다. AI 패널에서 사용할 모델을 선택하세요.');self.codex_models.setFocus();return
        chat_mode=self.ai_mode.currentData()=='chat';identity=(provider,codex_config['model'] if provider=='codex' else model)
        history=deepcopy(self.chat_history) if identity==self.chat_identity else []
        def work(control,progress):
            if chat_mode:
                from .ai_chat import answer
                text=answer(request,provider,identity[1],api_key=key,executable=codex_config['executable'],effort=effort,history=history,control=control,progress=progress,deadline=deadline)
                return dict(kind='answer',answer=text,prompt=prompt,serial=serial,identity=identity,history=history)
            from ..planner import local_draft
            if provider=='local':result=local_draft(request)
            elif provider=='ollama':
                from .local_ai import ollama_draft
                result=ollama_draft(request,model,control=control,progress=progress,deadline=deadline,repair=repair)
            elif provider=='codex':
                from .codex_ai import generate
                result=generate(request,codex_config['model'],executable=codex_config['executable'],control=control,progress=progress,deadline=deadline,effort=effort,repair=repair)
            else:
                if not key:raise ValueError('API 키를 입력하거나 OPENAI_API_KEY 환경변수를 설정하세요.')
                from .local_ai import cloud_draft
                result=cloud_draft(request,model,api_key=key,control=control,progress=progress,deadline=deadline,effort=effort,repair=repair)
            control.check();progress('생성 완료 · CAD 형상 검증 중…')
            with KERNEL_LOCK:
                d=Design.model_validate(result['design']);r=preview(d)
                from .draft_repair import review_candidate
                result['validation']=review_candidate(d,request.current,r,control.check)
            return dict(response=result,design=d.model_dump(),preview=r,serial=serial,provider=provider,prompt=prompt,request=request.model_dump())
        from .ai_task import AITask
        self.ai_task=AITask(work,self);self.ai_task.completed.connect(self.ai_complete,Qt.ConnectionType.QueuedConnection);self.ai_task.failed.connect(self.ai_failed,Qt.ConnectionType.QueuedConnection);self.ai_task.progress.connect(self.ai_progress,Qt.ConnectionType.QueuedConnection)
        self.ai_started=time.monotonic();self.ai_stage='모델 연결 / 준비 중…';self.ai_controls(True);self.ai_tick();self.ai_timer.start();self.ai_task.start()
    def ai_controls(self,running):
        self.reference_button.setEnabled(not running);self.actions['references'].setEnabled(not running)
        self.accept_draft.setVisible(not running and self.ai_mode.currentData()=='design')
        self.generate_button.setEnabled(not running and not self.busy and not self.sketching);self.cancel_ai_button.setVisible(running);self.ai_status_button.setVisible(running)
        for widget in (self.ai_mode,self.provider,self.prompt,self.ollama_models,self.model,self.key,self.ai_timeout,self.astra_button,self.cloud_effort,self.openai_setup_button,self.codex_setup_button):widget.setEnabled(not running)
        self.codex_models.setEnabled(not running and not self.codex_probe_task);self.codex_check_button.setEnabled(not running and not self.codex_probe_task)
        self.actions['openai_setup'].setEnabled(not running)
        self.actions['codex_setup'].setEnabled(not running)
    @Slot()
    def ai_tick(self):
        if not self.ai_task:return
        elapsed=int(time.monotonic()-self.ai_started);policy=' · 대기 무제한' if self.provider.currentData() in ('ollama','openai','codex') and self.ai_timeout.currentData() is None else '';text=f'{self.ai_stage}\n경과 {elapsed//60:02d}:{elapsed%60:02d}{policy}\n\n생성 중에도 CAD 작업과 저장이 가능합니다. 취소하거나 앱을 종료할 수 있습니다.'
        if elapsed>=30 and self.provider.currentData()=='ollama':text+='\n로컬 모델은 PC 성능과 설계 크기에 따라 몇 분 걸릴 수 있습니다.'
        self.ai_result.setPlainText(text);self.ai_status_button.setText(f'AI {elapsed//60:02d}:{elapsed%60:02d} · 취소')
    @Slot(object)
    def ai_progress(self,packet):
        task,text=packet
        if task is self.ai_task:
            self.ai_stage=text
            if self.provider.currentData()=='codex' and text.startswith('Codex 연결 대기'):
                self.codex_connection_verified=False
                self.codex_status.setText('Codex · 연결 대기 · 자동 재시도');self.codex_status.setStyleSheet('color:#f5c26b;')
            elif text.startswith('Codex 연결 복구'):
                self.codex_connection_verified=True
                self.codex_status.setText('✓ Codex 연결 완료');self.codex_status.setStyleSheet('color:#8dd7c0;')
            self.ai_tick()
    def finish_ai_task(self):
        self.ai_task=None;self.ai_timer.stop();self.ai_controls(False)
    @Slot()
    def cancel_ai(self):
        if self.ai_task:
            self.retain_ai_checkpoint()
            self.ai_task.cancel();self.finish_ai_task();self.last_draft=None;self.accept_draft.setEnabled(False);self.ai_result.setPlainText('설계 초안 생성을 취소했습니다. 현재 설계는 변경되지 않았습니다.');self.message('AI 생성 취소 완료')
            self.restore_repair_draft('수정을 취소했습니다. 이전 초안은 미리보기에서 다시 볼 수 있습니다.')
    def retain_ai_checkpoint(self):
        control=getattr(self.ai_task,'control',None)
        checkpoint=control.checkpoint() if control else None
        context=getattr(self,'ai_draft_context',None)
        if checkpoint and context and context['serial']==self.operation_serial:
            self.ai_retained_draft={**context,**checkpoint,'design':checkpoint['response']['design']}
    def restore_repair_draft(self,message):
        retained=getattr(self,'ai_retained_draft',None);self.ai_retained_draft=None
        if retained and retained['serial']==self.operation_serial:
            from .draft_summary import draft_summary
            self.last_draft=retained;self.accept_draft.setText('미리보기 / 수정');self.accept_draft.setEnabled(not self.busy and not self.sketching);self.ai_result.setPlainText(message+'\n\n'+draft_summary(retained['response'],retained['preview']));return True
        return False
    @Slot(object)
    def ai_failed(self,packet):
        task,error=packet
        if task is not self.ai_task:return
        from ..power_paths import PowerInputRequired,REQUIRED_POWER_INPUTS
        text=str(error)
        self.retain_ai_checkpoint()
        self.finish_ai_task()
        if isinstance(error,PowerInputRequired):
            if self.provider.currentData()=='codex':
                self.codex_connection_verified=True
                self.codex_status.setText('✓ Codex 연결 완료');self.codex_status.setStyleSheet('color:#8dd7c0;')
            fields=', '.join(REQUIRED_POWER_INPUTS[key] for key in error.missing_fields)
            notice='전원 수치 입력 필요\n\n'+fields+' 값을 확인해 입력하세요.\n\n전원 연결 설계…에서 값을 입력해 DC 미리보기를 확인하거나, 확인한 수치를 프롬프트에 추가하세요. 현재 설계는 변경되지 않았습니다.'
            if self.language_service.language=='en':
                labels={'source_voltage_v':'battery voltage (V)','positive_wire_length_mm':'feed wire length (mm)',
                        'positive_wire_cross_section_mm2':'feed wire area (mm²)','return_wire_length_mm':'return wire length (mm)',
                        'return_wire_cross_section_mm2':'return wire area (mm²)','load_voltage_v':'load voltage (V)',
                        'load_current_a':'load current (A)'}
                fields=', '.join(labels[key] for key in error.missing_fields)
                notice='Power operating inputs required\n\nSupply verified positive values for: '+fields+'.\n\nOpen Power path design… for a DC preview, or add the confirmed values to your prompt. The current design is unchanged.'
            if not self.restore_repair_draft(notice):self.ai_result.setPlainText(notice)
            self.message('Power operating inputs required · open Power path design…' if self.language_service.language=='en' else '전원 수치 입력 필요 · 전원 연결 설계…를 여세요.')
            return
        if self.restore_repair_draft('추가 수정이 완료되지 않았습니다. 이전 초안을 보존했습니다.\n'+text[:1200]):return
        if self.provider.currentData()=='codex':
            cad_error='치수·형상 검증' in text
            self.codex_connection_verified=cad_error
            self.codex_status.setText('✓ Codex 연결 완료' if cad_error else 'Codex · 연결 재확인 필요');self.codex_status.setStyleSheet('color:#8dd7c0;' if cad_error else 'color:#f5c26b;')
        self.ai_result.setPlainText('초안 생성 실패\n\n'+text[:2400]);self.message('초안 생성 실패 · AI 패널의 오류 안내를 확인하세요.')
    @Slot(object)
    def ai_complete(self,packet):
        task,draft=packet
        if task is not self.ai_task:return
        self.finish_ai_task()
        self.ai_retained_draft=None
        if draft.get('kind')=='answer':
            if draft['identity'][0]=='codex':self.codex_connection_verified=True;self.codex_status.setText('✓ Codex 연결 완료');self.codex_status.setStyleSheet('color:#8dd7c0;')
            self.chat_identity=draft['identity'];self.chat_history=(draft['history']+[dict(role='user',content=draft['prompt']),dict(role='assistant',content=draft['answer'])])[-10:]
            self.ai_result.setPlainText(('답변은 질문 당시 설계를 기준으로 합니다. 현재 설계가 변경되었습니다.\n\n' if draft['serial']!=self.operation_serial else '')+'\n\n'.join(('질문: ' if item['role']=='user' else '답변: ')+item['content'] for item in self.chat_history));self.ai_scroll.ensureWidgetVisible(self.ai_result,0,8);self.message('AI 답변 완료 · 설계 변경 없음');return
        response=draft['response'];r=draft['preview']
        if draft['provider']=='codex':self.codex_connection_verified=True;self.codex_status.setText('✓ Codex 연결 완료');self.codex_status.setStyleSheet('color:#8dd7c0;')
        if draft['provider']=='ollama':self.ollama_models.refresh()
        if draft['serial']!=self.operation_serial:
            self.ai_result.setPlainText('초안 생성 중 현재 설계가 바뀌었습니다. 새 설계를 기준으로 다시 생성하세요.');return
        from .draft_summary import draft_summary
        self.last_draft=draft;self.ai_result.setPlainText(draft_summary(response,r));self.accept_draft.setEnabled(not self.busy and not self.sketching);self.message('미리보기 준비 · 간섭 부위를 확인하고 AI로 수정을 계속하세요.' if response.get('validation',{}).get('status')=='needs_repair' else '설계 초안 생성 완료 · 내용을 확인하고 적용하세요.')
        self.accept_draft.setText('미리보기 / 수정' if response.get('validation',{}).get('status')=='needs_repair' else '미리보기 / 적용')
        self.completion_notifier.notify(response.get('validation',{}).get('status')=='needs_repair')
        self.ai_scroll.ensureWidgetVisible(self.ai_result,0,8)
    def preview_draft(self):
        draft=self.last_draft
        if not draft or self.busy or self.sketching:return
        if draft['serial']!=self.operation_serial:self.show_error('초안 생성 이후 설계가 변경되었습니다. 다시 생성하세요.');return
        from .draft_preview import DraftPreviewDialog
        dialog=DraftPreviewDialog(self,self.result,draft['preview'],self.ai_result.toPlainText(),validation=draft['response'].get('validation'),repairable=bool(draft['response'].get('repair')))
        outcome=dialog.exec()
        if outcome==QDialog.DialogCode.Accepted:self.apply_draft()
        elif outcome==2:
            retry=deepcopy(draft)
            if dialog.repair_note.text().strip():retry['response']['repair']['user_instruction']=dialog.repair_note.text().strip()
            self.generate_draft(repair_draft=retry)
    def apply_draft(self):
        draft=self.last_draft
        if not draft or self.busy or self.sketching:return
        if draft['response'].get('validation',{}).get('status')=='needs_repair':self.message('간섭이 남은 초안입니다. 미리보기에서 AI로 수정한 후 적용하세요.');return
        if draft['serial']!=self.operation_serial:self.show_error('초안 생성 이후 설계가 변경되었습니다. 현재 설계로 초안을 다시 생성하세요.');return
        self.document.prompt=draft['prompt'];context=dict(source='openai' if draft['provider'] in ('openai','codex') else 'local',provider=draft['provider'],prompt=draft['prompt'],summary=draft['response']['summary'],assumptions=draft['response'].get('assumptions',[]),tool='prompt',tool_actions=draft['response'].get('tool_actions',[]),journal_base=draft['response'].get('journal_base'),journal_steps=draft['response'].get('journal_steps',[]));self.apply_design(draft['design'],'설계 명령 적용',context,fit=True);self.last_draft=None;self.accept_draft.setEnabled(False)
    def help_dialog(self):
        from .shortcuts import show_manual
        show_manual(self)
    def check_updates(self):
        if self.busy or self.sketching:return
        from ..updater import latest_release,version
        if not getattr(sys,'frozen',False):
            QMessageBox.information(self,'업데이트','소스 실행 환경입니다. 배포 EXE에서 기존 설치를 업데이트할 수 있습니다.');return
        updater=Path(sys.executable).parent/'PromptCADStudioUpdater.exe'
        if not updater.is_file():self.show_error('업데이트 실행 파일이 없습니다. 릴리스의 PromptCADStudioUpdater.exe를 실행하세요.');return
        def checked(release):
            if version(release['version'])<=version(__version__):
                QMessageBox.information(self,'업데이트',f'현재 v{__version__} · 최신 버전입니다.');return
            answer=QMessageBox.question(self,'업데이트',f"v{release['version']}으로 업데이트할까요?\n다운로드 {release['size']/1024**2:.0f} MB\n\n현재 앱을 종료하고 기존 설치 폴더를 갱신합니다.\n완료 후 다시 실행하며 임시 다운로드와 이전 프로그램 파일을 정리합니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes or not self.check_save():return
            try:
                subprocess.Popen([str(updater),'--install-dir',str(updater.parent),'--wait-pid',str(os.getpid()),'--auto-update','--restart'],cwd=str(updater.parent),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            except OSError as exc:self.show_error('업데이트 실행 실패: '+str(exc));return
            self._update_close=True;self.close()
        self.run(latest_release,checked,'최신 버전 확인 중…')
    def closeEvent(self,event):
        self.cancel_ai()
        if self.codex_probe_task:self.codex_probe_task.cancel();self.codex_probe_task=None
        if self.busy:self.message('실행 중인 작업이 끝난 뒤 종료하세요.');event.ignore();return
        if self.sketching:
            answer=QMessageBox.question(self,'미완료 스케치','완료하지 않은 스케치를 버리고 종료할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
            self.cancel_sketch()
        if not getattr(self,'_update_close',False) and not self.check_save():event.ignore();return
        panel=getattr(self,'wiring_window',None)
        if panel is not None:panel.close();panel.deleteLater();self.wiring_window=None
        self.autosave_document();self.editor.stop();self.viewport.shutdown();event.accept()
