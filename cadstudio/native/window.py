"""Qt Widgets workbench: manual modeling, timeline, assembly and optional AI."""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt,QTimer,QThreadPool,QSize
from PySide6.QtGui import QAction,QKeySequence,QColor,QIcon
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QDockWidget,QTreeWidget,QTreeWidgetItem,QListWidget,QListWidgetItem,QAbstractItemView,QStackedWidget,QScrollArea,QToolBar,QToolButton,QMenu,QLineEdit,QComboBox,QCheckBox,QPlainTextEdit,QFileDialog,QMessageBox,QDialog,QDialogButtonBox,QColorDialog,QProgressBar,QLabel,QSplitter)
from .document import Document,read_project
from .widgets import icon,number,label,button,clear_layout,Worker
from .viewport import CADViewport
from .sketch import SketchEditor,combo
from .geometry import uid
from ..models import Design,Part,Project,DraftRequest
from ..catalog import TITLES,FIELDS,EXAMPLES,preset,part_default
from ..kernel import preview,export,KERNEL_LOCK
from ..constraints import anchors
from ..native_export import conversion_package

APP_NAME='Prompt CAD Studio'
DATA_DIR=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(os.getenv('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PromptCADStudio')))
ROOT=Path(__file__).resolve().parents[2]

class MainWindow(QMainWindow):
    def __init__(self,restore=True):
        super().__init__();self.setObjectName('nativeCADMainWindow');self.resize(1500,920);self.setMinimumSize(820,560)
        self.document=Document();self.result=None;self.selected=None;self.selected_sketch=None;self.busy=False;self.worker=None;self.sketching=False;self.joint_picks=None;self.last_draft=None;self.data_dir=DATA_DIR;self.data_dir.mkdir(parents=True,exist_ok=True);self.autosave=self.data_dir/'native-autosave.cad.json';self.operation_serial=0
        self.stack=QStackedWidget();self.setCentralWidget(self.stack);self.viewport=CADViewport();self.editor=SketchEditor();self.stack.addWidget(self.viewport);self.stack.addWidget(self.editor);self.viewport.part_selected.connect(self.select_part);self.viewport.face_selected.connect(self.face_selected);self.viewport.message.connect(self.message);self.editor.apply_requested.connect(self.apply_sketch);self.editor.finished_requested.connect(self.finish_sketch);self.viewport.sketch_selected.connect(self.select_sketch);self.editor.cancelled.connect(self.cancel_sketch)
        self.actions={};brand=QLabel('PROMPT  /  CAD');brand.setStyleSheet('color:#76d5c2;font-size:11px;font-weight:600;padding:0 14px;');self.menuBar().setCornerWidget(brand,Qt.Corner.TopRightCorner);self.make_menus();self.make_toolbar();self.make_browser();self.make_properties();self.make_timeline();self.make_ai()
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setFixedWidth(140);self.progress.setMaximumHeight(12);self.progress.hide();self.statusBar().addPermanentWidget(self.progress);self.statusBar().addPermanentWidget(QLabel('  mm  ·  NATIVE 2.1  '));self.message('새 스케치에서 시작하거나 부품을 추가하세요.');self.rebuild_tree();self.show_properties();self.title()
        if restore and self.autosave.exists():QTimer.singleShot(120,lambda:self.open_project(self.autosave,recovery=True))
    def action(self,key,title,fn,shortcut=None,ico=None):
        a=QAction(icon(ico),title,self) if ico else QAction(title,self);a.triggered.connect(fn)
        if shortcut:a.setShortcut(QKeySequence(shortcut))
        self.actions[key]=a;return a
    def make_menus(self):
        file=self.menuBar().addMenu('파일(&F)');file.addAction(self.action('new','새 설계',self.new_document,'Ctrl+N','file'));file.addAction(self.action('open','열기…',lambda:self.open_project(),'Ctrl+O','open'));file.addAction(self.action('save','저장',self.save,'Ctrl+S','save'));file.addAction(self.action('save_as','다른 이름으로 저장…',lambda:self.save(True),'Ctrl+Shift+S'));file.addSeparator()
        export_menu=file.addMenu('내보내기')
        for fmt,title in [('step','STEP · CAD 교환'),('stl','STL · 메시'),('zip','Fusion / Inventor 변환 패키지')]:export_menu.addAction(title,lambda f=fmt:self.export_file(f))
        examples=file.addMenu('예제 열기')
        for name,path in [('면 스케치 · 구속 · 전체 기록','analytic_history.cad.json'),('스케치 피처 기록','feature_history.cad.json')]:
            if (ROOT/'examples'/path).exists():examples.addAction(name,lambda p=path:self.open_project(ROOT/'examples'/p))
        examples.addAction('2링크 조립',lambda:self.add_preset('robot_arm'));file.addSeparator();file.addAction('종료',self.close)
        edit=self.menuBar().addMenu('편집(&E)');edit.addAction(self.action('undo','실행 취소',self.undo,'Ctrl+Z','undo'));edit.addAction(self.action('redo','다시 실행',self.redo,'Ctrl+Y','redo'));edit.addAction(self.action('delete','선택 부품 삭제',self.delete_part,None,'delete'))
        model=self.menuBar().addMenu('모델링(&M)');model.addAction(self.action('sketch','새 스케치 · XY',lambda:self.start_sketch('XY'),None,'sketch'));model.addAction(self.action('face_sketch','면 스케치',self.start_face_sketch,None,'sketch'));model.addAction(self.action('edit_sketch','스케치 편집',self.edit_sketch,None,'sketch'));model.addSeparator()
        for kind,title in TITLES.items():model.addAction(title,lambda k=kind:self.add_preset(k))
        assembly=self.menuBar().addMenu('조립(&A)');assembly.addAction(self.action('face_joint','면으로 조인트',self.start_face_joint,None,'assembly'));self.actions['face_joint'].setCheckable(True);assembly.addAction(self.action('drive','관절 구동',self.drive_joints,None,'origin'));assembly.addAction(self.action('robot','로봇 치수',self.robot_dialog,None,'assembly'));assembly.addAction(self.action('mate','기준점으로 연결…',self.mate_dialog,None,'assembly'));model.addAction(self.action('specimen','시편 설계',self.specimen_dialog,None,'specimen'))
        view=self.menuBar().addMenu('보기(&V)');view.addAction(self.action('fit','모델에 맞춤',self.fit,'F','fit'));self.view_menu=view;edge=view.addAction('모서리 표시');edge.setCheckable(True);edge.setChecked(True);edge.toggled.connect(self.viewport.edges)
        help=self.menuBar().addMenu('도움말(&H)');help.addAction('사용 방법 · 지원 범위',self.help_dialog);help.addAction('이 앱 정보',lambda:QMessageBox.about(self,APP_NAME,'Prompt CAD Studio 2.1\nQt Widgets + VTK OpenGL + Open CASCADE\n\n브라우저와 웹 서버 없이 실행되는 Windows CAD 앱입니다.\n단위: mm\n설계 프로젝트: .cad.json\n형상 교환: STEP / STL'))
    def make_toolbar(self):
        self.toolbar=QToolBar('작업 공간');self.toolbar.setObjectName('modelToolbar');self.toolbar.setMovable(False);self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);self.toolbar.setIconSize(QSize(25,25));self.addToolBar(self.toolbar)
        for key in ('new','open','save'):self.toolbar.addAction(self.actions[key])
        self.toolbar.addSeparator();self.workspace=combo([('model','설계'),('assembly','조립'),('specimen','시편')]);self.workspace.setMinimumWidth(95);self.workspace.setToolTip('작업 공간을 선택하면 필요한 도구가 나타납니다.');self.toolbar.addWidget(self.workspace);self.toolbar.addSeparator();self.mode_tools={'model':[],'assembly':[],'specimen':[]}
        self.plane=combo([('XY','XY 평면'),('XZ','XZ 평면'),('YZ','YZ 평면')]);self.mode_tools['model'].append(self.toolbar.addWidget(self.plane));self.mode_tools['model'].append(self.toolbar.addAction(icon('sketch'),'스케치 작성',lambda:self.start_sketch(self.plane.currentData())))
        for key in ('face_sketch','edit_sketch'):self.add_mode_tool('model',key)
        b=QToolButton();b.setText('부품 추가');b.setIcon(icon('extrude'));b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(b)
        for kind,title in TITLES.items():menu.addAction(title,lambda k=kind:self.add_preset(k))
        b.setMenu(menu);self.add_part_action=self.toolbar.addWidget(b)
        for key in ('face_joint','drive','robot','mate'):self.add_mode_tool('assembly',key)
        self.add_mode_tool('specimen','specimen');self.toolbar.addSeparator()
        for key in ('undo','redo','fit'):self.toolbar.addAction(self.actions[key])
        self.toolbar.addAction(icon('ai'),'설계 명령',lambda:self.ai_dock.setVisible(not self.ai_dock.isVisible()));self.workspace.currentIndexChanged.connect(self.workspace_changed);self.workspace_changed()
    def add_mode_tool(self,mode,key):
        source=self.actions[key];copy=self.toolbar.addAction(source.icon(),source.text(),source.trigger);copy.setCheckable(source.isCheckable());source.toggled.connect(copy.setChecked);self.mode_tools[mode].append(copy)
    def workspace_changed(self):
        for mode,actions in self.mode_tools.items():
            for action in actions:action.setVisible(mode==self.workspace.currentData())
        self.add_part_action.setVisible(self.workspace.currentData()!='specimen')
    def specimen_dialog(self):
        if self.busy or self.sketching:return
        from .workflows import SpecimenDialog
        part=self.part();identifier=part['id'] if part and part['geometry']['kind'] in ('round_specimen','flat_specimen','wafer') else None;dialog=SpecimenDialog(self,self.document.design,identifier)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'시편 치수 설계',{'tool':'specimen','part_id':dialog.part_id},fit=True,after=lambda:self.select_part(dialog.part_id))
    def robot_dialog(self):
        if self.busy or self.sketching:return
        from .workflows import RobotDialog
        dialog=RobotDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'로봇 링크 / 핀 / 관절 치수 편집',{'tool':'robot','dimensions':{k:w.value() for k,w in dialog.inputs.items()}},fit=True)
    def drive_joints(self):
        if self.busy or self.sketching:return
        if not self.document.design or not any(m['kind']!='rigid' for m in self.document.design['mates']):self.message('회전·슬라이더·원통 조인트를 먼저 만들거나 로봇 조립을 추가하세요.');return
        from .workflows import JointDriveDialog
        dialog=JointDriveDialog(self,self.document.design)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_design(dialog.checked.model_dump(),'관절 자세 적용',{'tool':'joint-drive','joint_values':[{'mate_id':k[0],'axis':k[1],'value':w.value()} for k,w in dialog.inputs.items()]})
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
    def make_properties(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);self.properties=QWidget();self.property_layout=QVBoxLayout(self.properties);self.property_layout.setContentsMargins(14,14,14,14);scroll.setWidget(self.properties);scroll.setMinimumWidth(270);self.property_dock=self.dock('속성 / 선택','propertiesDock',Qt.DockWidgetArea.RightDockWidgetArea,scroll);self.resizeDocks([self.property_dock],[305],Qt.Orientation.Horizontal)
    def make_timeline(self):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(10,8,10,8);row=QHBoxLayout();row.addWidget(label('작업 기록 · 클릭: 상세 · 더블클릭: 해당 단계로 복원',True));row.addStretch();row.addWidget(button('모든 분기 / 상세',self.history_dialog));v.addLayout(row);self.timeline=QListWidget();self.timeline.setObjectName('featureTimeline');self.timeline.setFlow(QListWidget.Flow.LeftToRight);self.timeline.setWrapping(False);self.timeline.setFixedHeight(66);self.timeline.setIconSize(QSize(24,24));self.timeline.itemClicked.connect(self.history_clicked);self.timeline.itemDoubleClicked.connect(lambda item:self.restore_history(item.data(Qt.ItemDataRole.UserRole)));v.addWidget(self.timeline);self.timeline_dock=self.dock('피처 / 작업 타임라인','historyDock',Qt.DockWidgetArea.BottomDockWidgetArea,w)
    def make_ai(self):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(12,12,12,12);self.provider=combo([('local','오프라인 치수 명령 · 키 불필요'),('openai','OpenAI · API 키 필요'),('ollama','로컬 AI · Ollama')]);v.addWidget(self.provider);self.ai_info=label('형상 이름과 치수를 입력하세요. 예: 구멍판 길이 80, 폭 60, 두께 6, 구멍 수 4 mm',True);v.addWidget(self.ai_info)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('API 키 · 이번 실행 동안만 사용');self.key.setVisible(False);v.addWidget(self.key);self.model=QLineEdit('gpt-4.1');self.model.setPlaceholderText('모델 이름');self.model.setVisible(False);v.addWidget(self.model);self.provider.currentIndexChanged.connect(self.provider_changed)
        self.prompt=QPlainTextEdit();self.prompt.setObjectName('designPrompt');self.prompt.setPlaceholderText('만들 형상과 치수, 바꿀 부분을 입력하세요.');self.prompt.setMinimumHeight(100);self.prompt.setMaximumHeight(170);v.addWidget(self.prompt);self.generate_button=button('설계 초안 생성',self.generate_draft,True);v.addWidget(self.generate_button);self.ai_result=QPlainTextEdit();self.ai_result.setReadOnly(True);self.ai_result.setMinimumHeight(130);v.addWidget(self.ai_result);self.accept_draft=button('검증된 초안 적용',self.apply_draft,True);self.accept_draft.setEnabled(False);v.addWidget(self.accept_draft);v.addWidget(label('명령은 치수·형상 데이터로 해석됩니다. 생성된 코드를 실행하지 않습니다. 적용한 결과는 작업 기록에 남습니다.',True));v.addStretch();self.ai_dock=self.dock('설계 명령 / AI','aiDock',Qt.DockWidgetArea.RightDockWidgetArea,w);self.tabifyDockWidget(self.property_dock,self.ai_dock);self.property_dock.raise_();self.ai_dock.hide()
    def message(self,text):self.statusBar().showMessage(text,15000)
    def title(self):self.setWindowTitle((self.document.design['name'] if self.document.design else '새 설계')+(' *' if self.document.dirty else '')+' — '+APP_NAME+' · Native')
    def set_busy(self,busy,message=''):
        self.busy=busy;self.progress.setVisible(busy);self.toolbar.setEnabled(not busy and not self.sketching);self.tree.setEnabled(not busy and not self.sketching);self.properties.setEnabled(not busy);self.timeline.setEnabled(not busy and not self.sketching);self.generate_button.setEnabled(not busy);self.accept_draft.setEnabled(not busy and self.last_draft is not None);self.editor.setEnabled(not busy)
        for key,a in self.actions.items():a.setEnabled(not busy and (not self.sketching or key in ('undo','redo','fit')))
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
        context=context or {};raw=deepcopy(data)
        def work():
            with KERNEL_LOCK:
                d=Design.model_validate(raw);r=preview(d);return d,r
        def done(result):
            d,self.result=result;self.document.commit(d,title,context,cursor);self.operation_serial+=1;self.viewport.load(self.result,fit or len(d.parts)==1 and not self.selected)
            if not self.selected or all(p.id!=self.selected for p in d.parts):self.selected=d.parts[0].id if d.parts else None
            self.rebuild_tree();self.select_part(self.selected);self.rebuild_timeline();self.autosave_document();self.title();self.message(title+' · 저장 가능한 유효한 CAD 형상입니다.')
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
            for part in self.document.design['parts']:
                node=QTreeWidgetItem(root,[part['name']+(' · 고정' if part['fixed'] else '')]);node.setIcon(0,icon('extrude'));node.setData(0,Qt.ItemDataRole.UserRole,('part',part['id']));node.setFlags(node.flags()|Qt.ItemFlag.ItemIsUserCheckable);node.setCheckState(0,Qt.CheckState.Unchecked if part['id'] in self.viewport.hidden else Qt.CheckState.Checked)
                base=QTreeWidgetItem(node,['기본 · '+TITLES[part['geometry']['kind']]]);base.setData(0,Qt.ItemDataRole.UserRole,('base',part['id']));base.setIcon(0,icon('sketch' if part['geometry']['kind']=='extrusion' else 'extrude'))
                for f in part['features']:
                    item=QTreeWidgetItem(node,[f['name']]);item.setData(0,Qt.ItemDataRole.UserRole,('feature',part['id'],f['id']));item.setIcon(0,icon('cut' if f['operation']=='cut' else 'extrude'));support=QTreeWidgetItem(item,[f"면 {f['face']+1} · 기준 {f['support_feature']} · {f['sketch']['thickness']:g} mm"])
                    for c in f['sketch'].get('entity_constraints',[]):QTreeWidgetItem(support,[f"{c['kind']} · {c['a'][:7]} → {c.get('b','')[:7]}"])
                node.setExpanded(True)
            mates=QTreeWidgetItem(root,['조립 구속']);mates.setIcon(0,icon('assembly'))
            for mate in self.document.design['mates']:
                item=QTreeWidgetItem(mates,[mate['kind']+' · '+mate['parent']+' → '+mate['child']]);item.setData(0,Qt.ItemDataRole.UserRole,('mate',mate['id']))
            mates.setExpanded(True)
        root.setExpanded(True);self.tree.blockSignals(False)
    def visibility_changed(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if data and data[0]=='part':self.viewport.visibility(data[1],item.checkState(0)==Qt.CheckState.Checked)
    def tree_clicked(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data:return
        if data[0] in ('part','base','feature'):self.select_part(data[1]);self.viewport.clear_face()
        if data[0]=='sketch':self.select_sketch(data[1])
        elif data[0]=='feature':self.show_feature(data[2])
        elif data[0]=='mate':self.show_mate(data[1])
        elif data[0]=='plane':self.plane.setCurrentIndex(self.plane.findData(data[1]));self.message(data[1]+' 평면 선택 · 스케치 작성 버튼을 누르세요.')
    def tree_edit(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data or self.busy or self.sketching:return
        if data[0]=='sketch':self.edit_saved_sketch(data[1])
        elif data[0]=='plane':self.start_sketch(data[1])
        elif data[0]=='feature':self.edit_sketch(data[2])
        elif data[0]=='base' and self.part()['geometry']['kind']=='extrusion':self.edit_sketch()
        elif data[0]=='mate':self.mate_dialog(data[1])
    def select_part(self,identifier):self.selected_sketch=None;self.selected=identifier;self.viewport.select(identifier);self.show_properties()
    def select_sketch(self,identifier):
        self.selected_sketch=identifier;self.selected=None;self.viewport.select(None);self.viewport.clear_face()
        saved=next((s for s in (self.document.design or {}).get('sketches',[]) if s['id']==identifier),None)
        if not saved:return
        clear_layout(self.property_layout);self.property_layout.addWidget(label(saved['name']));self.property_layout.addWidget(label(f"{len(saved['geometry']['entities'])}개 요소 · 단위 mm",True));self.property_layout.addWidget(button('스케치 편집',lambda:self.edit_saved_sketch(identifier),True));self.property_layout.addWidget(button('돌출 / 절삭',lambda:self.edit_saved_sketch(identifier,extrude=True)))
        def remove():
            data=deepcopy(self.document.design);data['sketches']=[s for s in data['sketches'] if s['id']!=identifier];self.selected_sketch=None;self.apply_design(data,'스케치 삭제',{'sketch_id':identifier})
        self.property_layout.addWidget(button('스케치 삭제',remove));self.property_layout.addStretch()
    def edit_saved_sketch(self,identifier,extrude=False):
        saved=next((s for s in (self.document.design or {}).get('sketches',[]) if s['id']==identifier),None)
        if not saved:return
        context=deepcopy(saved['context']);context.update(sketch_id=identifier,title=saved['name']);self.start_sketch(g=saved['geometry'],context=context)
        if extrude:self.editor.tabs.setCurrentIndex(3)
    def face_selected(self,identifier,face):
        if self.joint_picks is not None:self.receive_joint_face(identifier,face);return
        self.show_properties()
        if face:
            self.property_layout.insertWidget(1,label(f"선택 면 {face['index']+1} · "+('평면' if face['planar'] else '곡면')))
            if face['planar']:self.property_layout.insertWidget(2,button('이 면에서 스케치',self.start_face_sketch,True))
    def show_properties(self):
        clear_layout(self.property_layout);part=self.part()
        if not part:
            self.property_layout.addWidget(label('사람이 설계하고, 필요할 때 AI를 사용하세요.'));self.property_layout.addWidget(label('① 기준 평면 선택\n② 스케치 작성\n③ 닫힌 영역 돌출\n④ 면 선택 → 스케치 → 구멍 / 돌출',True));self.property_layout.addWidget(button('XY 평면에 스케치',lambda:self.start_sketch('XY'),True));self.property_layout.addWidget(button('시편 치수 설계',self.specimen_dialog));self.property_layout.addWidget(button('로봇 조립 설계',self.robot_dialog));self.property_layout.addStretch();return
        heading=label(part['name']);heading.setStyleSheet('font-size:17px;font-weight:600;');self.property_layout.addWidget(heading);form=QFormLayout();name=QLineEdit(part['name']);form.addRow('부품 이름',name);inputs={};g=part['geometry']
        for key,value in g.items():
            if key not in FIELDS:continue
            title,unit=FIELDS[key]
            if key=='hole_count':w=combo([(n,str(n)) for n in (0,2,4)]);w.setCurrentIndex(w.findData(value))
            else:w=number(value,0 if key in ('bore_diameter','flat_depth') else .01,2000,' '+unit)
            inputs[key]=w;form.addRow(title,w)
        self.property_layout.addLayout(form)
        if g['kind'] in ('round_specimen','flat_specimen','wafer'):self.property_layout.insertWidget(1,button('시편 치수 · 3D 미리보기',self.specimen_dialog,True))
        if any(m['child']==part['id'] and m['kind']!='rigid' for m in self.document.design['mates']):self.property_layout.insertWidget(1,button('관절 구동 · 간섭 확인',self.drive_joints,True))
        if g['kind']=='extrusion':self.property_layout.addWidget(button('기본 스케치 편집',lambda:self.edit_sketch()))
        self.property_layout.addWidget(label('배치 · 원점 기준'));tform=QFormLayout();trans={}
        for key,value in part['transform'].items():w=number(value,-360 if key.startswith('r') else -5000,360 if key.startswith('r') else 5000,' °' if key.startswith('r') else ' mm');trans[key]=w;tform.addRow(key.upper(),w)
        bound=next((m for m in self.document.design['mates'] if m['child']==part['id']),None)
        if bound:
            for w in trans.values():w.setEnabled(False);w.setToolTip('조인트로 배치된 부품입니다. 관절 구동 또는 조인트 오프셋을 편집하세요.')
            self.property_layout.addWidget(button('조인트 오프셋 편집',lambda:self.mate_dialog(bound['id'])))
        self.property_layout.addLayout(tform);fixed=QCheckBox('조립 기준 부품으로 고정');fixed.setChecked(part['fixed']);fixed.setEnabled(bound is None);self.property_layout.addWidget(fixed)
        def apply():
            if self.busy:return
            data=deepcopy(self.document.design);p=next(p for p in data['parts'] if p['id']==part['id']);p['name']=name.text().strip() or part['name'];p['fixed']=fixed.isChecked()
            for key,w in inputs.items():p['geometry'][key]=w.currentData() if isinstance(w,QComboBox) else w.value()
            for key,w in trans.items():p['transform'][key]=w.value()
            self.apply_design(data,'부품 치수 / 배치 편집',{'part_id':part['id'],'tool':'parameters'})
        self.property_layout.addWidget(button('치수 / 배치 적용',apply,True));self.property_layout.addWidget(button('부품 색상',lambda:self.color_part(part['id'])));self.property_layout.addWidget(button('부품 복제',self.duplicate_part));self.property_layout.addWidget(button('선택 부품 삭제',self.delete_part));self.property_layout.addStretch()
    def color_part(self,identifier):
        color=QColorDialog.getColor(QColor(self.part()['color']),self,'부품 색상')
        if color.isValid():data=deepcopy(self.document.design);next(p for p in data['parts'] if p['id']==identifier)['color']=color.name();self.apply_design(data,'부품 색상 변경',{'part_id':identifier})
    def show_feature(self,identifier):
        part=self.part();f=next(f for f in part['features'] if f['id']==identifier);clear_layout(self.property_layout);self.property_layout.addWidget(label(f['name']));self.property_layout.addWidget(label(f"부품: {part['name']}\n참조 피처: {f['support_feature']}\n선택 면: {f['face']+1}\n법선: {f['normal']}\n작업: {f['operation']}\n깊이: {f['sketch']['thickness']:g} mm\n스케치 요소: {len(f['sketch']['entities'])}\n구속: {len(f['sketch']['entity_constraints'])}",True));self.property_layout.addWidget(button('스케치 / 구속 편집',lambda:self.edit_sketch(identifier),True));self.property_layout.addWidget(button('이 피처와 뒤의 피처 제거',lambda:self.remove_feature(identifier)));self.property_layout.addStretch()
    def remove_feature(self,identifier):
        data=deepcopy(self.document.design);p=next(p for p in data['parts'] if p['id']==self.selected);i=next(i for i,f in enumerate(p['features']) if f['id']==identifier);removed=p['features'][i:];p['features']=p['features'][:i];self.apply_design(data,'피처 제거',{'part_id':p['id'],'removed_features':[f['id'] for f in removed]})
    def add_preset(self,kind):
        if self.busy or self.sketching:return
        if kind=='robot_arm':data=preset(kind).model_dump()
        elif self.document.design:
            data=deepcopy(self.document.design);p=part_default(kind,'part-'+uid()).model_dump();p['transform']['x']=(self.result['stats']['max'][0]+80) if self.result else 100;data['parts'].append(p)
        else:data=preset(kind).model_dump()
        self.apply_design(data,TITLES[kind]+' 생성',{'tool':'primitive','kind':kind},fit=True)
    def duplicate_part(self):
        if not self.part():return
        data=deepcopy(self.document.design);p=deepcopy(self.part());p['id']='part-'+uid();p['name']+=' 복사';p['fixed']=False;p['transform']['x']+=60;data['parts'].append(p);self.apply_design(data,'부품 복제',{'part_id':self.selected},fit=True)
    def delete_part(self):
        if not self.part() or self.busy:return
        if len(self.document.design['parts'])==1:self.show_error('마지막 부품을 없애려면 새 설계를 사용하세요. 현재 프로젝트는 저장 후 남길 수 있습니다.');return
        data=deepcopy(self.document.design);data['parts']=[p for p in data['parts'] if p['id']!=self.selected];data['mates']=[m for m in data['mates'] if self.selected not in (m['parent'],m['child'])];data['joint_frames']=[f for f in data.get('joint_frames',[]) if f['mate_id'] in {m['id'] for m in data['mates']}];self.apply_design(data,'부품 삭제',{'part_id':self.selected},fit=True)
    def start_sketch(self,plane='XY',g=None,context=None):
        if self.busy or self.sketching:return
        if self.joint_picks is not None:self.cancel_joint_pick()
        context=context or {'plane':plane,'title':f'새 스케치 · {plane} 기준 평면'};self.sketching=True;self.editor.start(g,context);self.stack.setCurrentWidget(self.editor);self.property_dock.hide();self.ai_dock.hide();self.browser_dock.hide();self.timeline_dock.hide();self.toolbar.hide();self.set_busy(False);self.editor.tabs.setCurrentIndex(0)
    def start_face_sketch(self):
        if not self.viewport.face:self.message('3D 모델의 평평한 면을 먼저 클릭하세요.');return
        identifier,face=self.viewport.face
        if not face or not face['planar']:self.message('곡면에는 스케치를 시작할 수 없습니다. 평평한 면을 선택하세요.');return
        part=next(p for p in self.document.design['parts'] if p['id']==identifier);context={'part_id':identifier,'face':deepcopy(face),'support_feature':part['features'][-1]['id'] if part['features'] else 'base','title':f"{part['name']} · 면 {face['index']+1} 스케치"};self.start_sketch(context=context)
    def edit_sketch(self,feature_id=None):
        if isinstance(feature_id,bool):feature_id=None
        if self.selected_sketch:self.edit_saved_sketch(self.selected_sketch);return
        p=self.part()
        if not p:return
        if feature_id:
            f=next(f for f in p['features'] if f['id']==feature_id);self.start_sketch(g=f['sketch'],context=dict(part_id=p['id'],feature_id=f['id'],operation=f['operation'],title=f['name']+' 편집'));return
        if p['geometry']['kind']!='extrusion':self.message('이 부품은 치수로 편집합니다. 새 구멍은 면을 선택해 스케치를 만드세요.');return
        self.start_sketch(g=p['geometry'],context=dict(part_id=p['id'],edit_base=True,title=p['name']+' · 기본 스케치 편집'))
    def cancel_sketch(self):
        if self.busy:return
        self.sketching=False;self.editor.stop();self.stack.setCurrentWidget(self.viewport);self.toolbar.show();self.browser_dock.show();self.property_dock.show();self.timeline_dock.show();self.set_busy(False);self.show_properties();self.viewport.window.Render()
    def finish_sketch(self,g,context,operation):
        if self.busy:return
        # Editing a solid's generating sketch still recomputes that feature.
        # New/open sketches can finish without creating a solid at all.
        if context.get('edit_base') or context.get('feature_id'):
            self.apply_sketch(g,context,operation);return
        if not g['entities'] and not context.get('sketch_id'):self.cancel_sketch();return
        data=deepcopy(self.document.design) if self.document.design else dict(name='스케치 설계',parts=[],mates=[],sketches=[])
        identifier=context.get('sketch_id') or 'sketch-'+uid();saved_context={k:deepcopy(v) for k,v in context.items() if k not in ('tool_actions','sketch_id')};saved_context['operation']=operation
        old=next((s for s in data.get('sketches',[]) if s['id']==identifier),None)
        saved=dict(id=identifier,name=old['name'] if old else '스케치 '+str(len(data.get('sketches',[]))+1),geometry=g,context=saved_context)
        data['sketches']=[s for s in data.get('sketches',[]) if s['id']!=identifier]+[saved]
        context.update(tool='sketch',sketch_id=identifier,sketch=g)
        def complete():self.cancel_sketch();self.select_sketch(identifier)
        self.apply_design(data,'스케치 종료 · '+saved['name'],context,fit=True,after=complete)
    def apply_sketch(self,g,context,operation):
        if self.busy:return
        data=deepcopy(self.document.design) if self.document.design else dict(name='스케치 설계',parts=[],mates=[]);title='스케치 돌출 생성'
        if context.get('edit_base'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);p['geometry']=g;title='기본 스케치 편집'
        elif context.get('feature_id'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);f=next(f for f in p['features'] if f['id']==context['feature_id']);f['sketch']=g;f['operation']=operation;title='면 스케치 피처 편집'
        elif context.get('face'):
            p=next(p for p in data['parts'] if p['id']==context['part_id']);face=context['face'];title='구멍 / 포켓 절삭' if operation=='cut' else '면 스케치 돌출';f=dict(id='feature-'+uid(),name=f"{title} {len(p['features'])+1}",face=face['index'],support_face_count=face['face_count'],support_feature=context['support_feature'],origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'],operation=operation,sketch=g);p['features'].append(f);context['feature_id']=f['id']
        else:
            plane=context.get('plane','XY');transform={'rx':90} if plane=='XZ' else {'rx':90,'rz':90} if plane=='YZ' else {};p=Part(id='part-'+uid(),name='스케치 돌출 '+str(len(data['parts'])+1),geometry=g,transform=transform).model_dump();data['parts'].append(p);context['part_id']=p['id']
        if context.get('sketch_id'):data['sketches']=[s for s in data.get('sketches',[]) if s['id']!=context['sketch_id']]
        context.update(tool='sketch',operation=operation,sketch=g);self.apply_design(data,title,context,fit=True,after=self.cancel_sketch)
    def fit(self):self.editor.canvas.fit() if self.sketching else self.viewport.fit()
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
        if c.get('tool_actions'):lines.append('스케치 도구: '+' → '.join(a['tool'] for a in c['tool_actions']))
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
        mate=next(m for m in self.document.design['mates'] if m['id']==identifier);clear_layout(self.property_layout);self.property_layout.addWidget(label('조립 구속 · '+mate['kind']));self.property_layout.addWidget(label(json.dumps(mate,ensure_ascii=False,indent=2),True));self.property_layout.addWidget(button('관절 구동 · 간섭 확인',self.drive_joints,True));self.property_layout.addWidget(button('고급 구속 / 오프셋 편집',lambda:self.mate_dialog(identifier)))
        def remove():data=deepcopy(self.document.design);data['mates']=[m for m in data['mates'] if m['id']!=identifier];data['joint_frames']=[f for f in data.get('joint_frames',[]) if f['mate_id']!=identifier];self.apply_design(data,'조립 구속 삭제',{'mate_id':identifier})
        self.property_layout.addWidget(button('구속 삭제',remove));self.property_layout.addStretch()
    def mate_dialog(self,identifier=None):
        if isinstance(identifier,bool):identifier=None
        if self.busy or self.sketching:return
        if not self.document.design or len(self.document.design['parts'])<2:self.message('조립 구속에는 부품이 두 개 이상 필요합니다.');return
        existing=next((m for m in self.document.design['mates'] if m['id']==identifier),None);parts=self.document.design['parts'];dialog=QDialog(self);dialog.setWindowTitle('조립 구속');dialog.resize(440,680);v=QVBoxLayout(dialog);f=QFormLayout();kind=combo([('rigid','강체 · 0 자유도'),('revolute','회전 · RZ'),('slider','슬라이더 · Z'),('cylindrical','원통 · Z + RZ')]);parent=combo([(p['id'],p['name']) for p in parts]);child=combo([(p['id'],p['name']) for p in parts]);child.setCurrentIndex(1);pa=QComboBox();ca=QComboBox()
        def populate():
            for c,pick in ((pa,parent),(ca,child)):
                old=c.currentData();c.clear();p=next(p for p in parts if p['id']==pick.currentData());model=Part.model_validate(p)
                for key in anchors(model.geometry):c.addItem(key,key)
                c.setCurrentIndex(max(0,c.findData(old)))
        parent.currentIndexChanged.connect(populate);child.currentIndexChanged.connect(populate);populate();fields={}
        for title,w in [('종류',kind),('부모 부품',parent),('부모 기준점',pa),('자식 부품',child),('자식 기준점',ca)]:f.addRow(title,w)
        for key in ('x','y','z','rx','ry','rz'):w=number(existing[key] if existing else 0,-360 if key.startswith('r') else -5000,360 if key.startswith('r') else 5000,' °' if key.startswith('r') else ' mm');fields[key]=w;f.addRow(key.upper(),w)
        v.addLayout(f);ground=QCheckBox('부모가 최상위 부품이면 조립 기준으로 고정');ground.setChecked(True);v.addWidget(ground);v.addWidget(label('연결된 부모의 치수·배치·관절 값을 바꾸면 자식 부품이 따라갑니다. 하나의 자식에는 한 연결만 허용하며 닫힌 조립 고리는 지원하지 않습니다.',True));buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);v.addWidget(buttons)
        if existing:
            kind.setCurrentIndex(kind.findData(existing['kind']));parent.setCurrentIndex(parent.findData(existing['parent']));child.setCurrentIndex(child.findData(existing['child']));pa.setCurrentIndex(pa.findData(existing['parent_anchor']));ca.setCurrentIndex(ca.findData(existing['child_anchor']))
        if existing and any(f['mate_id']==identifier for f in self.document.design.get('joint_frames',[])):
            for w in (parent,child,pa,ca):w.setEnabled(False);w.setToolTip('선택한 면 좌표계로 연결된 조인트입니다. 부품/면 변경은 조인트를 삭제하고 다시 선택하세요.')
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        m=dict(id=identifier or 'mate-'+uid(),kind=kind.currentData(),parent=parent.currentData(),child=child.currentData(),parent_anchor=pa.currentData(),child_anchor=ca.currentData(),**{key:w.value() for key,w in fields.items()});data=deepcopy(self.document.design);data['mates']=[mate for mate in data['mates'] if mate['id']!=identifier]+[m]
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
        self.document=Document();self.result=None;self.selected=None;self.selected_sketch=None;self.last_draft=None;self.viewport.load(None);self.viewport.hidden.clear();self.rebuild_tree();self.rebuild_timeline();self.show_properties();self.title();self.autosave.unlink(missing_ok=True)
    def open_project(self,path=None,recovery=False):
        if self.busy or self.sketching:return
        if not recovery and not self.check_save():return
        if not path:path,_=QFileDialog.getOpenFileName(self,'CAD 프로젝트 열기',str(self.document.path.parent if self.document.path else ROOT/'examples'),'CAD 프로젝트 (*.cad.json *.json)')
        if not path:return
        path=Path(path)
        def work():
            with KERNEL_LOCK:project=read_project(path);r=preview(project.design);return project,r
        def done(result):
            project,self.result=result;self.document.load(project,None if recovery else path);self.operation_serial+=1;self.last_draft=None;self.accept_draft.setEnabled(False);self.document.dirty=recovery;self.selected=project.design.parts[0].id if project.design.parts else None;self.selected_sketch=None;self.prompt.setPlainText(project.prompt);self.viewport.load(self.result,True);self.rebuild_tree();self.rebuild_timeline();self.show_properties();self.title();self.message('자동 저장한 설계를 복구했습니다.' if recovery else '프로젝트와 작업 기록을 열었습니다.')
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
    def provider_changed(self):
        provider=self.provider.currentData();self.key.setVisible(provider=='openai');self.model.setVisible(provider!='local');self.model.setText('gpt-4.1' if provider=='openai' else 'qwen3:8b');self.ai_info.setText({'local':'인터넷·API 키 없이 형상 이름과 치수를 해석합니다. 자유로운 문장을 이해하는 AI 모델은 아닙니다.','openai':'프롬프트와 현재 설계를 OpenAI API로 보냅니다. API 사용료가 발생할 수 있습니다. 키는 저장하지 않습니다.','ollama':'이 PC의 Ollama (127.0.0.1:11434)에 연결합니다. 설치된 모델 이름을 입력하세요. 인터넷 API 키 없이 자유로운 프롬프트를 처리합니다.'}[provider]);self.last_draft=None;self.accept_draft.setEnabled(False)
    def generate_draft(self):
        if self.busy or self.sketching:return
        prompt=self.prompt.toPlainText().strip()
        if not prompt:self.message('설계 명령을 입력하세요.');return
        if len(prompt)>4000:self.show_error('명령은 4,000자 이내로 입력하세요.');return
        provider=self.provider.currentData();key=self.key.text().strip() or os.getenv('OPENAI_API_KEY','');model=self.model.text().strip();request=DraftRequest(prompt=prompt,current=self.document.design,selected_part=self.selected,mode=(self.document.design or {}).get('mode','specimen'));serial=self.operation_serial;self.last_draft=None;self.accept_draft.setEnabled(False)
        def work():
            from ..planner import local_draft,openai_draft
            if provider=='local':result=local_draft(request)
            elif provider=='ollama':
                from .local_ai import ollama_draft
                result=ollama_draft(request,model)
            else:
                if not key:raise ValueError('API 키를 입력하거나 OPENAI_API_KEY 환경변수를 설정하세요.')
                from openai import OpenAI
                client=OpenAI(api_key=key,base_url='https://api.openai.com/v1',timeout=75,max_retries=0)
                # Pass the chosen model without changing process-wide environment variables.
                from .local_ai import cloud_draft
                result=cloud_draft(request,client,model)
            with KERNEL_LOCK:d=Design.model_validate(result['design']);r=preview(d)
            return result,d,r
        def done(result):
            response,d,r=result;self.last_draft=dict(response=response,design=d.model_dump(),preview=r,serial=serial,provider=provider,prompt=prompt);self.ai_result.setPlainText(response['summary']+'\n\n'+'\n'.join(response.get('changes',[])+response.get('assumptions',[]))+f"\n\n형상 검증: {r['stats']['parts']}개 부품 · {r['stats']['volume']:.2f} mm³");self.accept_draft.setEnabled(True);self.message('설계 초안 생성 완료 · 내용을 확인하고 적용하세요.')
        self.run(work,done,'설계 초안 생성 · 형상 검증 중…',failed=lambda text:self.ai_result.setPlainText(text))
    def apply_draft(self):
        draft=self.last_draft
        if not draft or self.busy:return
        if draft['serial']!=self.operation_serial:self.show_error('초안 생성 이후 설계가 변경되었습니다. 현재 설계로 초안을 다시 생성하세요.');return
        self.document.prompt=draft['prompt'];context=dict(source='openai' if draft['provider']=='openai' else 'local',provider=draft['provider'],prompt=draft['prompt'],summary=draft['response']['summary'],assumptions=draft['response'].get('assumptions',[]),tool='prompt');self.apply_design(draft['design'],'설계 명령 적용',context,fit=True);self.last_draft=None;self.accept_draft.setEnabled(False)
    def help_dialog(self):
        d=QDialog(self);d.setWindowTitle('사용 방법 · 지원 범위');d.resize(800,650);v=QVBoxLayout(d);text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText('Prompt CAD Studio · Native\n\n1. 스케치와 돌출\n상단에서 XY / XZ / YZ를 선택하고 스케치를 작성하세요. L 직선, C 원, R 사각형, D 선택 요소 치수. 좌표 입력으로 정밀하게 작성할 수도 있습니다. 상단 스케치 종료는 열린 선도 저장합니다. 설계 브라우저의 스케치를 다시 열고 돌출 탭에서 닫힌 영역과 깊이를 선택해 입체를 만드세요.\n\n2. 면 선택과 구멍\n3D 모델의 평평한 면을 클릭 → 선택 면에서 스케치 → 원 등을 작성 → 안쪽으로 파내기 → 깊이 입력. 면의 모서리는 보조선으로 투영할 수 있습니다.\n\n3. 스케치 구속\n구속 탭의 A / B / 점을 지정합니다. 원점 고정, 수평·수직, 거리·직경·각도, 일치·접선 등 20종. 자동 구속은 스냅한 원점·끝점·중간점·교점의 관계를 보존합니다. 자유도 0이면 완전 구속입니다.\n\n4. 조립\n부품을 2개 이상 만든 후 조립 구속을 추가하세요. 강체, 회전, 슬라이더, 원통 연결을 지원합니다. 기준점·오프셋·관절 값을 편집하면 자식 부품이 따라갑니다.\n\n5. 기록\n하단 기록을 클릭하면 실제 변경 필드, 도구, 면, 피처, 구속을 확인할 수 있습니다. 더블클릭으로 복원합니다. 복원 후 수정한 분기도 모두 저장합니다. 스케치 내부의 도구 작업은 스케치 완료 시 함께 저장합니다.\n\n6. 설계 AI\n오프라인 치수 명령은 키 없이 작동합니다. 자유 문장은 OpenAI API 또는 이 PC의 Ollama에 연결하세요. 초안을 검증한 후 적용하면 기록에 남습니다.\n\n7. 파일\n.cad.json은 편집 가능한 설계와 작업 기록입니다. STEP은 정확한 CAD 형상, STL은 메시입니다. .f3d / .ipt는 Autodesk 변환 패키지에 들어 있는 STEP과 스크립트를 해당 Autodesk 앱에서 실행해 변환해야 합니다. Autodesk 작업 기록을 그대로 재구성하지는 않습니다.\n\n지원 범위\nFusion과 동일한 전체 기능은 아닙니다. 평면 스케치와 돌출 / 절삭, 지정한 기본 형상, 조립 트리를 지원합니다. 스윕·로프트·곡면·3D 필렛·나사·닫힌 조립 고리·동역학은 아직 없습니다. 최대 12부품, 부품당 8개 면 피처, 스케치당 128요소 / 160구속. 완료한 스케치도 프로젝트·자동 저장·기록에 포함됩니다. 편집 중인 미완료 작업은 종료 버튼을 눌러 반영하세요.\n\n마우스\n3D: 왼쪽 드래그 회전, 가운데 이동, 휠 확대, 클릭 면 선택.\n스케치: 클릭 작성, 가운데 / 오른쪽 드래그 이동, 휠 확대. Shift / Ctrl 클릭 다중 선택. Enter 그리기 완료, Ctrl+Enter 스케치 종료, Esc 선택 도구, D 치수, Ctrl+A 전체 선택, F 화면 맞춤. 빈 곳 드래그로 상자 선택. 선 위 추천점은 자동 구속이 켜져 있을 때 관계를 유지합니다.');v.addWidget(text);v.addWidget(button('닫기',d.accept));d.exec()
    def closeEvent(self,event):
        if self.busy:self.message('실행 중인 작업이 끝난 뒤 종료하세요.');event.ignore();return
        if self.sketching:
            answer=QMessageBox.question(self,'미완료 스케치','완료하지 않은 스케치를 버리고 종료할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
            self.cancel_sketch()
        if not self.check_save():event.ignore();return
        self.autosave_document();self.editor.stop();self.viewport.shutdown();event.accept()
