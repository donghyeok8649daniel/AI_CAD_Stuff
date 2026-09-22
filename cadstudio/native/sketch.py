"""Native QPainter sketch editor, analytic geometry, persistent constraints."""
from copy import deepcopy
import math
from PySide6.QtCore import Qt,Signal,QPointF,QTimer,QThreadPool,QSize
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QFont,QAction
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QToolBar,QToolButton,QMenu,QLabel,QComboBox,QCheckBox,QLineEdit,QTabWidget,QScrollArea,QListWidget,QListWidgetItem,QAbstractItemView,QGroupBox,QSplitter,QMessageBox,QInputDialog)
from . import geometry as G
from .widgets import number,label,button,icon,clear_layout,Worker
from ..models import Extrusion
from ..sketch_engine import sketch_preview,sketch_status,values
from ..kernel import KERNEL_LOCK

TOOLS={'select':('선택',0),'line':('직선 / 연속선',2),'rectangle':('2점 사각형',2),'center-rectangle':('중심 사각형',2),'rectangle-3':('3점 사각형',3),'circle':('중심·반지름 원',2),'circle-2':('2점 지름 원',2),'circle-3':('3점 원',3),'arc-3':('3점 원호',3),'arc-center':('중심 원호',3),'ellipse':('타원',3),'polygon':('외접원 다각형',2),'polygon-inscribed':('내접원 다각형',2),'slot':('중심점 슬롯',3),'center-slot':('중심 슬롯',3),'spline-fit':('맞춤점 스플라인',0),'spline-control':('제어점 스플라인',0),'point':('점',1),'text':('텍스트',1),'trim':('자르기',0),'extend':('연장',0),'split':('분할',0)}
KINDS={'line':'직선','circle':'원','arc':'원호','ellipse':'타원','spline':'스플라인','point':'점','text':'텍스트'}
CONSTRAINTS={'fixed':'고정','horizontal':'수평','vertical':'수직','coincident':'일치','distance':'거리','dx':'수평 거리','dy':'수직 거리','angle':'각도','radius':'반지름','diameter':'직경','parallel':'평행','perpendicular':'직각','equal':'동일','concentric':'동심','collinear':'동일 직선','tangent':'접선','midpoint':'중간점','symmetry':'대칭','point_on':'점-곡선','curvature':'곡률 연속'}
HINTS={'select':'클릭 선택 · Shift / Ctrl로 추가 선택 · 점 / 요소 드래그 · Delete 삭제','line':'시작점 → 끝점 → 다음 끝점. Enter / Esc로 연속선 종료.','rectangle':'대각선의 두 모서리를 클릭하세요.','center-rectangle':'중심 → 모서리','rectangle-3':'첫 모서리 → 둘째 모서리 → 폭','circle':'중심 → 원 위의 점','circle-2':'지름의 양 끝점','circle-3':'원 위의 세 점','arc-3':'시작점 → 지나는 점 → 끝점','arc-center':'중심 → 시작점 → 끝점','ellipse':'중심 → 첫 반축 끝점 → 둘째 반축 폭','slot':'첫 중심 → 둘째 중심 → 반폭','center-slot':'전체 중심 → 한쪽 끝의 중심 → 반폭','polygon':'중심 → 꼭짓점','polygon-inscribed':'중심 → 변의 중간점','spline-fit':'맞춤점을 클릭한 뒤 Enter로 완료','spline-control':'제어점을 클릭한 뒤 Enter로 완료','trim':'제거할 직선·원·원호 구간 클릭. 해당 요소의 구속은 해제됩니다.','extend':'경계까지 연장할 직선의 끝 쪽 클릭','split':'분할할 직선·원호의 중간 위치 클릭'}

def combo(items):
    w=QComboBox()
    for value,title in items:w.addItem(title,value)
    return w

