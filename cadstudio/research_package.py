"""Portable experiment handoff, not a fatigue solver or instrument controller."""
from datetime import datetime,timezone
import hashlib,json,math,os,tempfile
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from typing import Literal
from pydantic import Field
from .models import Design,StrictModel


class TestProtocol(StrictModel):
    __test__=False
    material_id: Literal['aluminum','silicon_wafer']='aluminum'
    method: Literal['axial_tension_compression','undecided']='axial_tension_compression'
    batch: str=Field(default='',max_length=160)
    max_force_N: float|None=Field(default=None,gt=0)
    frequency_Hz: float|None=Field(default=None,gt=0)
    peak_to_peak_stroke_mm: float|None=Field(default=None,gt=0)


HEADERS='time_s,cycle_index,force_N,crosshead_displacement_mm,gauge_strain,temperature_C,source,quality_flag\n'
NOTES='''Research experiment handoff / 연구 시험 준비 패키지

This package contains geometry and an OPERATOR-PLANNED protocol, not measured
data, fatigue predictions, machine ratings, or a validated research-solver input.
No .ftgsim import or external solver execution is performed.

measurements-template.csv contains only column headers, NO generated measurements.
Use physical time in seconds, signed axial force in N (positive=tension),
crosshead displacement in mm, independently measured gauge strain (dimensionless),
temperature in Celsius, acquisition source and quality flag. Leave unavailable
channels blank. Cycle index is optional; preserve raw channels before derivation.
Crosshead displacement is NOT gauge strain. Do not infer strain without a
validated gauge-length/sensor/compliance correction.

Specified force, Hz and peak-to-peak stroke are desired test settings ONLY.
Empty settings are undecided, NOT zero or machine-rated capacity.
The Al research model's time/frequency are model units unless independently
calibrated to physical seconds/Hz. No conversion or probability is fabricated.
Nominal areas come from the base specimen dimensions; features can alter them.
End traction to force uses end area; gauge stress uses gauge area. Do not silently
substitute one for the other. Keep force measurements separately.
Si wafer test/fixture validation remains undecided; Al round grips are not reused
as a validated wafer protocol. Confirm brittle-specimen fixture and method first.

실측 원시 데이터와 해석 모델 출력은 구분하세요. 이 파일은 시험 조건 정리와
데이터 교환을 위한 양식이며 장비 구동 명령이나 제작 승인서가 아닙니다.
'''


def manifest(design,part_id,protocol):
    design=Design.model_validate(design);protocol=TestProtocol.model_validate(protocol)
    part=next((p for p in design.parts if p.id==part_id),None)
    if part is None:raise ValueError('내보낼 시편을 선택하세요.')
    if protocol.material_id=='silicon_wafer' and protocol.method!='undecided':
        raise ValueError('웨이퍼 시험 방식과 고정구는 아직 확인되지 않았습니다. 시험 방식을 미정으로 두세요.')
    if part.geometry.kind=='wafer' and protocol.material_id!='silicon_wafer':
        raise ValueError('웨이퍼 시편은 silicon_wafer 재료를 선택하세요.')
    raw=part.model_dump();g=raw['geometry'];areas={}
    if g['kind']=='round_specimen':areas=dict(gauge=math.pi*g['gauge_diameter']**2/4,end=math.pi*g['grip_diameter']**2/4)
    elif g['kind']=='flat_specimen':areas=dict(gauge=g['gauge_width']*g['thickness'],end=g['grip_width']*g['thickness'])
    digest=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return dict(format='promptcad-experiment-handoff',version=1,created_utc=datetime.now(timezone.utc).isoformat(),
        specimen_id=part.id,specimen_sha256=digest,specimen_snapshot=raw,
        nominal_base_areas_mm2=areas,area_status='nominal_base_only' if areas else 'not_available',
        protocol=protocol.model_dump(),protocol_status='operator_plan_unverified',measurements_status='template_only',
        model_time_mapping=None,solver_integration=False,
        channels=dict(time_s='s',cycle_index='count',force_N='N; positive=tension',crosshead_displacement_mm='mm',gauge_strain='dimensionless, independent gauge measurement',temperature_C='degC',source='acquisition source',quality_flag='operator/acquisition quality'))


def export_package(raw,part_id,protocol,path):
    from .kernel import KERNEL_LOCK,build
    import cadquery as cq
    design=Design.model_validate(raw);data=manifest(design,part_id,protocol)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # A private, bounded temp directory prevents overwriting a previous package
    # until both the real STEP export and archive have completed.
    with tempfile.TemporaryDirectory(prefix='cad-research-',dir=path.parent) as temp:
        temp=Path(temp);step=temp/'specimen.step'
        with KERNEL_LOCK:
            shapes=build(design);index=next(i for i,p in enumerate(design.parts) if p.id==part_id)
            shape=shapes[index]
            if not shape.isValid():raise ValueError('시편 형상이 유효하지 않습니다.')
            cq.exporters.export(shape,str(step))
        data['step_sha256']=hashlib.sha256(step.read_bytes()).hexdigest()
        archive=temp/'research.zip'
        with ZipFile(archive,'w',ZIP_DEFLATED) as z:
            z.writestr('protocol.json',json.dumps(data,ensure_ascii=False,indent=2))
            z.writestr('measurements-template.csv',HEADERS)
            z.writestr('README.txt',NOTES);z.write(step,'specimen.step')
        os.replace(archive,path)
    return path
