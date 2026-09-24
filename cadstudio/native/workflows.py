"""Native, validated previews for specimens, robot dimensions and real joints."""
from copy import deepcopy
import math
from PySide6.QtCore import Qt, QTimer, QThreadPool, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,QSplitter,QLineEdit,QComboBox,QCheckBox,QSlider,QLabel)
from .widgets import Worker,number,label,button,clear_layout
from .viewport import CADViewport
from .geometry import uid
from ..catalog import preset,part_default,FIELDS,TITLES
from ..models import Design
from ..kernel import KERNEL_LOCK,preview
from ..constraints import anchors,transform_matrix


def choice(items):
    c=QComboBox()
    for value,title in items:c.addItem(title,value)
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);c.setMinimumContentsLength(10)
    return c


class PreviewDialog(QDialog):
    """Only the latest successfully checked candidate can be committed."""
    def __init__(self,parent,title,instructions):
        super().__init__(parent);self.setWindowTitle(title);self.resize(1100,760);self.setMinimumSize(800,560)
        self.alive=True;self.running=False;self.revision=0;self.checked=None;self.result=None;self.fit_next=True
        v=QVBoxLayout(self);v.setContentsMargins(12,12,12,12);heading=label(title);heading.setStyleSheet('font-size:18px;font-weight:600;color:#bcf2e7;');v.addWidget(heading);v.addWidget(label(instructions,True))
        split=QSplitter();v.addWidget(split,1);self.viewport=CADViewport();split.addWidget(self.viewport)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(285);scroll.setMaximumWidth(360);controls=QWidget();self.controls=QVBoxLayout(controls);self.controls.setContentsMargins(14,12,14,12);scroll.setWidget(controls);split.addWidget(scroll);split.setSizes([750,330])
        self.status=label('치수를 입력하면 실제 CAD 형상을 미리 봅니다.');v.addWidget(self.status);row=QHBoxLayout();row.addStretch();row.addWidget(button('취소',self.reject));self.apply_button=button('설계에 적용',self.accept,True);self.apply_button.setEnabled(False);row.addWidget(self.apply_button);v.addLayout(row)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(220);self.timer.timeout.connect(self.calculate)
    def schedule(self,*args):
        self.revision+=1;self.checked=None;self.apply_button.setEnabled(False);self.timer.start()
    def calculate(self):
        if not self.alive or self.running:return
        revision=self.revision
        try:raw=self.candidate()
        except Exception as exc:self.failed(str(exc));return
        self.running=True;self.status.setText('형상 · 조립 구속 · 간섭 확인 중…');worker=Worker(lambda:self.compute(raw));self.worker=worker
        def done(result):
            self.running=False
            if not self.alive:return
            if revision!=self.revision:self.timer.start();return
            self.checked,self.result=result;self.viewport.load(self.result,self.fit_next);self.fit_next=False;self.apply_button.setEnabled(True);self.present()
        def failed(message):
            self.running=False
            if not self.alive:return
            if revision!=self.revision:self.timer.start();return
            self.failed(message)
        worker.signals.done.connect(done);worker.signals.failed.connect(failed);QThreadPool.globalInstance().start(worker)
    @staticmethod
    def compute(raw):
        with KERNEL_LOCK:
            d=Design.model_validate(raw);return d,preview(d)
    def failed(self,message):
        self.checked=None;self.apply_button.setEnabled(False);self.status.setText(message[:450]);self.status.setStyleSheet('color:#f4a18c;')
    def present(self):
        self.status.setStyleSheet('color:#8dd7c0;');s=self.result['stats'];self.status.setText(f"형상 유효 · {s['parts']}개 부품 · 체적 {s['volume']:,.2f} mm³ · 간섭 {len(s['collisions'])}건")
    def accept(self):
        if self.checked is not None:super().accept()
    def done(self,result):
        self.alive=False;self.timer.stop();self.viewport.shutdown();super().done(result)


