"""Export evaluated parts independently without breaking their dependencies."""
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED
import cadquery as cq
from .kernel import KERNEL_LOCK,build,exact_bounds
from .models import Design


def export_parts(raw, identifiers, destination, formats=('step','stl'), placement='local'):
    if not formats or set(formats)-{'step','stl'}:raise ValueError('STEP / STL 형식을 선택하세요.')
    if placement not in ('local','assembly'):raise ValueError('부품 원점 또는 조립 위치를 선택하세요.')
    design=Design.model_validate(raw).model_copy(deep=True);ids=set(identifiers)
    if not ids or not ids<={p.id for p in design.parts}:raise ValueError('내보낼 부품을 선택하세요.')
    target=Path(destination);temporary=target.with_name(target.name+'.'+uuid4().hex+'.tmp')
    manifest=dict(units='mm',placement=placement,parts=[])
    try:
        with KERNEL_LOCK,TemporaryDirectory(prefix='promptcad-parts-') as scratch:
            shapes=build(design)
            with ZipFile(temporary,'w',ZIP_DEFLATED) as archive:
                for index,(part,world) in enumerate(zip(design.parts,shapes),1):
                    if part.id not in ids:continue
                    shape=world
                    if placement=='local':
                        t=part.transform;shape=shape.translate((-t.x,-t.y,-t.z))
                        for angle,axis in [(t.rz,(0,0,1)),(t.ry,(0,1,0)),(t.rx,(1,0,0))]:
                            if angle:shape=shape.rotate((0,0,0),axis,-angle)
                        bounds=exact_bounds(shape);shape=shape.translate((-(bounds.xmin+bounds.xmax)/2,-(bounds.ymin+bounds.ymax)/2,-bounds.zmin))
                    if not shape.isValid() or not shape.Solids():raise ValueError('유효한 솔리드 부품만 개별 출력할 수 있습니다: '+part.name)
                    safe=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',part.name).strip(' .')[:55] or 'part'
                    base=f'{index:03d}_{safe}_{part.id}';names=[]
                    for fmt in dict.fromkeys(formats):
                        name=base+'.'+fmt;path=Path(scratch)/name
                        if fmt=='step':
                            a=cq.Assembly();a.add(shape,name=part.id,color=cq.Color(*[int(part.color[i:i+2],16)/255 for i in (1,3,5)]));a.export(str(path),'STEP')
                        else:cq.exporters.export(shape,str(path),exportType='STL',tolerance=.025,angularTolerance=.1)
                        archive.write(path,name);names.append(name)
                    manifest['parts'].append(dict(id=part.id,name=part.name,files=names,source_transform=part.transform.model_dump(),volume_mm3=shape.Volume()))
                archive.writestr('parts.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        os.replace(temporary,target)
        return manifest
    finally:temporary.unlink(missing_ok=True)