class SketchCanvas(QWidget):
    def __init__(self,editor):
        super().__init__();self.editor=editor;self.setObjectName('sketchCanvas');self.setMinimumSize(400,300);self.setMouseTracking(True);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scale=5.;self.pan=QPointF();self.cursor=None;self.snap=None;self.drag=None;self.samples={};self.candidates=[]
    def screen(self,p):return QPointF(self.width()/2+self.pan.x()+p['x']*self.scale,self.height()/2+self.pan.y()-p['y']*self.scale)
    def world(self,pos,snap=True):
        p=G.pt((pos.x()-self.width()/2-self.pan.x())/self.scale,(self.height()/2+self.pan.y()-pos.y())/self.scale);self.snap=None
        if snap and self.editor.snapping.isChecked():
            choices=[(G.dist(p,s['p']),s) for s in self.candidates if G.dist(p,s['p'])<10/self.scale]
            if choices:self.snap=min(choices,key=lambda v:v[0])[1];return deepcopy(self.snap['p'])
        return G.pt(round(p['x'],4),round(p['y'],4))
    def rebuild(self):
        self.samples={};self.candidates=[dict(p=G.pt(0,0),type='원점',ids=[])]
        exact={e['id']:e['lines'] for e in (self.editor.preview or {}).get('entities',[])}
        for e in self.editor.g['entities']:
            for anchor,p in G.anchors(e):self.candidates.append(dict(p=p,type={'center':'중심점','mid':'중간점','quadrant':'사분점'}.get(anchor,'끝점'),ids=[e['id']],anchor=anchor))
            if e['id'] in exact:self.samples[e['id']]=[[G.pt(*p) for p in row] for row in exact[e['id']]]
            elif e['kind'] not in ('text','point'):
                try:self.samples[e['id']]=[[G.at(e,i/(1 if e['kind']=='line' else 80)) for i in range(2 if e['kind']=='line' else 81)]]
                except Exception:self.samples[e['id']]=[]
        es=self.editor.g['entities']
        for i,a in enumerate(es):
            for b in es[i+1:]:
                for p in G.intersections(a,b):self.candidates.append(dict(p=p,type='교점',ids=[a['id'],b['id']]))
        for p in (self.editor.preview or {}).get('intersections',[]):self.candidates.append(dict(p=G.pt(p['x'],p['y']),type='교점',ids=[p['a'],p['b']]))
        self.update()
    def hit(self,p):
        best=None;d=9/self.scale
        for e in self.editor.g['entities']:
            for a,q in G.anchors(e):
                next=G.dist(p,q)
                if next<d and a!='quadrant':best=(e,a);d=next
        if best:return best
        for e in self.editor.g['entities']:
            for points in self.samples.get(e['id'],[]):
                for a,b in zip(points,points[1:]):
                    v=G.sub(b,a);t=max(0,min(1,G.dot(G.sub(p,a),v)/max(G.dot(v,v),1e-20)));next=G.dist(p,G.add(a,G.mul(v,t)))
                    if next<d:best=(e,None);d=next
        return best
    def fit(self):
        ps=[p for rows in self.samples.values() for row in rows for p in row]
        ps += [G.pt(*p) for row in self.editor.context.get('face',{}).get('outline',[]) for p in row]
        ps += [G.pt(0,0)];xs=[p['x'] for p in ps];ys=[p['y'] for p in ps];a,b,c,d=min(xs),max(xs),min(ys),max(ys)
        self.scale=min(max(100,self.width()-110)/max(30,b-a),max(100,self.height()-110)/max(30,d-c));self.pan=QPointF(-(a+b)/2*self.scale,(c+d)/2*self.scale);self.update()
    def path(self,points):
        path=QPainterPath()
        for i,p in enumerate(points):
            if i:path.lineTo(self.screen(p))
            else:path.moveTo(self.screen(p))
        return path
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor('#f7fafb'));origin=self.screen(G.pt(0,0));unit=10**math.floor(math.log10(45/self.scale));step=unit*self.scale
        p.setPen(QPen(QColor('#e4eaed'),1))
        x=origin.x()%step
        while x<self.width():p.drawLine(QPointF(x,0),QPointF(x,self.height()));x+=step
        y=origin.y()%step
        while y<self.height():p.drawLine(QPointF(0,y),QPointF(self.width(),y));y+=step
        p.setPen(QPen(QColor('#cc8787'),1));p.drawLine(QPointF(0,origin.y()),QPointF(self.width(),origin.y()));p.setPen(QPen(QColor('#82a891'),1));p.drawLine(QPointF(origin.x(),0),QPointF(origin.x(),self.height()))
        for region in (self.editor.preview or {}).get('regions',[]):
            path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
            for row in region['outline']:
                sub=self.path([G.pt(*v) for v in row]);sub.closeSubpath();path.addPath(sub)
            selected=region['index'] in (self.editor.g['profiles'] or [0]);p.fillPath(path,QColor('#d5ebe5' if selected else '#edf1f2'))
        p.setPen(QPen(QColor('#b49cc3'),1.5,Qt.PenStyle.DashLine))
        for row in self.editor.context.get('face',{}).get('outline',[]):p.drawPath(self.path([G.pt(*v) for v in row]))
        fixed={c['a'] for c in self.editor.g['entity_constraints'] if c['kind']=='fixed' and c.get('a_point')=='all'}
        for e in self.editor.g['entities']:
            selected=e['id'] in self.editor.selected;color='#e39329' if selected else '#4d8b64' if e['id'] in fixed else '#3576b0';p.setPen(QPen(QColor(color),2.3 if selected else 1.6,Qt.PenStyle.DashLine if e['construction'] else Qt.PenStyle.SolidLine));p.setBrush(Qt.BrushStyle.NoBrush)
            if e['kind']=='text' and e['id'] not in self.samples:
                p.save();p.translate(self.screen(e['position']));p.rotate(-e['rotation']);f=QFont(e['font']);f.setPixelSize(max(8,min(300,int(e['size']*self.scale))));p.setFont(f);p.drawText(QPointF(),e['text']);p.restore()
            for row in self.samples.get(e['id'],[]):p.drawPath(self.path(row))
            for a,v in G.anchors(e):
                if a=='quadrant' or (a=='mid' and not selected):continue
                p.setBrush(QColor(color));p.drawEllipse(self.screen(v),3 if selected else 2,3 if selected else 2)
        pending=self.editor.pending
        if pending:
            p.setPen(QPen(QColor('#c28232'),1.5,Qt.PenStyle.DashLine));p.setBrush(Qt.BrushStyle.NoBrush)
            ghost=[]
            try:
                n=TOOLS[self.editor.tool][1];pts=pending+([self.cursor] if self.cursor else [])
                if n and len(pts)>=n:ghost=G.create(self.editor.tool,pts[:n],self.editor.options())
            except Exception:pass
            if ghost:
                for e in ghost:
                    if e['kind'] not in ('text','point'):p.drawPath(self.path([G.at(e,i/64) for i in range(65)]))
            else:p.drawPath(self.path(pending+([self.cursor] if self.cursor else [])))
            for v in pending:p.drawEllipse(self.screen(v),4,4)
        p.setFont(QFont('Malgun Gothic',9));p.setPen(QColor('#748a93'));p.drawText(origin+QPointF(8,17),'원점 (0, 0)')
        index={e['id']:e for e in self.editor.g['entities']}
        for con in self.editor.g['entity_constraints']:
            e=index.get(con['a']);kind=con['kind']
            if not e:continue
            if kind=='fixed' and con.get('x',0)==0 and con.get('y',0)==0 and con.get('a_point')!='all':p.setPen(QColor('#43805c'));p.drawText(origin+QPointF(8,32),'원점 고정')
            if kind in ('diameter','radius','distance','dx','dy','angle'):
                pos=self.screen(G.at(e,.125 if 'center' in e else .5));p.setPen(QColor('#325f75'));p.drawText(pos+QPointF(10,-12),{'diameter':'Ø ','radius':'R ','angle':'∠ ','dx':'X ','dy':'Y '}.get(kind,'')+f"{con['value']:g}"+('°' if kind=='angle' else ' mm'))
        if self.snap:
            v=self.screen(self.snap['p']);p.setPen(QPen(QColor('#9e4cba'),2));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRect(v.x()-5,v.y()-5,10,10);p.drawText(v+QPointF(11,-10),self.snap['type'])
        p.setPen(QColor('#67818d'));p.drawText(QPointF(14,self.height()-14),f"mm · 격자 {unit:g} · 요소 {len(self.editor.g['entities'])}"+(f"   X {self.cursor['x']:.3f}   Y {self.cursor['y']:.3f}" if self.cursor else ''));p.end()
    def mousePressEvent(self,event):
        self.setFocus();pos=event.position()
        if event.button() in (Qt.MouseButton.MiddleButton,Qt.MouseButton.RightButton):self.drag=dict(pan=True,start=pos,old=QPointF(self.pan));return
        if event.button()!=Qt.MouseButton.LeftButton:return
        p=self.world(pos,self.editor.tool!='select')
        if self.editor.tool!='select':self.editor.input_point(p);return
        hit=self.hit(p);multi=event.modifiers()&(Qt.KeyboardModifier.ShiftModifier|Qt.KeyboardModifier.ControlModifier)
        if not multi:self.editor.selected=set()
        if hit:
            e,anchor=hit
            if multi and e['id'] in self.editor.selected:self.editor.selected.remove(e['id'])
            else:self.editor.selected.add(e['id'])
            self.drag=dict(pan=False,id=e['id'],anchor=anchor,start=p,before=deepcopy(self.editor.g),moved=False)
        self.editor.refresh_selection();self.update()
    def mouseMoveEvent(self,event):
        p=self.world(event.position(),not self.drag and self.editor.tool!='select');self.cursor=p
        if self.drag:
            d=self.drag
            if d['pan']:self.pan=d['old']+event.position()-d['start']
            elif G.dist(p,d['start'])*self.scale>3:
                d['moved']=True;e=next(e for e in self.editor.g['entities'] if e['id']==d['id']);old=next(e for e in d['before']['entities'] if e['id']==d['id']);a=d['anchor']
                if a in e and isinstance(e[a],dict):e[a]=p
                elif e['kind']=='spline' and a in ('start','end'):e['points'][0 if a=='start' else -1]=p
                else:e.update(G.transform(old,dx=p['x']-d['start']['x'],dy=p['y']-d['start']['y']))
                self.editor.preview=None;self.rebuild()
        self.update()
    def mouseReleaseEvent(self,event):
        if self.drag and not self.drag['pan'] and self.drag['moved']:self.editor.changed('요소 / 점 드래그',self.drag['before'])
        self.drag=None
    def wheelEvent(self,event):
        pos=event.position();p=self.world(pos,False);self.scale=max(.08,min(1000,self.scale*1.18**(event.angleDelta().y()/120)));self.pan=QPointF(pos.x()-self.width()/2-p['x']*self.scale,pos.y()-self.height()/2+p['y']*self.scale);self.update()
    def keyPressEvent(self,event):
        key=event.key();ctrl=bool(event.modifiers()&Qt.KeyboardModifier.ControlModifier)
        if key==Qt.Key.Key_Escape:self.editor.set_tool('select')
        elif key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):self.editor.finish_drawing()
        elif key==Qt.Key.Key_Delete:self.editor.delete_selected()
        elif ctrl and key==Qt.Key.Key_Z:self.editor.undo()
        elif ctrl and key==Qt.Key.Key_Y:self.editor.redo()
        elif key==Qt.Key.Key_F:self.fit()
        elif key==Qt.Key.Key_L:self.editor.set_tool('line')
        elif key==Qt.Key.Key_C:self.editor.set_tool('circle')
        elif key==Qt.Key.Key_R:self.editor.set_tool('rectangle')
        elif key==Qt.Key.Key_D:self.editor.tabs.setCurrentIndex(1)
        else:super().keyPressEvent(event)