class SpecimenDiagram(QWidget):
    def __init__(self):super().__init__();self.g=None;self.setFixedHeight(140)
    def paintEvent(self,event):
        if not self.g:return
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor('#13232e'));g=self.g;w=self.width();cx=w/2;cy=68
        p.setPen(QPen(QColor('#64d7c0'),1.5));p.setBrush(QColor('#24464d'))
        if g['kind']=='wafer':
            p.drawEllipse(QPointF(cx,cy),42,42);p.setPen(QColor('#c0d9e7'));p.drawText(12,20,f"Ø {g['diameter']:g} mm");p.drawText(12,127,f"두께 {g['thickness']:g} mm");p.end();return
        length=g['length'];scale=(w-30)/max(length,1);big=g.get('grip_diameter',g.get('grip_width'))/2;small=g.get('gauge_diameter',g.get('gauge_width'))/2;ratio=min(scale,32/max(big,1));a=-g['gauge_length']/2-g['transition_length'];b=-g['gauge_length']/2
        def xy(x,y):return QPointF(cx+x*scale,cy-y*ratio)
        path=QPainterPath();path.moveTo(xy(-length/2,big));path.lineTo(xy(a,big));path.cubicTo(xy(a+g['transition_length']/3,big),xy(b-g['transition_length']/3,small),xy(b,small));path.lineTo(xy(-b,small));path.cubicTo(xy(-b+g['transition_length']/3,small),xy(-a-g['transition_length']/3,big),xy(-a,big));path.lineTo(xy(length/2,big));path.lineTo(xy(length/2,-big));path.lineTo(xy(-a,-big));path.cubicTo(xy(-a-g['transition_length']/3,-big),xy(-b+g['transition_length']/3,-small),xy(-b,-small));path.lineTo(xy(b,-small));path.cubicTo(xy(b-g['transition_length']/3,-small),xy(a+g['transition_length']/3,-big),xy(a,-big));path.lineTo(xy(-length/2,-big));path.closeSubpath();p.drawPath(path)
        p.setPen(QColor('#c0d9e7'));p.drawText(10,19,f"전체 {length:g} mm");p.drawText(10,128,f"평행부 {g['gauge_length']:g} mm  ·  {'Ø' if g['kind']=='round_specimen' else '폭'} {small*2:g} mm");p.end()


