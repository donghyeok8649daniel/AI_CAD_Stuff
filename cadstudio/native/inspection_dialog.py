from copy import deepcopy
from PySide6.QtWidgets import QFormLayout,QLineEdit,QCheckBox
from .workflows import PreviewDialog,choice
from .widgets import number,label
from ..models import Design,Material
from ..kernel import build,KERNEL_LOCK
from ..inspection import mass_properties,minimum_distance,angle_between,section


class MaterialDialog(PreviewDialog):
    def __init__(self,parent,design,part_id):
        super().__init__(parent,'부품 재질 / 물성','질량·관성과 로봇 동역학에 사용할 재질 값을 지정하세요. 실제 소재 데이터시트 값을 입력할 수 있습니다.')
        self.raw=deepcopy(design);self.part_id=part_id;p=next(p for p in design['parts'] if p['id']==part_id);material=Material.model_validate(p.get('material') or {})
        self.enabled=QCheckBox('이 부품에 개별 재질 지정');self.enabled.setChecked(True);self.controls.addWidget(self.enabled);form=QFormLayout();self.controls.addLayout(form);self.name=QLineEdit(material.name);self.density=number(material.density,.01,30000,' kg/m³');self.modulus=number(material.youngs_modulus,.01,1000000,' MPa');self.poisson=number(material.poisson,-.99,.499,'')
        for title,w in [('재질 이름',self.name),('밀도',self.density),('탄성계수',self.modulus),('포아송 비',self.poisson)]:form.addRow(title,w);(w.textChanged if hasattr(w,'textChanged') else w.valueChanged).connect(self.schedule)
        self.controls.addWidget(label('초기 수치는 사용자 입력 예시입니다. 재질 인증값이 아닙니다. 밀도는 질량과 관성에, 탄성계수·포아송 비는 재질 기록에 저장됩니다.',True));self.controls.addStretch();self.enabled.toggled.connect(self.schedule);self.schedule()
    def candidate(self):
        raw=deepcopy(self.raw);p=next(p for p in raw['parts'] if p['id']==self.part_id)
        if self.enabled.isChecked():p['material']=Material(name=self.name.text(),density=self.density.value(),youngs_modulus=self.modulus.value(),poisson=self.poisson.value()).model_dump()
        else:p.pop('material',None)
        return raw


