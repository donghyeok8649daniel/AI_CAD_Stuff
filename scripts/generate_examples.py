"""Rebuild the reviewable sample projects and real CAD exports."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cadstudio.catalog import catalog, preset
from cadstudio.kernel import export, preview
from cadstudio.models import Design, Project

destination = ROOT / "examples"
destination.mkdir(exist_ok=True)
report = []
for item in catalog():
    design = Design.model_validate(item["design"])
    (destination / f"{item['kind']}.cad.json").write_text(Project(design=design,prompt=item["example"]).model_dump_json(indent=2), encoding="utf-8")
    stats = preview(design)["stats"]
    if item["kind"] in {"round_specimen", "wafer", "bracket", "extrusion", "robot_arm"}:
        for fmt in ("step", "stl"):
            export(design, destination / f"{item['kind']}.{fmt}", fmt)
    report.append({"kind":item["kind"], **stats})
(destination / "geometry-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Created {len(report)} valid example projects in {destination}")

# A reproducible face sketch with a fully constrained 20 x 10 mm rectangular boss.
design=preset('plate');data=design.model_dump();mesh=preview(design)['meshes'][0]
face=next(f for f in mesh['faces'] if f['planar'] and f['normal']==[0,0,1])
sketch=dict(kind='extrusion',thickness=5,points=[dict(x=-10,y=-5),dict(x=10,y=-5),dict(x=10,y=5),dict(x=-10,y=5)],constraints=[
    dict(kind='fixed',a=0,x=-10,y=-5),dict(kind='horizontal',a=0,b=1),dict(kind='vertical',a=1,b=2),
    dict(kind='horizontal',a=2,b=3),dict(kind='vertical',a=3,b=0),dict(kind='distance',a=0,b=1,value=20),dict(kind='distance',a=1,b=2,value=10)])
data['name']='완전 구속 면 스케치 예제'
data['parts'][0]['features']=[dict(id='face-sketch',name='20 x 10 돌출',face=face['index'],support_face_count=face['face_count'],normal=face['normal'],operation='add',sketch=sketch)]
design=Design.model_validate(data)
(destination/'face_sketch.cad.json').write_text(Project(design=design).model_dump_json(indent=2),encoding='utf-8')
export(design,destination/'face_sketch.step','step')

# Analytic sketch and a face-cut history, reproducible without a browser or API key.
from copy import deepcopy
from cadstudio.models import Extrusion,Part
entities=[
    dict(id='top',kind='line',start=dict(x=-20,y=10),end=dict(x=20,y=10)),
    dict(id='right',kind='arc',center=dict(x=20,y=0),radius=10,start_angle=90,sweep=-180),
    dict(id='bottom',kind='line',start=dict(x=20,y=-10),end=dict(x=-20,y=-10)),
    dict(id='left',kind='arc',center=dict(x=-20,y=0),radius=10,start_angle=-90,sweep=-180),
    dict(id='hole-left',kind='circle',center=dict(x=-20,y=0),radius=3),
    dict(id='hole-right',kind='circle',center=dict(x=20,y=0),radius=3),
]
base=Design(name='슬롯과 면 구멍 · 작업 기록 예제',parts=[Part(id='link',name='슬롯 스케치 부품',geometry=Extrusion(sketch_mode='entities',entities=entities,thickness=8))])
data=base.model_dump();face=next(f for f in preview(base)['meshes'][0]['faces'] if f['planar'] and f['normal']==[0,0,1])
cut=Extrusion(sketch_mode='entities',entities=[dict(id='pocket',kind='circle',center=dict(x=0,y=0),radius=4)],thickness=3,entity_constraints=[dict(id='origin',kind='fixed',a='pocket',a_point='center',x=0,y=0),dict(id='diameter',kind='diameter',a='pocket',value=8)])
data['parts'][0]['features']=[dict(id='pocket-cut',name='원점 중심 구멍',face=face['index'],support_face_count=face['face_count'],support_feature='base',normal=face['normal'],origin=face['origin'],x_direction=face['x_direction'],operation='cut',sketch=cut.model_dump())]
finished=Design.model_validate(data)
journal=dict(base=base.model_dump(),cursor='cut',head='cut',entries=[
    dict(id='base',label='슬롯·원 스케치 예제 생성',created_at='2026-09-22T00:00:00Z',source='import',context={'part_id':'link','tool_actions':[{'tool':'예제 스크립트 · 직선/원호/원', 'after':entities}]}),
    dict(id='cut',parent='base',label='상면 원점 구속 구멍',created_at='2026-09-22T00:00:01Z',source='import',changes=[dict(path=['parts',0,'features'],before=[],after=finished.parts[0].model_dump()['features'])],context={'part_id':'link','feature_id':'pocket-cut','face':{k:face[k] for k in ['index','origin','normal','x_direction']},'tool_actions':[{'tool':'예제 스크립트 · 원점 고정 + 직경', 'constraints_after':cut.model_dump()['entity_constraints']}]}),
])
project=Project(design=finished,history=journal,prompt='스크립트로 재현하는 예제: 슬롯 스케치, 양단 관통 구멍, 상면 원점 고정 파내기')
(destination/'analytic_history.cad.json').write_text(project.model_dump_json(indent=2),encoding='utf-8')
export(finished,destination/'analytic_history.step','step')