class SpecimenDialog(PreviewDialog):
    def __init__(self,parent,design=None,part_id=None):
        super().__init__(parent,'시편 설계','치수 입력 → 실제 형상 확인 → 적용. 전이부와 그립 길이도 함께 검사합니다.')
        self.base=deepcopy(design) if design else dict(name='시편 설계',parts=[],mates=[]);self.original=next((p for p in self.base['parts'] if p['id']==part_id),None);self.part_id=part_id or 'part-'+uid()
        self.kind=choice([(k,TITLES[k]) for k in ('round_specimen','flat_specimen','wafer')]);self.name=QLineEdit(self.original['name'] if self.original else '원통형 시편');self.controls.addWidget(self.kind);self.controls.addWidget(self.name);self.diagram=SpecimenDiagram();self.controls.addWidget(self.diagram);self.form=QFormLayout();self.controls.addLayout(self.form);self.metrics=label('',True);self.controls.addWidget(self.metrics);self.controls.addStretch();self.inputs={}
        if self.original:self.kind.setCurrentIndex(self.kind.findData(self.original['geometry']['kind']))
        self.kind.currentIndexChanged.connect(self.rebuild);self.name.textChanged.connect(self.schedule);self.rebuild()
        saved=next((s for s in self.base.get('studies',[]) if s['kind']=='specimen-rule' and s['settings'].get('part_id')==self.part_id),None)
        self.rule_id=saved['id'] if saved else 'rule-'+uid();self.rule=choice([('custom','사용자 표점 길이'),('E8-4D','ASTM E8 · 원통 4D 표점'),('E8M-5D','ASTM E8M · 원통 5D 표점')]);self.mark=number(25,.01,2000,' mm');self.controls.insertWidget(self.controls.count()-1,label('표점 길이 L₀ · 평행부 길이와 별개'));self.controls.insertWidget(self.controls.count()-1,self.rule);self.controls.insertWidget(self.controls.count()-1,self.mark);self.rule_result=label('',True);self.controls.insertWidget(self.controls.count()-1,self.rule_result)
        if saved:self.rule.setCurrentIndex(max(0,self.rule.findData(saved['settings']['rule'])));self.mark.setValue(saved['settings']['mark_length'])
        self.rule.currentIndexChanged.connect(self.schedule);self.mark.valueChanged.connect(self.schedule)
    def rebuild(self):
        clear_layout(self.form);kind=self.kind.currentData();g=self.original['geometry'] if self.original and self.original['geometry']['kind']==kind else part_default(kind).geometry.model_dump();self.inputs={}
        if not self.original:self.name.setText(TITLES[kind])
        for key,value in g.items():
            if key in FIELDS:
                w=number(value,0 if key=='flat_depth' else .01,2000,' mm');self.form.addRow(FIELDS[key][0],w);self.inputs[key]=w;w.valueChanged.connect(self.schedule)
        self.fit_next=True;self.schedule()
    def candidate(self):
        raw=deepcopy(self.base);g=dict(kind=self.kind.currentData(),**{k:w.value() for k,w in self.inputs.items()});self.diagram.g=g;self.diagram.update()
        if self.original:p=next(p for p in raw['parts'] if p['id']==self.part_id);p['geometry']=g
        else:
            p=part_default(g['kind'],self.part_id).model_dump();p['geometry']=g
            if raw['parts']:p['transform']['x']=max(q['transform']['x']+max(q['geometry'].get('length',0),q['geometry'].get('diameter',0),q['geometry'].get('width',0),100) for q in raw['parts'])+max(g.get('length',0),g.get('diameter',0))/2+25
            raw['parts'].append(p)
        p['name']=self.name.text().strip() or TITLES[g['kind']]
        if hasattr(self,'rule') and g['kind']!='wafer':
            from ..tensile import specimen_rule
            from ..models import GEOMETRY_TYPES
            report=specimen_rule(GEOMETRY_TYPES[g['kind']].model_validate(g),self.rule.currentData(),self.mark.value());self.rule_result.setText(f"L₀ {report['mark_length']:g} mm · "+('평행부 안에 들어갑니다.' if report['fits'] else '평행부보다 깁니다. 평행부 길이를 늘리세요.')+'\n'+report['note']);self.mark.setEnabled(self.rule.currentData()=='custom');raw['studies']=[s for s in raw.get('studies',[]) if s['id']!=self.rule_id]+[dict(id=self.rule_id,kind='specimen-rule',name='시편 표점 길이 검사',settings=dict(part_id=self.part_id,**report))]
        return raw
    def compute(self,raw):
        with KERNEL_LOCK:
            d=Design.model_validate(raw);preview(d)
            part=next(p.model_copy(deep=True) for p in d.parts if p.id==self.part_id)
            # Focus the specimen without altering other components in the
            # candidate document that will be committed on Apply.
            focused=preview(Design(parts=[part]));return d,focused
    def present(self):
        super().present();g=next(p.geometry for p in self.checked.parts if p.id==self.part_id)
        if g.kind=='wafer':self.metrics.setText(f"두께 {g.thickness:g} mm = {g.thickness*1000:g} µm\n플랫 깊이 {g.flat_depth:g} mm")
        else:
            area=math.pi*g.gauge_diameter**2/4 if g.kind=='round_specimen' else g.gauge_width*g.thickness;grip=(g.length-g.gauge_length-2*g.transition_length)/2;self.metrics.setText(f"평행부 단면적 {area:.4f} mm²\n한쪽 그립 길이 {grip:g} mm\n전이부: 수평 접선을 갖는 곡선")


