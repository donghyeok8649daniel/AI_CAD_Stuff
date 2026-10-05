"""Research repository and local reference snapshots, with visible transmission preview."""
from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPlainTextEdit,
    QListWidget,QListWidgetItem,QAbstractItemView,QFileDialog,QTabWidget,QWidget,QDialogButtonBox,QSplitter,QScrollArea)

from ..github_reference import (GitHubReader, existing_token, TOKEN_URL,
    repository_index_reference,is_repository_snapshot)
from ..references import read_reference, merge_references
from .ai_task import AITask
from .widgets import button,label

MAX_VISIBLE_REPOSITORY_PATHS=2000

class ReferenceDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.setWindowTitle('연구 저장소 · AI 참고자료');self.resize(830,740)
        self.refs=deepcopy(parent.reference_materials);self.task=None;self.connection=None;self.reader=None;self.callback=None
        self.settings_path=parent.data_dir/'github-reference-settings.json'
        try:settings=json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):settings={}
        if not isinstance(settings,dict):settings={}
        frame=QVBoxLayout(self);body=QWidget();root=QVBoxLayout(body);root.setContentsMargins(0,0,0,0)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(body);frame.addWidget(self.scroll,1)
        root.addWidget(label('저장소 주소를 연결하면 전체 경로 목록과 읽을 수 있는 문서의 발췌가 자동 추가됩니다. 범위를 비우면 저장소 전체입니다. 첨부 내용은 다음 설계·질문과 함께 선택한 AI 서비스로 전송됩니다.',True))
        tabs=QTabWidget();root.addWidget(tabs)
        github=QWidget();layout=QVBoxLayout(github);tabs.addTab(github,'GitHub 연구 저장소')
        form=QFormLayout();self.repo=QLineEdit(str(settings.get('repo','')));self.repo.setPlaceholderText('https://github.com/owner/repository')
        self.branch=QLineEdit(str(settings.get('branch','')));self.branch.setPlaceholderText('비워 두면 기본 브랜치')
        self.scope_path=QLineEdit(str(settings.get('scope_path','')));self.scope_path.setObjectName('referenceRepositoryScope');self.scope_path.setPlaceholderText('비워 두면 전체 저장소 · 예: docs, experiments')
        self.key=QLineEdit(getattr(parent,'github_reference_token',''));self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('비공개 저장소: Contents 읽기 토큰 · 이번 실행 동안만 사용')
        form.addRow('저장소',self.repo);form.addRow('브랜치 / 태그',self.branch);form.addRow('참고 범위 · 선택 사항',self.scope_path);form.addRow('GitHub 토큰',self.key);layout.addLayout(form)
        row=QHBoxLayout();self.connect_button=button('연결 · 저장소 참고자료 자동 추가',self.connect_repository,True);self.connect_button.setObjectName('referenceRepositoryConnect');self.existing_button=button('기존 Git 로그인 사용',lambda:self.connect_repository(True))
        self.token_button=button('읽기 토큰 발급 ↗',lambda:QDesktopServices.openUrl(QUrl(TOKEN_URL)))
        for w in (self.connect_button,self.existing_button,self.token_button):w.setAutoDefault(False);row.addWidget(w)
        layout.addLayout(row);layout.addWidget(label('공개 저장소는 토큰 없이 연결합니다. 비공개 저장소는 해당 저장소의 Contents: Read 권한만 필요합니다. 저장소를 변경하거나 코드를 실행하지 않습니다.',True))
        self.filter=QLineEdit();self.filter.setPlaceholderText('전체 저장소 경로 검색 · 예: README, specimen, material');layout.addWidget(self.filter)
        self.list_count=label('경로 색인 없음');layout.addWidget(self.list_count)
        self.files=QListWidget();self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.files.setMinimumHeight(90);self.files.setMaximumHeight(150);layout.addWidget(self.files)
        row=QHBoxLayout();self.fetch_button=button('선택 문서를 참고자료에 추가',self.fetch_selected);self.fetch_button.setEnabled(False);row.addWidget(self.fetch_button)
        self.disconnect_button=button('저장소 연결 해제',self.disconnect);row.addWidget(self.disconnect_button);layout.addLayout(row)
        local=QWidget();local_layout=QVBoxLayout(local);tabs.addTab(local,'로컬 파일 첨부')
        local_layout.addWidget(label('PDF·TXT·MD·CSV·JSON·YAML·TOML·텍스트 코드 파일을 첨부할 수 있습니다. PDF는 텍스트만 읽으며 스캔·도면·그림은 해석하지 않습니다.',True))
        self.local_button=button('파일 선택…',self.add_local);local_layout.addWidget(self.local_button);local_layout.addStretch()
        root.addWidget(label('AI가 읽을 자료 · 최대 8개 / 합계 60,000자 · 자료당 20,000자. 전체 경로 색인과 제한된 문서 발췌를 구분해 표시합니다. 바이너리·대형 파일·외부 하위 저장소는 실행하거나 읽지 않습니다.',True))
        split=QSplitter();root.addWidget(split,1);self.attached=QListWidget();self.attached.setMinimumWidth(200);split.addWidget(self.attached)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);self.preview.setMinimumHeight(150);self.preview.setPlaceholderText('자료를 선택하면 실제로 전달할 내용과 출처를 확인할 수 있습니다.');split.addWidget(self.preview);split.setSizes([230,530])
        row=QHBoxLayout();self.remove_button=button('선택 자료 삭제',self.remove_selected);self.clear_button=button('자료 모두 비우기',self.clear_references);row.addWidget(self.remove_button);row.addWidget(self.clear_button);root.addLayout(row)
        self.status=QPlainTextEdit();self.status.setReadOnly(True);self.status.setMaximumHeight(64);root.addWidget(self.status)
        root.addWidget(label('첨부 본문과 토큰은 프로젝트·설정에 저장하지 않습니다. 앱 재시작이나 새 설계에서는 자료를 다시 선택하세요. 연결 주소와 브랜치만 기억합니다.',True))
        buttons=QDialogButtonBox();self.use_button=buttons.addButton('자료 사용',QDialogButtonBox.ButtonRole.AcceptRole);buttons.addButton('닫기',QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);frame.addWidget(buttons)
        self.cancel_button=button('조회 취소',self.cancel);self.cancel_button.hide();frame.addWidget(self.cancel_button)
        self.filter.textChanged.connect(self.filter_files);self.attached.currentRowChanged.connect(self.show_reference)
        for field in (self.repo,self.branch,self.scope_path,self.key):field.textEdited.connect(self.invalidate_connection)
        self.refresh_references()
        available=self.screen().availableGeometry();self.resize(min(830,available.width()-40),min(740,available.height()-70))

    def start(self,fn,callback):
        if self.task:return
        self.callback=callback;self.task=AITask(fn,self)
        self.task.completed.connect(self.completed,Qt.ConnectionType.QueuedConnection);self.task.failed.connect(self.failed,Qt.ConnectionType.QueuedConnection)
        self.set_running(True);self.status.setPlainText('자료 조회 중…');self.task.start()

    def set_running(self,running):
        for w in (self.repo,self.branch,self.scope_path,self.key,self.connect_button,self.existing_button,self.fetch_button,self.local_button,self.use_button,self.remove_button,self.clear_button,self.disconnect_button):w.setEnabled(not running)
        self.fetch_button.setEnabled(not running and self.connection is not None);self.cancel_button.setVisible(running)

    def cancel(self):
        if self.task:self.task.cancel();self.task=None
        self.set_running(False);self.status.setPlainText('자료 조회를 취소했습니다.')

    @Slot(object)
    def completed(self,packet):
        task,result=packet
        if task is not self.task:return
        self.task=None;self.set_running(False)
        try:self.callback(result)
        except Exception as exc:self.status.setPlainText(str(exc)[:1000])

    @Slot(object)
    def failed(self,packet):
        task,message=packet
        if task is not self.task:return
        self.task=None;self.set_running(False);self.status.setPlainText(message[:1000])

    def invalidate_connection(self):
        self.connection=None;self.reader=None;self.repository_rows=[];self.files.clear();self.list_count.setText('경로 색인 없음');self.fetch_button.setEnabled(False)
        self.status.setPlainText('연결 정보가 변경되었습니다. 다시 연결하세요.')

    def connect_repository(self,use_existing=False):
        repo=self.repo.text();branch=self.branch.text();path=self.scope_path.text();token=self.key.text()
        self.invalidate_connection()
        def work(control,progress):
            chosen=existing_token(repo) if use_existing else token
            reader=GitHubReader(chosen);connection=reader.connect(repo,branch,control,path)
            return reader,connection,True
        self.start(work,self.connected)

    def connected(self,result):
        self.reader,self.connection=result[:2];auto_add=len(result)>2 and bool(result[2]);info=self.connection;self.key.setText(self.reader.token)
        self.parent().github_reference_token=self.reader.token
        self.repo.setText(info['repo']);self.branch.setText(info['branch'])
        self.scope_path.setText(info.get('scope_path',''))
        self.repository_rows=info.get('entries',info['files'])
        self.filter_files();self.fetch_button.setEnabled(True)
        mode='private' if info['private'] else 'public'
        self.status.setPlainText(f"✓ {info['repo']} · {mode} · {info['login'] or 'public read'}\n{info['branch']} @ {info['revision'][:12]} · /{info.get('scope_path','')} · 경로 {len(self.repository_rows)}개 / 읽기 후보 {len(info['files'])}개"+('\n경로 목록이 일부 생략되었습니다. 전체 저장소를 읽었다고 간주하지 않습니다.' if info['truncated'] else ''))
        try:
            self.settings_path.parent.mkdir(parents=True,exist_ok=True);temp=self.settings_path.with_suffix('.tmp')
            settings={'repo':info['repo'],'branch':info['branch']}
            if info.get('scope_path'):settings['scope_path']=info['scope_path']
            temp.write_text(json.dumps(settings),encoding='utf-8');temp.replace(self.settings_path)
        except OSError:self.status.appendPlainText('연결 주소를 저장하지 못했습니다. 이번 실행에서만 사용합니다.')
        if auto_add:self.add_repository_snapshot()

    def filter_files(self):
        query=self.filter.text().casefold()
        rows=getattr(self,'repository_rows',[])
        selected={item.data(Qt.ItemDataRole.UserRole)['path'] for item in self.files.selectedItems()}
        readable={row['path']:row for row in (self.connection or {}).get('files',[])}
        matching=[row for row in rows if query in row['path'].casefold()]
        self.files.clear()
        for row in matching[:MAX_VISIBLE_REPOSITORY_PATHS]:
            supported=row['path'] in readable
            item=QListWidgetItem(f"{row['path']}  ·  {row.get('size',0)/1000:.1f} KB"+('' if supported else ' · 경로 색인만'))
            item.setData(Qt.ItemDataRole.UserRole,readable.get(row['path'],row))
            if not supported:
                item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip('경로·버전 메타데이터만 포함합니다. 바이너리, 대형 파일, 디렉터리, 심볼릭 링크, 외부 하위 저장소의 내용은 첨부하지 않습니다.')
            self.files.addItem(item)
            if supported and row['path'] in selected:item.setSelected(True)
        self.list_count.setText(f'전체 색인 {len(rows):,}개 · 검색 결과 {len(matching):,}개 · 표시 {self.files.count():,}개'+
            (' · 경로 검색으로 나머지도 찾을 수 있습니다.' if len(matching)>MAX_VISIBLE_REPOSITORY_PATHS else ''))

    def add_repository_snapshot(self):
        if not self.connection or self.task:return
        info=deepcopy(self.connection);reader=self.reader
        base=[ref for ref in self.refs if not is_repository_snapshot(ref,info['repo'])]
        slots=8-len(base);characters=60000-sum(len(ref.text) for ref in base)
        if slots<1 or characters<500:
            self.status.appendPlainText('경로 목록 연결은 완료했지만 참고자료 용량이 가득 차 자동 추가하지 않았습니다. 기존 자료를 일부 제거한 뒤 다시 연결하세요.')
            return
        index=repository_index_reference(info,max_chars=min(20000,characters))
        self.refs=merge_references(base,[index]);self.refresh_references()
        # Show the repository in the attachment list immediately after its
        # immutable metadata connects; fetch excerpts in a cancellable worker.
        self.start(lambda control,progress:reader.snapshot(info,control,max_chars=characters,max_references=min(3,slots)),
                   lambda refs:self.finish_repository_snapshot(base,refs,info))
        self.status.setPlainText(f"✓ {info['repo']} · /{info.get('scope_path','')} 경로 색인을 추가했습니다. 문서 발췌 조회 중…")

    def finish_repository_snapshot(self,base,refs,info):
        self.refs=merge_references(base,refs);self.refresh_references()
        scope='일부 경로' if info.get('truncated') else '전체 선택 범위 경로'
        self.status.setPlainText(f"✓ {info['repo']} · 저장소 참고자료 자동 추가 완료\n{scope} {len(info.get('entries',info['files']))}개를 색인했습니다. AI에는 미리보기에 보이는 제한된 발췌만 전달됩니다. 정확한 문서는 목록에서 추가 선택할 수 있습니다.")

    def fetch_selected(self):
        if not self.connection:return
        rows=[i.data(Qt.ItemDataRole.UserRole) for i in self.files.selectedItems() if not i.isHidden()]
        if not rows:self.add_repository_snapshot();return
        reader=self.reader;connection=deepcopy(self.connection)
        self.start(lambda control,progress:reader.fetch(connection,rows,control),self.add_references)

    def add_local(self):
        paths,_=QFileDialog.getOpenFileNames(self,'AI 참고자료 첨부','','Reference (*.pdf *.txt *.md *.rst *.csv *.tsv *.json *.yaml *.yml *.toml *.py *.c *.h *.cpp *.hpp *.ino *.xml)')
        if not paths:return
        if len(paths)>8:self.status.setPlainText('한 번에 최대 8개 자료를 선택하세요.');return
        self.start(lambda control,progress:[read_reference(p,control.check) for p in paths],self.add_references)

    def add_references(self,refs):
        self.refs=merge_references(self.refs,refs);self.refresh_references()
        self.status.setPlainText('자료를 읽었습니다. 내용 미리보기를 확인하고 자료 사용을 누르세요.')

    def refresh_references(self):
        self.attached.clear()
        for ref in self.refs:self.attached.addItem(f'{ref.name} · {len(ref.text):,} chars'+(' · 일부' if ref.truncated else ''))
        if self.refs:self.attached.setCurrentRow(len(self.refs)-1)
        else:self.preview.clear()

    def show_reference(self,index):
        if not 0<=index<len(self.refs):return
        ref=self.refs[index]
        self.preview.setPlainText(f'{ref.name}\n{ref.source}\nRevision: {ref.revision or "local snapshot"}\nSHA256: {ref.sha256}\n'+('일부 내용만 포함되었습니다.\n' if ref.truncated else '')+ref.note+'\n\n'+ref.text)

    def remove_selected(self):
        row=self.attached.currentRow()
        if row>=0:self.refs.pop(row);self.refresh_references()

    def clear_references(self):self.refs=[];self.refresh_references()

    def disconnect(self):
        self.key.clear();self.parent().github_reference_token='';self.invalidate_connection()
        self.refs=[r for r in self.refs if not r.source.startswith('https://github.com/')];self.refresh_references()

    def done(self,result):
        if self.task:self.cancel()
        super().done(result)