class InspectionDialog(PreviewDialog):
    def __init__(self,parent,design,part_id=None):
        super().__init__(parent,'각도 / 간격 / 질량 / 단면 검사','대상을 클릭하거나 목록으로 지정하세요. 모든 길이는 mm, 각도는 °, 질량은 kg입니다.')
        self.base=deepcopy(design);self.mode=choice([('distance','몸체 사이 최소 간격'),('edge_angle','직선 모서리 사이 각도'),('face_angle','평면 사이 각도'),('mass','질량 / 무게중심 / 관성'),('section','평면 단면 / 단면적')]);self.controls.addWidget(self.mode);form=QFormLayout();self.controls.addLayout(form);items=[(p['id'],p['name']) for p in design['parts']];self.a=choice(items);self.b=choice(items);self.a.setCurrentIndex(max(0,self.a.findData(part_id)));self.b.setCurrentIndex(min(1,len(items)-1));self.ia=number(1,1,100000,'',0);self.ib=number(1,1,100000,'',0)
        self.rows={}
        for key,title,w in [('a','첫 부품',self.a),('ia','첫 모서리 / 면 번호',self.ia),('b','두 번째 부품',self.b),('ib','둘째 모서리 / 면 번호',self.ib)]:form.addRow(title,w);self.rows[key]=w;(w.currentIndexChanged if hasattr(w,'currentIndexChanged') else w.valueChanged).connect(self.schedule)
        self.origin=[];self.normal=[]
        for group,key,values in [(self.origin,'단면 원점',[0,0,0]),(self.normal,'단면 법선',[0,0,1])]:
            for axis,value in zip('XYZ',values):w=number(value,-5000,5000,' mm' if group is self.origin else '');group.append(w);form.addRow(key+' '+axis,w);self.rows[key+axis]=w;w.valueChanged.connect(self.schedule)
        self.output=label('검사 결과를 준비합니다.');self.output.setStyleSheet('color:#b6f0dc;font-size:13px;');self.controls.addWidget(self.output);self.controls.addStretch();self.form=form;self.pick_second=False;self.mode.currentIndexChanged.connect(self.changed);self.viewport.geometry_selected.connect(self.picked_edge);self.viewport.face_selected.connect(self.picked_face);self.apply_button.setText('닫기')
        if len(design['parts'])==1:self.mode.setCurrentIndex(self.mode.findData('face_angle'))
        self.changed()
    def changed(self,*args):
        mode=self.mode.currentData();self.pick_second=False
        for key,w in self.rows.items():
            visible=key=='a' or key=='b' and mode in ('distance','edge_angle','face_angle') or key in ('ia','ib') and mode.endswith('angle') or key.startswith('단면') and mode=='section';w.setVisible(visible);self.form.labelForField(w).setVisible(visible)
        self.viewport.filter.setCurrentIndex(self.viewport.filter.findData('edge' if mode=='edge_angle' else 'face' if mode=='face_angle' else 'body'));self.schedule()
    def pick(self,part_id,index):
        target=self.b if self.pick_second else self.a;field=self.ib if self.pick_second else self.ia;target.setCurrentIndex(target.findData(part_id));field.setValue(index+1);self.pick_second=not self.pick_second;self.schedule()
    def picked_edge(self,part_id,kind,record):
        if self.mode.currentData()=='edge_angle':self.pick(part_id,record['index'])
    def picked_face(self,part_id,face):
        if self.mode.currentData()=='face_angle' and face:self.pick(part_id,face['index'])
    def candidate(self):
        raw=deepcopy(self.base);raw['_inspection']=dict(mode=self.mode.currentData(),a=self.a.currentData(),b=self.b.currentData(),ia=int(self.ia.value())-1,ib=int(self.ib.value())-1,origin=[w.value() for w in self.origin],normal=[w.value() for w in self.normal]);return raw
    @staticmethod
    def compute(raw):
        settings=raw.pop('_inspection')
        with KERNEL_LOCK:
            d,result=PreviewDialog.compute(raw);shapes=dict(zip((p.id for p in d.parts),build(d)));a=shapes[settings['a']];mode=settings['mode'];text='';overlay=[]
            if mode=='distance':
                if settings['a']==settings['b']:raise ValueError('서로 다른 부품 두 개를 선택하세요.')
                value=minimum_distance(a,shapes[settings['b']]);text=f"최소 간격 {value['distance_mm']:.6f} mm";overlay=[value['points']]
            elif mode.endswith('angle'):
                collection='Edges' if mode=='edge_angle' else 'Faces';one=getattr(a,collection)();two=getattr(shapes[settings['b']],collection)()
                if settings['ia']>=len(one) or settings['ib']>=len(two):raise ValueError('모서리 / 면 번호가 형상의 범위를 벗어났습니다.')
                angle=angle_between(one[settings['ia']],two[settings['ib']]);text=f'방향 각도 {angle:.6f}°\n작은 교차각 {min(angle,180-angle):.6f}°'
            elif mode=='mass':
                part=next(p for p in d.parts if p.id==settings['a'])
                if part.material is None:raise ValueError('부품 속성의 재질 / 물성에서 밀도를 먼저 지정하세요.')
                value=mass_properties(a,part.material.density);text=f"{part.material.name}\n질량 {value['mass_kg']:.6f} kg\n체적 {value['volume_mm3']:.3f} mm³\n표면적 {value['area_mm2']:.3f} mm²\n무게중심 · 세계 좌표 mm\n"+', '.join(f'{v:.4f}' for v in value['center_mm'])+'\n질량중심 관성 텐서 · kg·m²\n'+'\n'.join('  '.join(f'{v:.5g}' for v in row) for row in value['inertia_kg_m2'])
            else:
                shape=section(a,settings['origin'],settings['normal']);text=f'단면적 {shape.Area():.6f} mm²\n경계 길이 {sum(e.Length() for e in shape.Edges()):.6f} mm'
                for e in shape.Edges():
                    points=e.sample(2 if e.geomType()=='LINE' else 96)[0]
                    if e.IsClosed():points.append(points[0])
                    overlay.append([p.toTuple() for p in points])
            result['inspection']=dict(text=text,overlay=overlay);return d,result
    def present(self):
        super().present();data=self.result['inspection'];self.output.setText(data['text']);self.viewport.set_edge_candidates([dict(index=i,points=row) for i,row in enumerate(data['overlay'])]);self.viewport.highlight_edges(set(range(len(data['overlay']))))
        if self.mode.currentData()=='section':
            for actors in self.viewport.actors.values():actors[0].GetProperty().SetOpacity(.16)
            self.viewport.window.Render()