class RobotDialog(PreviewDialog):
    def __init__(self,parent,design=None):
        super().__init__(parent,'로봇 조립 치수','링크 중심 간격과 핀 치수를 바꾸면 연결된 관절과 핀이 함께 갱신됩니다.')
        self.base=deepcopy(design) if design else None;self.ids={k:k for k in ('base','link-1','link-2','pin-1','pin-2')};self.mate_ids={k:k for k in ('shoulder','elbow','shoulder-pin','elbow-pin')};self.existing=False
        if design:
            for shoulder in design['mates']:
                if shoulder['id']=='shoulder' or shoulder['id'].endswith('-shoulder'):
                    prefix=shoulder['id'][:-len('shoulder')];lookup={m['id']:m for m in design['mates']}
                    if all(prefix+k in lookup for k in self.mate_ids):
                        self.mate_ids={k:prefix+k for k in self.mate_ids};self.ids=dict(base=shoulder['parent'],**{'link-1':shoulder['child'],'link-2':lookup[prefix+'elbow']['child'],'pin-1':lookup[prefix+'shoulder-pin']['child'],'pin-2':lookup[prefix+'elbow-pin']['child']});self.existing=all(k in {p['id'] for p in design['parts']} for k in self.ids.values());break
        source=design if self.existing else preset('robot_arm').model_dump();parts={key:next(p for p in source['parts'] if p['id']==actual) for key,actual in self.ids.items()} if self.existing else {p['id']:p for p in source['parts']};mates={key:next(m for m in source['mates'] if m['id']==actual) for key,actual in self.mate_ids.items()} if self.existing else {m['id']:m for m in source['mates']};self.prefix='robot-'+uid()[:8]+'-';self.inputs={};form=QFormLayout();self.controls.addLayout(form)
        defaults=[('l1','링크 1 중심 간격',parts['link-1']['geometry']['hole_spacing'],.1,1800,' mm'),('l2','링크 2 중심 간격',parts['link-2']['geometry']['hole_spacing'],.1,1800,' mm'),('width','링크 폭',parts['link-1']['geometry']['width'],1,400,' mm'),('thickness','링크 두께',parts['link-1']['geometry']['thickness'],.1,200,' mm'),('pin','핀 직경',parts['pin-1']['geometry']['diameter'],.1,200,' mm'),('clearance','핀 지름 여유',parts['link-1']['geometry']['hole_diameter']-parts['pin-1']['geometry']['diameter'],.01,10,' mm'),('gap','링크 층 간격',mates['elbow']['z'],0,100,' mm'),('a1','어깨 각도',mates['shoulder']['rz'],-180,180,' °'),('a2','팔꿈치 상대 각도',mates['elbow']['rz'],-180,180,' °')]
        for key,title,value,lo,hi,suffix in defaults:w=number(value,lo,hi,suffix);self.inputs[key]=w;form.addRow(title,w);w.valueChanged.connect(self.schedule)
        self.controls.addWidget(label('베이스는 고정되고, 두 회전 관절은 링크의 구멍 중심에 연결됩니다. 핀은 해당 부품과 강체로 연결됩니다.',True));self.controls.addStretch();self.schedule()
    def candidate(self):
        v={k:w.value() for k,w in self.inputs.items()};robot=preset('robot_arm').model_dump();parts={p['id']:p for p in robot['parts']};mates={m['id']:m for m in robot['mates']}
        for key,length in [('link-1',v['l1']),('link-2',v['l2'])]:parts[key]['geometry'].update(length=length+v['width'],hole_spacing=length,width=v['width'],thickness=v['thickness'],hole_diameter=v['pin']+v['clearance'])
        parts['base']['geometry'].update(diameter=max(50,v['width']*2),bore_diameter=v['pin']+v['clearance']);parts['pin-1']['geometry'].update(diameter=v['pin'],height=10+v['thickness']);parts['pin-2']['geometry'].update(diameter=v['pin'],height=2*v['thickness']+v['gap']);mates['shoulder']['rz']=v['a1'];mates['elbow'].update(rz=v['a2'],z=v['gap']);mates['elbow-pin']['z']=0
        if self.existing:
            raw=deepcopy(self.base)
            for part in raw['parts']:
                canonical=next((key for key,actual in self.ids.items() if actual==part['id']),None)
                if canonical:part['geometry']=parts[canonical]['geometry']
            for mate in raw['mates']:
                canonical=next((key for key,actual in self.mate_ids.items() if actual==mate['id']),None)
                if canonical:mate.update({k:mates[canonical][k] for k in ('x','y','z','rx','ry','rz')})
            return raw
        if not self.base:return robot
        raw=deepcopy(self.base)
        robot['parts'][0]['transform']['x']=max(p['transform']['x']+max(p['geometry'].get('length',0),p['geometry'].get('diameter',0),100) for p in raw['parts'])+75 if raw['parts'] else 0
        for part in robot['parts']:part['id']=self.prefix+part['id']
        for mate in robot['mates']:
            for key in ('id','parent','child'):mate[key]=self.prefix+mate[key]
        raw['parts'].extend(robot['parts']);raw['mates'].extend(robot['mates']);return raw