class SketchEditor(QWidget):
    apply_requested=Signal(object,object,str)
    cancelled=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.g={};self.context={};self.preview=None;self.selected=set();self.pending=[];self.tool='select';self.revision=0;self.solving=False;self.worker=None;self.undo_stack=[];self.redo_stack=[];self.actions=[]
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0);self.toolbar=QToolBar();self.toolbar.setIconSize(QSize(22,22));self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);outer.addWidget(self.toolbar)
        self.tool_actions={}
        self.add_tool('select','origin');self.add_tool('line','line')
        for name,key,items in [('사각형','rectangle',['rectangle','center-rectangle','rectangle-3']),('원','circle',['circle','circle-2','circle-3','ellipse']),('원호 / 슬롯','arc',['arc-3','arc-center','slot','center-slot']),('스플라인','spline',['spline-fit','spline-control']),('다각형 / 문자','sketch',['polygon','polygon-inscribed','point','text']),('수정','trim',['trim','extend','split'])]:
            b=QToolButton();b.setText(name);b.setIcon(icon(key));b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);menu=QMenu(b)
            for tool in items:menu.addAction(TOOLS[tool][0],lambda t=tool:self.set_tool(t))
            b.setMenu(menu);self.toolbar.addWidget(b)
        self.toolbar.addSeparator();self.toolbar.addAction(icon('undo'),'취소',self.undo);self.toolbar.addAction(icon('redo'),'다시',self.redo);self.toolbar.addAction(icon('fit'),'맞춤',lambda:self.canvas.fit())
        self.title=label('스케치');self.title.setStyleSheet('padding:8px 14px;background:#e8f1ee;color:#286759;font-weight:600;');outer.addWidget(self.title)
        splitter=QSplitter();outer.addWidget(splitter,1);left=QWidget();vl=QVBoxLayout(left);vl.setContentsMargins(0,0,0,0);self.hint=label('');self.hint.setStyleSheet('padding:8px 12px;color:#566b75;');vl.addWidget(self.hint);self.canvas=SketchCanvas(self);vl.addWidget(self.canvas,1)
        row=QHBoxLayout();row.setContentsMargins(8,5,8,5);self.x=number(0,-1000,1000);self.y=number(0,-1000,1000);row.addWidget(QLabel('X'));row.addWidget(self.x);row.addWidget(QLabel('Y'));row.addWidget(self.y);row.addWidget(button('좌표로 점 입력',lambda:self.input_point(G.pt(self.x.value(),self.y.value()))));row.addWidget(button('그리기 완료 ↵',self.finish_drawing));vl.addLayout(row);splitter.addWidget(left)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(300);self.tabs.setMaximumWidth(390);splitter.addWidget(self.tabs);splitter.setStretchFactor(0,1);splitter.setSizes([900,330])
        props=self.page('스케치');self.snapping=QCheckBox('끝점·교점·중심·원점 스냅');self.snapping.setChecked(True);self.auto=QCheckBox('자동 구속');self.auto.setChecked(True);self.construction=QCheckBox('보조선으로 작성');props.addWidget(self.snapping);props.addWidget(self.auto);props.addWidget(self.construction)
        form=QFormLayout();self.count=number(6,3,32,decimals=0);self.text=QLineEdit('CAD');self.size=number(10,.01,2000);self.closed=QCheckBox('닫힌 스플라인');self.clockwise=QCheckBox('시계 방향 원호');form.addRow('다각형 변 수',self.count);form.addRow('문자',self.text);form.addRow('문자 높이',self.size);props.addLayout(form);props.addWidget(self.closed);props.addWidget(self.clockwise)
        self.entity_list=QListWidget();self.entity_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.entity_list.setMaximumHeight(165);self.entity_list.itemSelectionChanged.connect(self.list_selected);props.addWidget(label('스케치 요소'));props.addWidget(self.entity_list)
        self.property_box=QWidget();self.property_form=QFormLayout(self.property_box);props.addWidget(self.property_box);props.addWidget(button('선택 요소 속성 적용',self.apply_properties));props.addWidget(button('선택 요소 삭제',self.delete_selected));props.addWidget(button('선택 면의 모서리 투영',self.project_face));props.addStretch()
        cons=self.page('구속');f=QFormLayout();self.kind=combo(CONSTRAINTS.items());self.ca=QComboBox();self.cb=QComboBox();self.cc=QComboBox();points=[('start','시작점 / 점'),('end','끝점'),('center','중심'),('mid','중간점'),('all','전체')];self.ap=combo(points);self.bp=combo(points);self.value=number(20,-4000,4000);self.mode=combo([('external','외접'),('internal','내접')])
        for name,w in [('종류',self.kind),('요소 A',self.ca),('점 A',self.ap),('요소 B',self.cb),('점 B',self.bp),('대칭 기준선 C',self.cc),('치수 mm / 각도 °',self.value),('원 접선',self.mode)]:f.addRow(name,w)
        cons.addLayout(f);cons.addWidget(button('구속 추가',self.add_constraint,True));cons.addWidget(button('점 A를 원점에 고정',self.origin_constraint));cons.addWidget(label('선 하나의 수평·수직·각도는 B를 비웁니다. 전체 고정은 점 A를 ‘전체’로 선택하세요.',True));self.constraint_list=QListWidget();self.constraint_list.setMinimumHeight(150);self.constraint_list.itemDoubleClicked.connect(self.edit_dimension);cons.addWidget(self.constraint_list);cons.addWidget(button('선택 치수 값 편집',self.edit_dimension));cons.addWidget(button('선택 구속 삭제',self.delete_constraint));cons.addWidget(label('해가 없는 구속은 오류로 표시됩니다. 취소하거나 해당 구속을 지운 뒤 다시 해석하세요.',True));cons.addStretch()
        modify=self.page('변형');f=QFormLayout();self.mod=combo([('move','이동'),('copy','복사'),('rotate','회전'),('scale','배율'),('mirror-x','X축 대칭 복사'),('mirror-y','Y축 대칭 복사'),('mirror-line','마지막 선택 직선 대칭'),('offset','간격띄우기'),('fillet','필렛'),('chamfer','모따기'),('rect-pattern','직사각형 패턴'),('circular-pattern','원형 패턴')]);self.dx=number(20);self.dy=number(0);self.degrees=number(45,-360,360);self.factor=number(1,.01,100);self.amount=number(5,.01,2000);self.nx=number(3,2,32,decimals=0);self.ny=number(1,1,32,decimals=0)
        for name,w in [('작업',self.mod),('X 이동 / 간격',self.dx),('Y 이동 / 간격',self.dy),('각도 / 패턴 각도',self.degrees),('배율',self.factor),('반지름 / 거리',self.amount),('개수 X / 원형',self.nx),('개수 Y',self.ny)]:f.addRow(name,w)
        modify.addLayout(f);modify.addWidget(button('선택 요소에 적용',self.modify,True));modify.addWidget(label('회전·배율·원형 패턴은 스케치 원점 기준입니다. 변형된 요소에 연결된 기존 구속은 해제되고 작업 기록에 남습니다.',True));modify.addStretch()
        finish=QHBoxLayout();finish.setContentsMargins(12,10,12,10);self.status=label('');self.status.setMinimumWidth(120);finish.addWidget(self.status,1);self.regions=QComboBox();self.regions.setMinimumWidth(170);self.regions.currentIndexChanged.connect(self.choose_region);finish.addWidget(self.regions);self.operation=combo([('add','돌출 · 더하기'),('cut','안쪽으로 파내기')]);finish.addWidget(self.operation);self.depth=number(8,.01,2000,' mm');finish.addWidget(self.depth);finish.addWidget(button('취소',self.cancelled.emit));self.apply_button=button('스케치 완료 · 돌출',self.finish,True);finish.addWidget(self.apply_button);outer.addLayout(finish)
        self.solve_timer=QTimer(self);self.solve_timer.setSingleShot(True);self.solve_timer.setInterval(180);self.solve_timer.timeout.connect(self.solve)
    def page(self,title):
        scroll=QScrollArea();scroll.setWidgetResizable(True);w=QWidget();layout=QVBoxLayout(w);layout.setContentsMargins(12,12,12,12);scroll.setWidget(w);self.tabs.addTab(scroll,title);return layout
    def add_tool(self,tool,key):
        a=self.toolbar.addAction(icon(key),TOOLS[tool][0],lambda:self.set_tool(tool));a.setCheckable(True);self.tool_actions[tool]=a
    def start(self,g=None,context=None):
        self.context=deepcopy(context or {});self.g=G.to_entities(g) if g else Extrusion(sketch_mode='entities',entities=[]).model_dump();self.preview=None;self.selected=set();self.pending=[];self.undo_stack=[];self.redo_stack=[];self.actions=[];self.revision+=1
        self.title.setText(self.context.get('title','새 스케치 · XY 평면'));self.depth.setValue(self.g['thickness']);self.operation.setCurrentIndex(1 if self.context.get('operation')=='cut' else 0);self.operation.setEnabled(bool(self.context.get('face') or self.context.get('feature_id')));self.refresh();self.set_tool('select');QTimer.singleShot(0,self.canvas.fit);self.solve_timer.start()
    def set_tool(self,tool):
        self.tool=tool;self.pending=[];self.canvas.snap=None
        for key,a in self.tool_actions.items():a.setChecked(key==tool)
        self.hint.setText(TOOLS[tool][0]+'  ·  '+HINTS.get(tool,'위치를 클릭하거나 아래에 X·Y 좌표를 입력하세요.'));self.canvas.setCursor(Qt.CursorShape.ArrowCursor if tool=='select' else Qt.CursorShape.CrossCursor);self.canvas.setFocus();self.canvas.update()
    def options(self):return dict(count=self.count.value(),text=self.text.text()[:32] or 'CAD',size=self.size.value(),font='Malgun Gothic',closed=self.closed.isChecked(),clockwise=self.clockwise.isChecked())
    def error(self,message):self.status.setText(message[:320]);self.status.setStyleSheet('color:#b54e3d;');self.status.setToolTip(message)
    def mutate(self,name,fn):
        before=deepcopy(self.g)
        try:
            fn()
            if len(self.g['entities'])>128 or len(self.g['entity_constraints'])>160:raise ValueError('스케치 요소 128개, 구속 160개까지 지원합니다. 스케치를 나누세요.')
            self.changed(name,before)
        except Exception as exc:self.g=before;self.error(str(exc));self.refresh()
    def changed(self,name,before):
        if before==self.g:return
        self.undo_stack.append((before,deepcopy(self.actions)));self.redo_stack=[];self.actions.append(dict(tool=name,before=before,after=deepcopy(self.g)));self.g['profiles']=[];self.preview=None;self.revision+=1;self.refresh();self.solve_timer.start()
    def undo(self):
        if self.pending:self.pending=[];self.canvas.update();return
        if not self.undo_stack:return
        self.redo_stack.append((deepcopy(self.g),deepcopy(self.actions)));self.g,self.actions=self.undo_stack.pop();self.preview=None;self.revision+=1;self.refresh();self.solve_timer.start()
    def redo(self):
        if not self.redo_stack:return
        self.undo_stack.append((deepcopy(self.g),deepcopy(self.actions)));self.g,self.actions=self.redo_stack.pop();self.preview=None;self.revision+=1;self.refresh();self.solve_timer.start()
    def input_point(self,p):
        if self.tool=='select':self.error('직선·원 등 그리기 도구를 먼저 선택하세요.');return
        if self.tool in ('trim','extend','split'):
            hit=self.canvas.hit(p)
            if not hit:self.error('수정할 요소를 클릭하세요.');return
            e=hit[0]
            def edit():self.replace([e['id']],G.split(e,p) if self.tool=='split' else getattr(G,self.tool)(e,self.g['entities'],p))
            self.mutate(TOOLS[self.tool][0],edit);return
        self.pending.append(deepcopy(p));n=TOOLS[self.tool][1]
        if n and len(self.pending)>=n:
            pts=deepcopy(self.pending);self.mutate(TOOLS[self.tool][0],lambda:self.add_entities(G.create(self.tool,pts,self.options()),True));self.pending=[pts[-1]] if self.tool=='line' else []
        self.canvas.update()
    def finish_drawing(self):
        if self.tool.startswith('spline-'):
            if len(self.pending)<3:self.error('스플라인에는 점이 3개 이상 필요합니다.');return
            pts=deepcopy(self.pending);self.mutate(TOOLS[self.tool][0],lambda:self.add_entities(G.create(self.tool,pts,self.options()),True))
        self.set_tool('select')
    def add_entities(self,es,connect=False):
        before=deepcopy(self.g['entities']);candidates=deepcopy(self.canvas.candidates)
        for e in es:e['construction']=self.construction.isChecked()
        if connect and self.auto.isChecked():
            for i,e in enumerate(es):
                for anchor,p in G.anchors(e):
                    if anchor in ('mid','quadrant'):continue
                    if G.dist(p,G.pt(0,0))<1e-7:self.g['entity_constraints'].append(dict(id=G.uid(),kind='fixed',a=e['id'],a_point=anchor,x=0,y=0))
                    linked=False
                    for other in before+es[:i]:
                        for oa,q in G.anchors(other):
                            if oa in ('mid','quadrant'):continue
                            if G.dist(p,q)<1e-7:self.g['entity_constraints'].append(dict(id=G.uid(),kind='coincident',a=e['id'],a_point=anchor,b=other['id'],b_point=oa));linked=True;break
                        if linked:break
                    if not linked:
                        for snap in sorted(candidates,key=lambda s:s['type']!='교점'):
                            if G.dist(p,snap['p'])>1e-7:continue
                            if snap['type']=='교점':
                                for id in snap['ids']:self.g['entity_constraints'].append(dict(id=G.uid(),kind='point_on',a=e['id'],a_point=anchor,b=id))
                                break
                            if snap['type']=='중간점':self.g['entity_constraints'].append(dict(id=G.uid(),kind='midpoint',a=e['id'],a_point=anchor,b=snap['ids'][0]));break
                if e['kind']=='line':
                    if abs(e['start']['y']-e['end']['y'])<1e-7:self.g['entity_constraints'].append(dict(id=G.uid(),kind='horizontal',a=e['id']))
                    elif abs(e['start']['x']-e['end']['x'])<1e-7:self.g['entity_constraints'].append(dict(id=G.uid(),kind='vertical',a=e['id']))
        self.g['entities'].extend(es);self.selected={e['id'] for e in es}
    def replace(self,ids,es):
        self.g['entities']=[e for e in self.g['entities'] if e['id'] not in ids]+es;self.g['entity_constraints']=[c for c in self.g['entity_constraints'] if not any(c.get(k) in ids for k in ('a','b','c'))];self.selected={e['id'] for e in es}
    def chosen(self):return [e for e in self.g['entities'] if e['id'] in self.selected]
    def delete_selected(self):
        if self.selected:self.mutate('요소 삭제',lambda:self.replace(self.selected,[]))
    def refresh(self):
        self.entity_list.blockSignals(True);self.entity_list.clear()
        for i,e in enumerate(self.g['entities']):
            item=QListWidgetItem(f"{i+1}. {KINDS[e['kind']]}"+(' · 보조' if e['construction'] else ''));item.setData(Qt.ItemDataRole.UserRole,e['id']);self.entity_list.addItem(item);item.setSelected(e['id'] in self.selected)
        self.entity_list.blockSignals(False)
        for c in (self.ca,self.cb,self.cc):
            previous=c.currentData();c.clear();c.addItem('선택 안 함','')
            for i,e in enumerate(self.g['entities']):c.addItem(f"{i+1}. {KINDS[e['kind']]}",e['id'])
            c.setCurrentIndex(max(0,c.findData(previous)))
        self.constraint_list.clear();index={e['id']:i+1 for i,e in enumerate(self.g['entities'])}
        for c in self.g['entity_constraints']:
            item=QListWidgetItem(f"{CONSTRAINTS[c['kind']]} · {index.get(c['a'],'?')}"+(f" ↔ {index.get(c.get('b'),'?')}" if c.get('b') else '')+(f" = {c['value']:g}" if c['kind'] in ('distance','diameter','radius','dx','dy','angle') else ''));item.setData(Qt.ItemDataRole.UserRole,c['id']);self.constraint_list.addItem(item)
        self.refresh_selection();self.canvas.rebuild()
    def list_selected(self):
        self.selected={i.data(Qt.ItemDataRole.UserRole) for i in self.entity_list.selectedItems()};self.refresh_selection();self.canvas.update()
    def refresh_selection(self):
        self.entity_list.blockSignals(True)
        for i in range(self.entity_list.count()):item=self.entity_list.item(i);item.setSelected(item.data(Qt.ItemDataRole.UserRole) in self.selected)
        self.entity_list.blockSignals(False);chosen=self.chosen()
        if chosen:
            self.ca.setCurrentIndex(self.ca.findData(chosen[0]['id']));self.ap.setCurrentIndex(self.ap.findData('center' if 'center' in chosen[0] else 'start'))
            self.cb.setCurrentIndex(self.cb.findData(chosen[1]['id']) if len(chosen)>1 else 0)
            if len(chosen)>2:self.cc.setCurrentIndex(self.cc.findData(chosen[2]['id']))
        clear_layout(self.property_form);self.property_inputs=[]
        if len(chosen)!=1:self.property_form.addRow(label(f'{len(chosen)}개 선택 · 속성 편집은 하나를 선택하세요.',True));return
        e=chosen[0]
        names={'construction':'보조선','closed':'닫힌 곡선','start':'시작','end':'끝','center':'중심','position':'위치','points':'점','radius':'반지름','radius_x':'X 반축','radius_y':'Y 반축','rotation':'회전 각도','start_angle':'시작 각도','sweep':'원호 각도','size':'문자 높이','text':'문자','x':'X','y':'Y'}
        def field_title(path):return ' '.join(str(k+1) if isinstance(k,int) else names.get(k,k) for k in path)
        def fields(value,path=()):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k in ('id','kind','style','font'):continue
                    fields(v,(*path,k))
            elif isinstance(value,list):
                for i,v in enumerate(value):fields(v,(*path,i))
            elif isinstance(value,bool):
                w=QCheckBox();w.setChecked(value);self.property_form.addRow(field_title(path),w);self.property_inputs.append((path,w,'bool'))
            elif isinstance(value,(int,float)):
                w=number(value,-1000 if path[-1] in ('x','y') else -360 if path[-1] in ('rotation','start_angle','sweep') else .01,1000 if path[-1] in ('x','y') else 359.99 if path[-1]=='sweep' else 360 if path[-1] in ('rotation','start_angle') else 2000);self.property_form.addRow(field_title(path),w);self.property_inputs.append((path,w,'number'))
            elif isinstance(value,str):
                w=QLineEdit(value);self.property_form.addRow(field_title(path),w);self.property_inputs.append((path,w,'text'))
        fields(e)
    def apply_properties(self):
        if len(self.chosen())!=1:return
        def edit():
            e=self.chosen()[0]
            for path,w,kind in self.property_inputs:
                target=e
                for key in path[:-1]:target=target[key]
                target[path[-1]]=w.isChecked() if kind=='bool' else w.value() if kind=='number' else w.text()
        self.mutate('요소 속성 편집',edit)
    def add_constraint(self):
        def edit():
            a=self.ca.currentData()
            if not a:raise ValueError('요소 A를 선택하세요.')
            c=dict(id=G.uid(),kind=self.kind.currentData(),a=a,b=self.cb.currentData(),c=self.cc.currentData(),a_point=self.ap.currentData(),b_point=self.bp.currentData(),value=self.value.value(),mode=self.mode.currentData())
            e=next(e for e in self.g['entities'] if e['id']==a)
            if c['kind']=='fixed':
                if c['a_point']=='all':c['reference']=values(e)
                else:
                    from ..sketch_engine import point
                    p=point(e,c['a_point']);c.update(x=float(p[0]),y=float(p[1]))
            self.g['entity_constraints'].append(c)
        self.mutate('구속 추가 · '+self.kind.currentText(),edit)
    def origin_constraint(self):
        def edit():
            if not self.ca.currentData():raise ValueError('요소 A를 선택하세요.')
            self.g['entity_constraints'].append(dict(id=G.uid(),kind='fixed',a=self.ca.currentData(),a_point=self.ap.currentData() if self.ap.currentData()!='all' else 'center',x=0,y=0))
        self.mutate('원점 고정',edit)
    def delete_constraint(self):
        item=self.constraint_list.currentItem()
        if item:self.mutate('구속 삭제',lambda:self.g.update(entity_constraints=[c for c in self.g['entity_constraints'] if c['id']!=item.data(Qt.ItemDataRole.UserRole)]))
    def edit_dimension(self,item=None):
        if not isinstance(item,QListWidgetItem):item=self.constraint_list.currentItem()
        if not item:return
        c=next(c for c in self.g['entity_constraints'] if c['id']==item.data(Qt.ItemDataRole.UserRole))
        if c['kind'] not in ('distance','dx','dy','angle','radius','diameter'):self.error('이 구속은 수치가 없습니다. 삭제 후 다른 관계로 추가하세요.');return
        value,accepted=QInputDialog.getDouble(self,'치수 편집',CONSTRAINTS[c['kind']]+' · mm / °',c.get('value',0),-4000,4000,5)
        if accepted:self.mutate('치수 구속 편집 · '+CONSTRAINTS[c['kind']],lambda:c.update(value=value))
    def project_face(self):
        def edit():
            es=deepcopy(self.context.get('face',{}).get('projected_entities',[]))
            if not es:raise ValueError('선택 면의 직선·원·원호 모서리가 없습니다.')
            for e in es:e['id']=G.uid();e['construction']=True
            self.g['entities'].extend(es)
            for e in es:self.g['entity_constraints'].append(dict(id=G.uid(),kind='fixed',a=e['id'],a_point='all',reference=values(e)))
            self.selected={e['id'] for e in es}
        self.mutate('면 모서리 투영 · 보조선 고정',edit)
    def modify(self):
        def edit():
            es=self.chosen();kind=self.mod.currentData()
            if not es:raise ValueError('변형할 요소를 선택하세요.')
            if kind in ('fillet','chamfer'):
                if len(es)!=2:raise ValueError('두 직선을 선택하세요.')
                self.replace(self.selected,G.corner(*es,self.amount.value(),kind=='fillet'));return
            if kind=='offset':out=G.offset(es,self.amount.value())
            elif kind in ('rect-pattern','circular-pattern'):
                count=int(self.nx.value());ny=int(self.ny.value()) if kind=='rect-pattern' else 1
                if len(self.g['entities'])+len(es)*(count*ny-1)>128:raise ValueError('패턴 결과가 요소 128개를 넘습니다.')
                out=[G.transform(e,dx=self.dx.value()*x,dy=self.dy.value()*y) if kind=='rect-pattern' else G.transform(e,degrees=self.degrees.value()*x/count) for x in range(count) for y in range(ny) if x or y for e in es]
            else:
                options={}
                if kind in ('move','copy'):options=dict(dx=self.dx.value(),dy=self.dy.value())
                elif kind=='rotate':options=dict(degrees=self.degrees.value())
                elif kind=='scale':options=dict(scale=self.factor.value())
                elif kind.startswith('mirror'):
                    axis=G.line(G.pt(0,0),G.pt(1,0) if kind=='mirror-x' else G.pt(0,1))
                    if kind=='mirror-line':
                        if len(es)<2 or es[-1]['kind']!='line':raise ValueError('마지막 선택 요소가 대칭 기준 직선이어야 합니다.')
                        axis=es[-1];es=es[:-1]
                    options=dict(axis=axis)
                out=[G.transform(e,**options) for e in es]
            if kind in ('move','rotate','scale'):self.replace(self.selected,out)
            else:
                for e in out:e['id']=G.uid()
                self.g['entities'].extend(out);self.selected={e['id'] for e in out}
        self.mutate('변형 · '+self.mod.currentText(),edit)
    def solve(self):
        if self.solving:self.solve_timer.start();return
        revision=self.revision;raw=deepcopy(self.g);self.solving=True;self.status.setText('구속 해석 · 닫힌 영역 계산 중…');self.status.setStyleSheet('color:#557480;')
        def job():
            with KERNEL_LOCK:
                g=Extrusion.model_validate(raw);status=sketch_status(g);preview=sketch_preview(g)
                return g.model_dump(),status,preview
        worker=Worker(job);self.worker=worker
        def done(result):
            self.solving=False
            if revision!=self.revision:self.solve_timer.start();return
            self.g,status,self.preview=result;self.status.setStyleSheet('color:#286d5e;');self.status.setText(f"{'완전 구속' if status['dof']==0 else '자유도 '+str(status['dof'])} · 영역 {len(self.preview['regions'])}개");self.refresh();self.regions.blockSignals(True);self.regions.clear()
            for r in self.preview['regions']:self.regions.addItem(f"영역 {r['index']+1} · {r['area']:.2f} mm²",r['index'])
            self.regions.addItem('모든 닫힌 영역',-1);self.regions.setCurrentIndex(0 if not self.g['profiles'] else self.regions.findData(self.g['profiles'][0]) if len(self.g['profiles'])==1 else self.regions.count()-1);self.regions.blockSignals(False)
        def failed(message):
            self.solving=False
            if revision!=self.revision:self.solve_timer.start();return
            self.preview=None;self.error(message)
        worker.signals.done.connect(done);worker.signals.failed.connect(failed);QThreadPool.globalInstance().start(worker)
    def choose_region(self):
        if not self.preview:return
        value=self.regions.currentData();self.g['profiles']=[r['index'] for r in self.preview['regions']] if value==-1 else [value] if value is not None else [];self.canvas.update()
    def finish(self):
        if self.pending:
            self.finish_drawing()
            if self.pending:return
        self.g['thickness']=self.depth.value();context=deepcopy(self.context);context['tool_actions']=deepcopy(self.actions);self.apply_requested.emit(deepcopy(self.g),context,self.operation.currentData())
