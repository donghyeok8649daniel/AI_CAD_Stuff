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