class JointDriveDialog(PreviewDialog):
    def __init__(self,parent,design,selected_joint=None):
        super().__init__(parent,'관절 구동 · 간섭 확인','각도 또는 이동량을 조절하세요. 연결된 부품과 하위 부품이 함께 움직입니다. 적용한 자세는 작업 기록에 남습니다.')
        self.base=deepcopy(design);self.inputs={};self.changed_axes=set();self.groups={};names={p['id']:p['name'] for p in design['parts']}
        self.passive={j for c in design.get('loops',[]) for j in c['passive_joints']};self.sliders={}
        from ..assembly_motion import JOINT_AXES
        self.linked_axes={(l['driven'],l['driven_axis']) for l in design.get('motion_links',[])}
        self.joint_filter=choice([('', '전체 관절')]+[(m['id'],m['id']+' · '+names[m['child']]) for m in design['mates'] if m['kind']!='rigid'])
        self.controls.addWidget(label('조작할 관절'));self.controls.addWidget(self.joint_filter)
        for mate in design['mates']:
            if mate['kind']=='rigid':continue
            group=QWidget();group_layout=QVBoxLayout(group);group_layout.setContentsMargins(0,0,0,0);self.groups[mate['id']]=group;self.controls.addWidget(group)
            title=label(names[mate['parent']]+' → '+names[mate['child']]);title.setStyleSheet('font-weight:600;color:#8ed5c6;');group_layout.addWidget(title)
            for key in JOINT_AXES[mate['kind']]:
                lo,hi=mate.get('limits',{}).get(key,[-360,360] if key.startswith('r') else [-5000,5000])
                row=QHBoxLayout();w=number(mate[key],lo,hi,' °' if key.startswith('r') else ' mm',decimals=6);row.addWidget(QLabel(key.upper()));row.addWidget(w);group_layout.addLayout(row);slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(math.ceil(w.minimum()*10),math.floor(w.maximum()*10));slider.setValue(round(w.value()*10));group_layout.addWidget(slider);slider.valueChanged.connect(lambda v,spin=w:spin.setValue(v/10))
                slider.setEnabled(slider.minimum()<slider.maximum())
                def changed(v,s=slider,axis=(mate['id'],key)):
                    self.changed_axes.add(axis);s.blockSignals(True);s.setValue(round(v*10));s.blockSignals(False);self.schedule()
                w.valueChanged.connect(changed);self.inputs[(mate['id'],key)]=w
                self.sliders[(mate['id'],key)]=slider
                if mate['id'] in self.passive or (mate['id'],key) in self.linked_axes:w.setEnabled(False);slider.setEnabled(False);w.setToolTip('폐루프 또는 모션 연결이 계산하는 관절입니다.')
        def filter_joints():
            selected=self.joint_filter.currentData()
            for identifier,group in self.groups.items():group.setVisible(not selected or selected==identifier)
        self.joint_filter.currentIndexChanged.connect(filter_joints)
        self.joint_filter.setCurrentIndex(max(0,self.joint_filter.findData(selected_joint)));filter_joints()
        self.collisions=label('',True);self.controls.addWidget(self.collisions);self.controls.addStretch();self.schedule()
    def candidate(self):
        from ..assembly_motion import set_joint_motion
        raw=deepcopy(self.base)
        for mate in raw['mates']:
            values={key:self.inputs[(mate['id'],key)].value() for mid,key in self.changed_axes if mid==mate['id']}
            if values:set_joint_motion(raw,mate['id'],values)
        return raw
    def present(self):
        super().present();names={p.id:p.name for p in self.checked.parts};collisions=self.result['stats']['collisions'];self.collisions.setText('체적 간섭 없음' if not collisions else '간섭 부품\n'+'\n'.join(f"{names[c['a']]} ↔ {names[c['b']]}\n{c['volume']:.3f} mm³" for c in collisions));self.collisions.setStyleSheet('color:#f3ac97;' if collisions else 'color:#89d6c0;')
        self.apply_button.setEnabled(any(self.inputs[(mid,key)].value()!=next(m for m in self.base['mates'] if m['id']==mid)[key] for mid,key in self.changed_axes))
        for mate in self.checked.mates:
            if mate.id in self.passive or any(mate.id==j for j,k in self.linked_axes):
                for key in ('x','y','z','rx','ry','rz'):
                    if (mate.id,key) in self.inputs:
                        w=self.inputs[(mate.id,key)];w.blockSignals(True);w.setValue(getattr(mate,key));w.blockSignals(False);s=self.sliders[(mate.id,key)];s.blockSignals(True);s.setValue(round(getattr(mate,key)*10));s.blockSignals(False)
        stats=self.result['stats']['assembly_constraints']
        if stats.get('loops'):self.status.setText(self.status.text()+f" · 폐루프 오차 {stats['closure_error_mm']:.2g} mm · 자유도 {stats['dof']}")
        for collision in collisions:
            for identifier in (collision['a'],collision['b']):self.viewport.actors[identifier][0].GetProperty().SetColor(.83,.30,.20)
        self.viewport.window.Render()


