"""Parametric specimen chamber components, not a certified sealed vessel.

The factory creates portable BREP parts with stable IDs. Its protected swept
volume, feedthrough motion and tool-access volumes are separate inspection
envelopes; they never hide real physical interference through grouping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Literal

import cadquery as cq
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Design, Part, ShapeAsset
from .imported import encode_shape
from .kernel import KERNEL_LOCK, exact_bounds


SEAL_SOURCE = 'https://www.parker.com/content/dam/Parker-com/Literature/O-Ring-Division-Literature/ORD-5700.pdf'
BELLOWS_SOURCE = 'https://www.metalbellows.com/assets/Bellows-Design-Data-Sheet-Submit-3.pdf'
BELLOWS_GUIDANCE_SOURCE = 'https://www.metalbellows.com/bellows-101/'
PRESSURE_SOURCE = 'https://usbellows.com/resources/technical-bulletins/bellows3/'


class ChamberModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ChamberBounds(ChamberModel):
    minimum_mm: tuple[float, float, float]
    maximum_mm: tuple[float, float, float]

    @model_validator(mode='after')
    def ordered(self):
        if any(b-a < .01 for a,b in zip(self.minimum_mm,self.maximum_mm)):
            raise ValueError('보호 영역의 각 축 길이는 0.01 mm 이상이어야 합니다.')
        if any(abs(value)>4500 for value in (*self.minimum_mm,*self.maximum_mm)):
            raise ValueError('챔버 기준 영역은 CAD 좌표 범위 안에 있어야 합니다.')
        return self

    @property
    def center(self):
        return tuple((a+b)/2 for a,b in zip(self.minimum_mm,self.maximum_mm))

    @property
    def size(self):
        return tuple(b-a for a,b in zip(self.minimum_mm,self.maximum_mm))


class StaticChamberPort(ChamberModel):
    id: str = Field(min_length=1,max_length=20,pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(default='정적 밀봉 포트',min_length=1,max_length=60)
    face: Literal['back','left','right'] = 'back'
    # Face-local millimetres: back=(X,Z); left/right=(Y,Z).
    position_uv_mm: tuple[float,float] | None = None
    bore_diameter_mm: float = Field(default=6,gt=0,le=100)
    sleeve_wall_mm: float = Field(default=2,ge=.1,le=20)
    radial_clearance_mm: float = Field(default=.2,ge=0,le=5)
    flange_diameter_mm: float = Field(default=24,ge=4,le=200)
    flange_thickness_mm: float = Field(default=4,ge=.5,le=30)
    seal_width_mm: float = Field(default=3,ge=.5,le=20)

    @model_validator(mode='after')
    def fitting_land(self):
        sleeve=self.bore_diameter_mm+2*self.sleeve_wall_mm
        if self.flange_diameter_mm <= sleeve+2*self.radial_clearance_mm+2*self.seal_width_mm+2:
            raise ValueError('포트 플랜지에는 관통 구멍 밖의 밀봉 랜드가 필요합니다.')
        return self


class ChamberRodInterface(ChamberModel):
    id: str = Field(min_length=1,max_length=20,pattern=r'^[A-Za-z0-9_-]+$')
    face: Literal['top','bottom'] = 'top'
    position_xy_mm: tuple[float,float] = (0,0)
    rod_diameter_mm: float = Field(default=12,gt=0,le=150)
    radial_clearance_mm: float = Field(default=.2,ge=0,le=5)
    bellows_inner_diameter_mm: float = Field(default=20,gt=0,le=200)
    bellows_outer_diameter_mm: float = Field(default=34,gt=0,le=300)
    bellows_wall_mm: float = Field(default=.4,ge=.05,le=3)
    installed_length_mm: float = Field(default=50,ge=5,le=500)
    stroke_min_mm: float = Field(default=-5,ge=-300,le=300)
    stroke_max_mm: float = Field(default=5,ge=-300,le=300)
    current_stroke_mm: float = Field(default=0,ge=-300,le=300)
    convolutions: int = Field(default=8,ge=2,le=32)
    cuff_length_mm: float = Field(default=3,ge=.5,le=20)
    supplier_compressed_length_mm: float | None = Field(default=None,gt=0,le=1000)
    supplier_extended_length_mm: float | None = Field(default=None,gt=0,le=1000)

    @model_validator(mode='after')
    def motion_dimensions(self):
        if self.bellows_inner_diameter_mm <= self.rod_diameter_mm+2*self.radial_clearance_mm:
            raise ValueError('벨로즈 내경은 이동 로드의 여유 포함 지름보다 커야 합니다.')
        if self.bellows_outer_diameter_mm <= self.bellows_inner_diameter_mm+4*self.bellows_wall_mm:
            raise ValueError('벨로즈 외경에 주름과 벽 두께 여유가 부족합니다.')
        if self.stroke_min_mm>self.stroke_max_mm or self.installed_length_mm+self.stroke_min_mm<=2*self.cuff_length_mm:
            raise ValueError('벨로즈 운동 범위 또는 압축 길이가 올바르지 않습니다.')
        if not self.stroke_min_mm<=self.current_stroke_mm<=self.stroke_max_mm:
            raise ValueError('현재 로드 위치가 지정한 운동 범위 밖에 있습니다.')
        minimum=self.installed_length_mm+self.stroke_min_mm
        maximum=self.installed_length_mm+self.stroke_max_mm
        if self.supplier_compressed_length_mm is not None and minimum<self.supplier_compressed_length_mm:
            raise ValueError('요청 스트로크가 공급사 최소 압축 길이를 벗어납니다.')
        if self.supplier_extended_length_mm is not None and maximum>self.supplier_extended_length_mm:
            raise ValueError('요청 스트로크가 공급사 최대 신장 길이를 벗어납니다.')
        return self


class ParasiticForceInputs(ChamberModel):
    pressure_differential_pa: float | None = Field(default=None,ge=-1e7,le=1e7)
    bellows_effective_area_mm2: float | None = Field(default=None,gt=0,le=1e8)
    bellows_spring_rate_n_per_mm: float | None = Field(default=None,ge=0,le=1e6)
    bellows_deflection_from_free_mm: float | None = Field(default=None,ge=-1000,le=1000)
    seal_friction_n: float | None = Field(default=None,ge=0,le=1e6)
    preload_n: float | None = Field(default=None,ge=-1e6,le=1e6)
    test_force_n: float | None = Field(default=None,gt=0,le=1e7)


class ChamberSpecimenAperture(ChamberModel):
    """A declared open passage; never silently represented as a dynamic seal."""
    id: str = Field(min_length=1,max_length=20,pattern=r'^[A-Za-z0-9_-]+$')
    face: Literal['top','bottom']
    position_xy_mm: tuple[float,float] = (0,0)
    specimen_swept_diameter_mm: float = Field(gt=0,le=300)
    radial_clearance_mm: float = Field(default=.2,ge=.05,le=10)
    specimen_part_id: str = Field(default='',max_length=40,pattern=r'^[A-Za-z0-9_-]*$')
    seal_status: Literal['unresolved'] = 'unresolved'


class StaticChamberRodSeal(ChamberModel):
    """Stationary rod with a declared static radial O-ring gland geometry."""
    id: str = Field(min_length=1,max_length=20,pattern=r'^[A-Za-z0-9_-]+$')
    face: Literal['top','bottom'] = 'top'
    position_xy_mm: tuple[float,float] = (0,0)
    rod_diameter_mm: float = Field(default=20,gt=0,le=150)
    cross_section_mm: float = Field(default=3,ge=.5,le=10)
    radial_compression_fraction: float = Field(default=.2,gt=0,le=.3)
    axial_gland_extra_mm: float = Field(default=.5,ge=.1,le=5)
    cap_thickness_mm: float = Field(default=2,ge=1.5,le=10)
    cap_outer_diameter_mm: float = Field(default=46,ge=12,le=200)
    cap_bore_clearance_mm: float = Field(default=.2,ge=.05,le=2)

    @model_validator(mode='after')
    def gland_fill(self):
        radial=self.cross_section_mm*(1-self.radial_compression_fraction)
        depth=self.cross_section_mm**2/radial+self.axial_gland_extra_mm
        fill=math.pi*self.cross_section_mm**2/4/(radial*depth)
        if not .6<=fill<=.85:
            raise ValueError('정적 O링 홈 충진율이 60~85% 설계 검토 범위를 벗어납니다. 단면과 홈 여유를 다시 지정하세요.')
        return self


class ParasiticForceEstimate(ChamberModel):
    pressure_force_n: float | None = None
    spring_force_n: float | None = None
    conservative_force_bound_n: float | None = None
    fraction_of_test_force: float | None = None
    unknown_inputs: list[str] = Field(default_factory=list)
    estimate_only: Literal[True] = True


def estimate_parasitic_force(inputs: ParasiticForceInputs | dict | None = None):
    values=ParasiticForceInputs.model_validate(inputs or {})
    unknown=[name for name,value in values.model_dump().items() if value is None]
    pressure=(values.pressure_differential_pa*values.bellows_effective_area_mm2*1e-6
              if values.pressure_differential_pa is not None and values.bellows_effective_area_mm2 is not None else None)
    spring=(values.bellows_spring_rate_n_per_mm*values.bellows_deflection_from_free_mm
            if values.bellows_spring_rate_n_per_mm is not None and values.bellows_deflection_from_free_mm is not None else None)
    total=(abs(pressure)+abs(spring)+values.seal_friction_n+abs(values.preload_n)
           if pressure is not None and spring is not None and values.seal_friction_n is not None and values.preload_n is not None else None)
    ratio=total/values.test_force_n if total is not None and values.test_force_n is not None else None
    return ParasiticForceEstimate(pressure_force_n=pressure,spring_force_n=spring,
        conservative_force_bound_n=total,fraction_of_test_force=ratio,unknown_inputs=unknown)


def _default_ports():
    return [StaticChamberPort(id='humidity-in',name='습도 공급 포트'),
            StaticChamberPort(id='humidity-out',name='습도 배출 포트')]


class ChamberRequirements(ChamberModel):
    protected_swept_bounds: ChamberBounds
    prefix: str = Field(default='chamber',min_length=1,max_length=16,pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(default='시편 습도 챔버',min_length=1,max_length=60)
    clearance_mm: tuple[float,float,float] = (10,10,10)
    wall_thickness_mm: float = Field(default=6,ge=1,le=50)
    door_thickness_mm: float = Field(default=6,ge=1,le=30)
    front_flange_width_mm: float = Field(default=20,ge=5,le=100)
    gasket_thickness_mm: float = Field(default=2,ge=.2,le=10)
    gasket_compression_fraction: float = Field(default=.2,ge=0,le=.3)
    gasket_width_mm: float = Field(default=4,ge=1,le=20)
    gasket_land_mm: float = Field(default=1,ge=.1,le=10)
    observation_window: bool = True
    window_width_mm: float | None = Field(default=None,ge=10,le=1500)
    window_height_mm: float | None = Field(default=None,ge=10,le=1500)
    window_thickness_mm: float = Field(default=5,ge=1,le=30)
    window_overlap_mm: float = Field(default=8,ge=3,le=30)
    window_retainer_width_mm: float = Field(default=8,ge=4,le=30)
    window_retainer_thickness_mm: float = Field(default=3,ge=1,le=20)
    fastener_diameter_mm: float = Field(default=4,ge=1,le=20)
    fastener_radial_clearance_mm: float = Field(default=.2,ge=0,le=3)
    fastener_head_diameter_mm: float = Field(default=8,ge=2,le=40)
    fastener_head_thickness_mm: float = Field(default=4,ge=1,le=20)
    fastener_nut_thickness_mm: float = Field(default=3,ge=1,le=20)
    tool_access_radius_mm: float = Field(default=6,ge=2,le=30)
    tool_access_length_mm: float = Field(default=40,ge=5,le=250)
    static_ports: list[StaticChamberPort] = Field(default_factory=_default_ports,max_length=12)
    rod_interfaces: list[ChamberRodInterface] = Field(default_factory=list,max_length=4)
    specimen_apertures: list[ChamberSpecimenAperture] = Field(default_factory=list,max_length=2)
    static_rod_seals: list[StaticChamberRodSeal] = Field(default_factory=list,max_length=4)
    parasitic_force: ParasiticForceInputs = Field(default_factory=ParasiticForceInputs)

    @model_validator(mode='after')
    def usable_layout(self):
        if any(not math.isfinite(value) or value<.1 or value>200 for value in self.clearance_mm):
            raise ValueError('각 축 챔버 여유는 0.1~200 mm로 지정하세요.')
        if self.fastener_head_diameter_mm<=self.fastener_diameter_mm+2*self.fastener_radial_clearance_mm:
            raise ValueError('체결 머리는 여유 포함 관통 구멍보다 커야 합니다.')
        if self.observation_window and self.door_thickness_mm<self.fastener_nut_thickness_mm+.5:
            raise ValueError('관찰창 도어에는 체결 너트 매립 깊이와 바닥 두께가 필요합니다.')
        if self.front_flange_width_mm<2*self.tool_access_radius_mm+2:
            raise ValueError('전면 플랜지가 체결 공구 접근 공간에 비해 좁습니다.')
        if self.front_flange_width_mm<2*(self.gasket_land_mm+self.gasket_width_mm)+self.fastener_diameter_mm:
            raise ValueError('전면 밀봉 랜드와 체결 구멍의 분리가 부족합니다.')
        for collection in (self.static_ports,self.rod_interfaces,self.specimen_apertures,self.static_rod_seals):
            if len({item.id for item in collection})!=len(collection):
                raise ValueError('챔버 포트와 로드 인터페이스 ID는 종류별로 중복될 수 없습니다.')
        # Prefix + longest generated part suffix must obey the CAD part ID
        # limit; fail before performing any expensive geometry operation.
        for collection,pattern in ((self.static_ports,'port-{}-seal'),(self.rod_interfaces,'rod-{}-bellows'),(self.static_rod_seals,'static-{}-bolt-2')):
            if any(len(self.prefix+'-'+pattern.format(item.id))>40 for item in collection):
                raise ValueError('챔버 접두사와 인터페이스 ID를 합친 부품 ID가 너무 깁니다.')
        if any(size+2*gap>1800 for size,gap in zip(self.protected_swept_bounds.size,self.clearance_mm)):
            raise ValueError('챔버 내부 치수가 현재 CAD 크기 범위를 벗어납니다.')
        return self


@dataclass
class ChamberEnvelope:
    name: str
    kind: str
    shape: cq.Shape
    associated_part_ids: tuple[str,...] = ()
    note: str = ''

    def bounds_mm(self):
        bounds=exact_bounds(self.shape)
        return [bounds.xmin,bounds.xmax,bounds.ymin,bounds.ymax,bounds.zmin,bounds.zmax]


@dataclass
class ChamberBuild:
    requirements: ChamberRequirements
    parts: list[Part]
    assets: dict[str,ShapeAsset]
    interfaces: list[dict]
    envelopes: list[ChamberEnvelope]
    checks: list[str]
    warnings: list[str]
    parasitic_estimate: ParasiticForceEstimate
    collision_pairs: list[dict] = field(default_factory=list)

    def as_design(self):
        return Design(name=self.requirements.name,mode='robot',parts=self.parts,assets=self.assets)

    def append_to(self,design: Design | dict):
        source=design if isinstance(design,Design) else Design.model_validate(design)
        ids={part.id for part in source.parts}
        if any(part.id in ids for part in self.parts) or set(source.assets)&set(self.assets):
            raise ValueError('동일 챔버 ID가 이미 있습니다. 기존 챔버를 명시적으로 교체하거나 다른 접두사를 사용하세요.')
        raw=source.model_dump();raw['parts'] += [part.model_dump() for part in self.parts]
        raw['assets']={**raw.get('assets',{}),**{key:value.model_dump() for key,value in self.assets.items()}}
        return Design.model_validate(raw)

    def report(self):
        return dict(requirements=self.requirements.model_dump(mode='json'),parts=[part.id for part in self.parts],
                    interfaces=self.interfaces,envelopes=[dict(name=e.name,kind=e.kind,bounds_mm=e.bounds_mm(),
                    associated_part_ids=list(e.associated_part_ids),note=e.note) for e in self.envelopes],
                    checks=self.checks,warnings=self.warnings,collision_pairs=self.collision_pairs,
                    parasitic_estimate=self.parasitic_estimate.model_dump(mode='json'),leak_test_verified=False,
                    pressure_rating_verified=False,bellows_life_verified=False,
                    sources=[SEAL_SOURCE,BELLOWS_SOURCE,BELLOWS_GUIDANCE_SOURCE,PRESSURE_SOURCE])


def _box(size,minimum):
    return cq.Solid.makeBox(*size,cq.Vector(*minimum))


def _cylinder(radius,length,base,direction):
    return cq.Solid.makeCylinder(radius,length,cq.Vector(*base),cq.Vector(*direction))


def _ring(radius,bore,length,base,direction):
    return _cylinder(radius,length,base,direction).cut(_cylinder(bore,length,base,direction)).clean()


def _xz_frame(width,height,border,thickness,y):
    return _box((width,thickness,height),(-width/2,y,-height/2)).cut(
        _box((width-2*border,thickness+2,height-2*border),(-width/2+border,y-1,-height/2+border))).clean()


def _interferences(names,shapes,check=lambda:None):
    result=[]
    boxes=[exact_bounds(shape) for shape in shapes]
    for i,a in enumerate(shapes):
        ba=boxes[i]
        for j in range(i+1,len(shapes)):
            check()
            bb=boxes[j]
            if min(ba.xmax,bb.xmax)-max(ba.xmin,bb.xmin)<=1e-7 or min(ba.ymax,bb.ymax)-max(ba.ymin,bb.ymin)<=1e-7 or min(ba.zmax,bb.zmax)-max(ba.zmin,bb.zmin)<=1e-7:
                continue
            volume=a.intersect(shapes[j]).Volume()
            if volume>1e-6:result.append(dict(a=names[i],b=names[j],volume_mm3=volume))
    return result


def build_chamber(requirements: ChamberRequirements | dict, *, check=lambda:None):
    """Build parameter-driven exact solids; perform no UI, file or network I/O."""
    req=ChamberRequirements.model_validate(requirements)
    with KERNEL_LOCK:
        return _build_chamber(req,check)


def _build_chamber(req,check):
    check();w,d,h=[size+2*gap for size,gap in zip(req.protected_swept_bounds.size,req.clearance_mm)]
    center=req.protected_swept_bounds.center;t=req.wall_thickness_mm;f=req.front_flange_width_mm
    gap=req.gasket_thickness_mm*(1-req.gasket_compression_fraction)
    front=-d/2-t;door_back=front-gap;door_front=door_back-req.door_thickness_mm
    parts=[];assets={};shapes=[];interfaces=[];envelopes=[];checks=[]
    warnings=['밀봉·습도 유지·내압·피로 수명은 실제 시험으로 검증되지 않았습니다.',
              '체결 부품은 공간 검사용 단순 형상입니다. 나사 규격·토크·판 변형과 밀봉 재료를 선정하세요.',
              '구동기와 하중 센서를 챔버 외부에 배치하고 전체 조립 간섭을 별도로 검사하세요.']
    def world(point):return tuple(a+b for a,b in zip(point,center))
    def add(suffix,name,shape,color='#F2F2F2',fixed=True):
        check();identifier=f'{req.prefix}-{suffix}'
        if not shape.isValid() or len(shape.Solids())!=1 or shape.Volume()<=1e-7:
            raise ValueError(f'챔버 부품 {name}에서 유효한 단일 솔리드를 만들지 못했습니다.')
        key=identifier+'-brep';assets[key]=encode_shape(shape,name+'.brep')
        parts.append(Part(id=identifier,name=name,geometry=dict(kind='imported',asset_id=key),
            transform=dict(zip(('x','y','z'),center)),color=color,role='structure',fixed=fixed))
        shapes.append(shape.translate(center));return identifier
    def envelope(name,kind,shape,ids=(),note=''):
        envelopes.append(ChamberEnvelope(name,kind,shape.translate(center),tuple(ids),note))
    inner=_box((w,d,h),(-w/2,-d/2,-h/2))
    shell=_box((w+2*t,d+2*t,h+2*t),(-w/2-t,-d/2-t,-h/2-t)).cut(
        _box((w,d+t+1,h),(-w/2,-d/2-t-1,-h/2)))
    flange=_xz_frame(w+2*f,h+2*f,f,t,front)
    shell=shell.fuse(flange).clean()
    door=_box((w+2*f,req.door_thickness_mm,h+2*f),(-w/2-f,door_front,-h/2-f))
    fasteners=[]
    for x in (-w/2-f/2,w/2+f/2):
        for z in (-h/2-f/2,h/2+f/2):
            fasteners.append((x,z,door_front,door_back+t+gap,'door'))
    window_parts=[]
    if req.observation_window:
        ww=req.window_width_mm or w*.6;wh=req.window_height_mm or h*.65
        overlap=req.window_overlap_mm;retainer=req.window_retainer_width_mm
        if ww+2*(overlap+retainer+2)>w+2*f or wh+2*(overlap+retainer+2)>h+2*f:
            raise ValueError('관찰창·고정 프레임·체결 여유가 전면 도어 밖으로 나갑니다.')
        if overlap<req.gasket_land_mm+req.gasket_width_mm+1:
            raise ValueError('관찰창 겹침 폭에 밀봉 랜드가 부족합니다.')
        door=door.cut(_box((ww,req.door_thickness_mm+2,wh),(-ww/2,door_front-1,-wh/2))).clean()
        glass_back=door_front-gap;glass_front=glass_back-req.window_thickness_mm
        glass=_box((ww+2*overlap,req.window_thickness_mm,wh+2*overlap),(-ww/2-overlap,glass_front,-wh/2-overlap))
        seal_outer_w=ww+2*(req.gasket_land_mm+req.gasket_width_mm)
        seal_outer_h=wh+2*(req.gasket_land_mm+req.gasket_width_mm)
        window_seal=_xz_frame(seal_outer_w,seal_outer_h,req.gasket_width_mm,gap,glass_back)
        frame=_xz_frame(ww+2*(overlap+retainer),wh+2*(overlap+retainer),overlap+retainer,
            req.window_retainer_thickness_mm,glass_front-req.window_retainer_thickness_mm)
        for x in (-ww/2-overlap-retainer/2,ww/2+overlap+retainer/2):
            for z in (-wh/2-overlap-retainer/2,wh/2+overlap+retainer/2):
                # Recess window nuts into the door so they never intrude into
                # a small chamber's gasket/flange behind the removable panel.
                fasteners.append((x,z,glass_front-req.window_retainer_thickness_mm,door_back-req.fastener_nut_thickness_mm,'window'))
        window_parts=[('window','관찰창',glass,'#B9DFF6'),('window-seal','관찰창 압축 가스켓',window_seal,'#606A73'),
                      ('window-retainer','관찰창 고정 프레임',frame,'#F2F2F2')]
    hole_r=req.fastener_diameter_mm/2+req.fastener_radial_clearance_mm
    for x,z,head_plane,tail_plane,kind in fasteners:
        tool=_cylinder(hole_r,tail_plane-head_plane+2,(x,head_plane-1,z),(0,1,0))
        door=door.cut(tool)
        if kind=='door':shell=shell.cut(tool)
        else:
            door=door.cut(_cylinder(req.fastener_head_diameter_mm/2+req.fastener_radial_clearance_mm,
                req.fastener_nut_thickness_mm+.1,(x,tail_plane,z),(0,1,0)))
            window_parts[2]=(window_parts[2][0],window_parts[2][1],window_parts[2][2].cut(tool).clean(),window_parts[2][3])
    # Ports and rod openings cut the real case, not a visual-only placeholder.
    port_parts=[]
    for index,port in enumerate(req.static_ports):
        u,v=port.position_uv_mm or ((-w/4 if index%2==0 else w/4),h/4)
        if port.face=='back':base=(u,d/2+t,v);direction=(0,1,0);available=(w,h)
        else:base=((w/2+t)*(1 if port.face=='right' else -1),u,v);direction=(1 if port.face=='right' else -1,0,0);available=(d,h)
        if abs(u)+port.flange_diameter_mm/2+2>available[0]/2 or abs(v)+port.flange_diameter_mm/2+2>available[1]/2:
            raise ValueError('정적 포트의 플랜지가 벽 가장자리·전면 개구부와 겹칩니다.')
        outer=port.bore_diameter_mm/2+port.sleeve_wall_mm
        start=tuple(base[i]-direction[i]*t for i in range(3))
        shell=shell.cut(_cylinder(outer+port.radial_clearance_mm,t+2,tuple(start[i]-direction[i] for i in range(3)),direction))
        sleeve=_ring(outer,port.bore_diameter_mm/2,t+gap+port.flange_thickness_mm,start,direction)
        flange_start=tuple(base[i]+direction[i]*gap for i in range(3))
        fitting=sleeve.fuse(_ring(port.flange_diameter_mm/2,port.bore_diameter_mm/2,port.flange_thickness_mm,flange_start,direction)).clean()
        seal_inner=outer+port.radial_clearance_mm+.5
        seal=_ring(seal_inner+port.seal_width_mm,seal_inner,gap,base,direction)
        port_parts.extend([(f'port-{port.id}',port.name,fitting,'#F2F2F2'),(f'port-{port.id}-seal',port.name+' 가스켓',seal,'#606A73')])
        interfaces.append(dict(id=port.id,kind='static_port',position_mm=world(base),outward_axis=list(direction),
            bore_diameter_mm=port.bore_diameter_mm,seal_width_mm=port.seal_width_mm,
            thread_or_gland_verified=False,mounting_method='unresolved'))
        warnings.append(f'{port.id}: 실제 벌크헤드 피팅·나사·너트 또는 접합 방법이 지정되지 않았습니다. 포트 유지와 밀봉을 제작 전에 확인하세요.')
    static_rod_parts=[]
    for seal in req.static_rod_seals:
        x,y=seal.position_xy_mm;sign=1 if seal.face=='top' else -1;axis=(0,0,sign)
        rod_r=seal.rod_diameter_mm/2;radial=seal.cross_section_mm*(1-seal.radial_compression_fraction)
        # Elliptical section keeps the undeformed circle's section area.
        axial=seal.cross_section_mm**2/radial;gland_depth=axial+seal.axial_gland_extra_mm
        cap_r=seal.cap_outer_diameter_mm/2;outer_r=rod_r+radial
        if gland_depth+.5>t:raise ValueError('정적 O링 홈 깊이가 벽 두께의 밀봉 바닥 여유를 남기지 않습니다.')
        if cap_r<outer_r+8 or abs(x)+cap_r+2>w/2 or abs(y)+cap_r+2>d/2:
            raise ValueError('정적 로드 밀봉 캡의 체결·벽 가장자리 공간이 부족합니다.')
        base=(x,y,sign*(h/2+t));gland_start=(x,y,base[2]-sign*gland_depth)
        shaft_start=(x,y,base[2]-sign*(t+1))
        shell=shell.cut(_cylinder(rod_r+seal.cap_bore_clearance_mm,t+2,shaft_start,axis))
        shell=shell.cut(_cylinder(outer_r,gland_depth+.01,gland_start,axis))
        mean_r=rod_r+radial/2
        profile=cq.Workplane('XZ').moveTo(mean_r,0).ellipse(radial/2,axial/2)
        oring=profile.revolve(360,(0,0),(0,1)).val()
        if sign<0:oring=oring.rotate((0,0,0),(1,0,0),180)
        oring=oring.translate((x,y,base[2]-sign*gland_depth/2))
        cap=_ring(cap_r,rod_r+seal.cap_bore_clearance_mm,seal.cap_thickness_mm,base,axis)
        # Flush simplified screws keep the complete top assembly in a short
        # load-cell gap; holes are blind in the actual chamber wall.
        bolt_r=1.5;head_r=2.5;head_depth=min(1.2,seal.cap_thickness_mm-.3)
        bolt_length=min(4,t-1);bolt_offset=outer_r+4.5
        if bolt_offset+head_r+.5>cap_r:raise ValueError('정적 밀봉 캡의 볼트 위치에 가장자리 여유가 부족합니다.')
        for index,offset in enumerate((-bolt_offset,bolt_offset),1):
            bolt_base=(x+offset,y,base[2]-sign*bolt_length)
            bore=_cylinder(bolt_r+.2,bolt_length+seal.cap_thickness_mm+.01,bolt_base,axis)
            shell=shell.cut(bore);cap=cap.cut(bore)
            head_base=(x+offset,y,base[2]+sign*(seal.cap_thickness_mm-head_depth))
            cap=cap.cut(_cylinder(head_r+.2,head_depth+.01,head_base,axis))
            screw=_cylinder(bolt_r,bolt_length+seal.cap_thickness_mm,bolt_base,axis).fuse(
                _cylinder(head_r,head_depth,head_base,axis)).clean()
            static_rod_parts.append((f'static-{seal.id}-bolt-{index}',f'정적 로드 캡 체결 {index}',screw,'#F2F2F2'))
        static_rod_parts.extend([(f'static-{seal.id}-oring','정적 로드 압축 O링 공간',oring,'#606A73'),
                                 (f'static-{seal.id}-cap','정적 로드 밀봉 캡',cap.clean(),'#F2F2F2')])
        fill=math.pi*seal.cross_section_mm**2/4/(radial*gland_depth)
        interfaces.append(dict(id=seal.id,kind='static_rod_seal',position_mm=world(base),outward_axis=list(axis),
            rod_diameter_mm=seal.rod_diameter_mm,radial_compression_fraction=seal.radial_compression_fraction,
            gland_depth_mm=gland_depth,gland_fill_fraction=fill,cap_thickness_mm=seal.cap_thickness_mm,
            leak_test_verified=False,stationary_rod_required=True,
            cap_part_id=f'{req.prefix}-static-{seal.id}-cap',seal_part_id=f'{req.prefix}-static-{seal.id}-oring'))
        warnings.append(f'{seal.id}: 정적 로드 O링 홈은 치수 초안입니다. 로드가 이 밀봉부에서 왕복하면 안 되며 실제 규격·재료·누설 검증이 필요합니다.')
    for aperture in req.specimen_apertures:
        x,y=aperture.position_xy_mm;sign=1 if aperture.face=='top' else -1;axis=(0,0,sign)
        radius=aperture.specimen_swept_diameter_mm/2+aperture.radial_clearance_mm
        if abs(x)+radius+2>w/2 or abs(y)+radius+2>d/2:
            raise ValueError('시편 통과 개구부가 챔버 벽 가장자리와 겹칩니다.')
        base=(x,y,sign*(h/2+t));start=(x,y,base[2]-sign*(t+1))
        shell=shell.cut(_cylinder(radius,t+2,start,axis))
        interfaces.append(dict(id=aperture.id,kind='unsealed_specimen_aperture',position_mm=world(base),
            outward_axis=list(axis),bore_diameter_mm=2*radius,specimen_part_id=aperture.specimen_part_id,
            seal_status='unresolved',open_leak_path=True))
        warnings.append(f'{aperture.id}: 시편 통과 구멍에 밀봉 부품이 없습니다. 열린 누설 경로이며 습도 시험 준비 완료로 취급하지 않습니다.')
    rod_parts=[]
    for rod in req.rod_interfaces:
        x,y=rod.position_xy_mm;sign=1 if rod.face=='top' else -1;axis=(0,0,sign)
        r0=rod.bellows_inner_diameter_mm/2;r1=rod.bellows_outer_diameter_mm/2
        if abs(x)+r1+2>w/2 or abs(y)+r1+2>d/2:
            raise ValueError('로드·벨로즈 인터페이스가 챔버 벽 가장자리와 겹칩니다.')
        base=(x,y,sign*(h/2+t));rod_r=rod.rod_diameter_mm/2+rod.radial_clearance_mm
        start=tuple(base[i]-axis[i]*(t+1) for i in range(3))
        shell=shell.cut(_cylinder(rod_r,t+2,start,axis))
        fixed_collar=_ring(r0+rod.bellows_wall_mm+2,rod_r,3,base,axis)
        length=rod.installed_length_mm+rod.current_stroke_mm;lo=rod.cuff_length_mm;pitch=(length-2*lo)/rod.convolutions
        profile=[(r0,0),(r0,lo)]
        for n in range(rod.convolutions):
            profile.extend([(r1-rod.bellows_wall_mm,lo+(n+.5)*pitch),(r0,lo+(n+1)*pitch)])
        profile.append((r0,length))
        polygon=[(r+rod.bellows_wall_mm,z) for r,z in profile]+list(reversed(profile))
        bellows=cq.Workplane('XZ').polyline(polygon).close().revolve(360,(0,0),(0,1)).val()
        if sign<0:bellows=bellows.rotate((0,0,0),(1,0,0),180)
        bellows=bellows.translate((x,y,base[2]+sign*3))
        moving_base=(x,y,base[2]+sign*(3+length))
        moving_collar=_ring(r0+rod.bellows_wall_mm+2,rod_r,3,moving_base,axis)
        rod_parts.extend([(f'rod-{rod.id}-fixed','벨로즈 고정 칼라',fixed_collar,'#F2F2F2'),
            (f'rod-{rod.id}-bellows','벨로즈 형상·공간 초안',bellows,'#9CA7B0'),
            (f'rod-{rod.id}-moving','벨로즈 이동 칼라',moving_collar,'#F2F2F2')])
        maximum=3+rod.installed_length_mm+rod.stroke_max_mm+3
        # The fixed collar stays on the outer wall. Compression moves the
        # distal collar toward it; it does not push the bellows into the case.
        motion=_ring(r1+2,rod_r,maximum,base,axis)
        envelope(rod.id+' 벨로즈 전체 운동 공간','bellows_motion',motion,
            (f'{req.prefix}-rod-{rod.id}-bellows',f'{req.prefix}-rod-{rod.id}-moving'),
            '축 방향 운동만 포함합니다. 횡방향·회전·실제 벨로즈 수명은 검증되지 않았습니다.')
        interfaces.append(dict(id=rod.id,kind='moving_rod',position_mm=world(base),outward_axis=list(axis),
            rod_diameter_mm=rod.rod_diameter_mm,stroke_min_mm=rod.stroke_min_mm,stroke_max_mm=rod.stroke_max_mm,
            current_stroke_mm=rod.current_stroke_mm,
            fixed_collar_part_id=f'{req.prefix}-rod-{rod.id}-fixed',moving_collar_part_id=f'{req.prefix}-rod-{rod.id}-moving',
            bellows_part_id=f'{req.prefix}-rod-{rod.id}-bellows',automatic_deformation_supported=False,
            supplier_stroke_verified=rod.supplier_compressed_length_mm is not None and rod.supplier_extended_length_mm is not None))
        warnings.append(f'{rod.id}: 벨로즈는 CAD 공간 초안이며 실제 밀봉 접합부·로드 결합·공급사 수명 확인이 필요합니다. 이동 칼라의 조립 구속과 벨로즈 자세 갱신은 별도로 등록해야 합니다.')
    case_id=add('case','챔버 본체 · 밀봉 플랜지',shell.clean())
    door_id=add('door','분리형 챔버 전면 도어',door.clean())
    outer_w=w+2*(req.gasket_land_mm+req.gasket_width_mm)
    outer_h=h+2*(req.gasket_land_mm+req.gasket_width_mm)
    add('door-seal','전면 압축 가스켓',_xz_frame(outer_w,outer_h,req.gasket_width_mm,gap,door_back),'#606A73')
    for suffix,name,shape,color in [*window_parts,*port_parts,*static_rod_parts,*rod_parts]:
        add(suffix,name,shape,color,fixed=not(suffix.startswith('rod-') and suffix.endswith('-moving')))
    for index,(x,z,head_plane,tail_plane,kind) in enumerate(fasteners,1):
        shaft=_cylinder(req.fastener_diameter_mm/2,tail_plane-head_plane+req.fastener_nut_thickness_mm,
                        (x,head_plane,z),(0,1,0))
        head=_cylinder(req.fastener_head_diameter_mm/2,req.fastener_head_thickness_mm,
                       (x,head_plane-req.fastener_head_thickness_mm,z),(0,1,0))
        identifier=add(f'bolt-{index}',f'{kind} 체결 볼트 {index}',shaft.fuse(head).clean())
        nut=_ring(req.fastener_head_diameter_mm/2,hole_r,req.fastener_nut_thickness_mm,(x,tail_plane,z),(0,1,0))
        nut_id=add(f'nut-{index}',f'{kind} 체결 너트 공간 {index}',nut)
        access=_cylinder(req.tool_access_radius_mm,req.tool_access_length_mm,
            (x,head_plane-req.fastener_head_thickness_mm,z),(0,-1,0))
        envelope(f'체결 공구 {index}','tool_access',access,(identifier,), '전면 접근 경로')
        access=_cylinder(req.tool_access_radius_mm,req.tool_access_length_mm,
            (x,tail_plane+req.fastener_nut_thickness_mm,z),(0,1,0))
        envelope(f'너트 공구 {index}','tool_access',access,(nut_id,), '후면 너트 접근 경로')
    protected=_box(req.protected_swept_bounds.size,
        tuple(-size/2 for size in req.protected_swept_bounds.size))
    envelope('시편·그립 전체 운동 보호 영역','protected_swept_volume',protected)
    envelope('챔버 내부 체적','interior_volume',inner)
    envelope('전면 설치·시편 교체 개구부','service_opening',
        _box((w,req.tool_access_length_mm,h),(-w/2,front-req.tool_access_length_mm,-h/2)),
        (door_id,), '전면 도어·창·가스켓과 체결부를 분리한 뒤 사용합니다.')
    collision_pairs=_interferences([part.id for part in parts],shapes,check)
    if collision_pairs:
        raise ValueError('챔버 부품에 실제 체적 간섭이 있습니다: '+', '.join(row['a']+' ↔ '+row['b'] for row in collision_pairs[:6]))
    protected_world=protected.translate(center)
    occupied=[]
    for part,shape in zip(parts,shapes):
        check()
        if shape.intersect(protected_world).Volume()>1e-6:occupied.append(part.id)
    if occupied:raise ValueError('챔버 부품이 시편·그립 운동 보호 영역에 들어갑니다: '+', '.join(occupied))
    checks.extend(['모든 구성품은 유효한 단일 BREP 솔리드입니다.','구성품 사이 체적 간섭이 없습니다.',
                   '시편·그립 운동 보호 영역과 챔버 부품 사이 체적 간섭이 없습니다.',
                   '전면 도어·관찰창 체결 구멍과 별도 체결 공구 접근 영역이 있습니다.'])
    if not req.static_ports:warnings.append('습도 공급·배출·센서 포트가 지정되지 않았습니다.')
    if not req.rod_interfaces:warnings.append('이동 로드 밀봉 인터페이스가 지정되지 않았습니다.')
    return ChamberBuild(req,parts,assets,interfaces,envelopes,checks,warnings,
        estimate_parasitic_force(req.parasitic_force),collision_pairs)


def chamber_rod_pose(chamber: ChamberBuild, rod_id: str, stroke_mm: float, *, check=lambda:None):
    """Regenerate the geometric bellows proxy at an explicit in-range pose.

    This is a CAD pose rebuild, not a bellows constitutive/finite-element model.
    Stable part IDs let the host replace its generated chamber transactionally.
    """
    raw=chamber.requirements.model_dump()
    rod=next((item for item in raw['rod_interfaces'] if item['id']==rod_id),None)
    if rod is None:raise ValueError('존재하지 않는 챔버 로드 인터페이스입니다.')
    rod['current_stroke_mm']=stroke_mm
    return build_chamber(raw,check=check)


def gauge_only_chamber_requirements(protected_gauge_bounds: ChamberBounds | dict, *,
        specimen_swept_diameter_mm: float, specimen_part_id: str='',prefix='gauge-chamber'):
    """Compact, open-passage gauge chamber for a tightly packed grip fixture.

    This preset does not move existing grips, claim shoulder-contact sealing,
    or infer their stroke. The host must verify the complete real assembly and
    qualify a seal or redesign load-path spacing before humidity testing.
    """
    return ChamberRequirements(protected_swept_bounds=ChamberBounds.model_validate(protected_gauge_bounds),
        prefix=prefix,name='게이지 구간 습도 챔버 · 밀봉 인터페이스 검토',
        clearance_mm=(12,40,.1),wall_thickness_mm=3,door_thickness_mm=4,
        static_ports=[StaticChamberPort(id='humidity-in',name='습도 공급 포트',face='left',position_uv_mm=(0,0)),
                      StaticChamberPort(id='humidity-out',name='습도 배출 포트',face='right',position_uv_mm=(0,0))],
        specimen_apertures=[ChamberSpecimenAperture(id='specimen-top',face='top',specimen_swept_diameter_mm=specimen_swept_diameter_mm,specimen_part_id=specimen_part_id),
                           ChamberSpecimenAperture(id='specimen-bottom',face='bottom',specimen_swept_diameter_mm=specimen_swept_diameter_mm,specimen_part_id=specimen_part_id)])


def inspect_chamber_interfaces(chamber: ChamberBuild, existing: Design | dict, *, drive_part_ids=(),exclude_part_ids=(),check=lambda:None):
    """Check external installation envelopes against an existing real assembly.

    Drives must remain outside the chamber interior. Tool and bellows spaces
    are reported, rather than inserted as physical solids or hidden in groups.
    """
    from .kernel import build
    design=existing if isinstance(existing,Design) else Design.model_validate(existing)
    with KERNEL_LOCK:
        check();shapes=build(design);hits=[];drives=set(drive_part_ids);excluded=set(exclude_part_ids)
        boxes=[exact_bounds(shape) for shape in shapes]
        if not drives<={part.id for part in design.parts}:
            raise ValueError('챔버 검사에서 존재하지 않는 구동 부품 ID를 지정했습니다.')
        if not excluded<={part.id for part in chamber.parts}:
            raise ValueError('검사에서 제외할 수 있는 부품은 교체 중인 챔버 구성품뿐입니다. 기존 조립 부품을 제외할 수 없습니다.')
        for envelope in chamber.envelopes:
            if envelope.kind not in ('interior_volume','bellows_motion','tool_access'):continue
            be=exact_bounds(envelope.shape)
            for part,shape,bb in zip(design.parts,shapes,boxes):
                check()
                if part.id in excluded:continue
                if envelope.kind=='interior_volume' and part.id not in drives:continue
                if any(min(getattr(be,k+'max'),getattr(bb,k+'max'))-max(getattr(be,k+'min'),getattr(bb,k+'min'))<=1e-7 for k in 'xyz'):continue
                volume=envelope.shape.intersect(shape).Volume()
                if volume>1e-6:hits.append(dict(envelope=envelope.name,kind=envelope.kind,part_id=part.id,
                    volume_mm3=volume,action='구동기를 챔버 외부로 이동하세요.' if envelope.kind=='interior_volume' else '설치·운동·공구 접근 공간을 확보하세요.'))
        return hits