def frame_record(part,face):
    record=dict(face=face['index'],face_count=face['face_count'],support_feature=part['features'][-1]['id'] if part['features'] else 'base',origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'])
    if face.get('reference'):record['reference']=face['reference']
    return record


class FaceJointDialog(PreviewDialog):
    def __init__(self,parent,design,first,second):
        super().__init__(parent,'면으로 조인트 만들기','먼저 고른 면이 기준입니다. 두 번째 부품을 맞추고 회전·이동 자유도를 지정하세요.')
        self.base=deepcopy(design);self.first=deepcopy(first);self.second=deepcopy(second);self.mate_id='mate-'+uid();parts={p['id']:p for p in design['parts']};self.controls.addWidget(label(parts[first[0]]['name']+' → '+parts[second[0]]['name']));self.kind=choice([('revolute','회전 관절 · 1 자유도'),('rigid','강체 고정 · 0 자유도'),('slider','직선 이동 · 1 자유도'),('cylindrical','회전 + 직선 이동 · 2 자유도'),('pin_slot','핀 슬롯 · 2 자유도'),('planar','평면 · 3 자유도'),('ball','볼 · 3 자유도')]);form=QFormLayout();form.addRow('조인트',self.kind);self.gap=number(0,-500,500,' mm');self.angle=number(0,-360,360,' °');form.addRow('면 사이 간격',self.gap);form.addRow('축 주위 각도',self.angle);self.controls.addLayout(form);self.flip=QCheckBox('두 면을 서로 마주 보게 연결');self.flip.setChecked(True);self.controls.addWidget(self.flip);self.controls.addWidget(label('평면 중심과 법선이 조인트 축입니다. 다른 구멍 중심을 쓰려면 기존 조립 구속의 기준점 선택을 이용하세요.',True));self.controls.addStretch()
        for w in (self.gap,self.angle):w.valueChanged.connect(self.schedule)
        self.kind.currentIndexChanged.connect(self.schedule);self.flip.toggled.connect(self.schedule);self.schedule()
    def candidate(self):
        raw=deepcopy(self.base);parts={p['id']:p for p in raw['parts']};pa,ca=self.first[0],self.second[0]
        if any(m['child']==ca for m in raw['mates']):raise ValueError('두 번째 부품에는 이미 조인트가 있습니다. 기존 조인트를 편집하거나 삭제한 뒤 연결하세요.')
        if not any(m['child']==pa for m in raw['mates']):parts[pa]['fixed']=True
        parts[ca]['fixed']=False
        raw['mates'].append(dict(id=self.mate_id,kind=self.kind.currentData(),parent=pa,child=ca,rz=self.angle.value(),z=self.gap.value()))
        raw.setdefault('joint_frames',[]).append(dict(mate_id=self.mate_id,parent=frame_record(parts[pa],self.first[1]),child=frame_record(parts[ca],self.second[1]),flipped=self.flip.isChecked()))
        return raw
