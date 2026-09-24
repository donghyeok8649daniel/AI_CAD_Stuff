"""The entire design language. No scripts, expressions or executable operations."""
from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator, model_serializer


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Dimension = Annotated[float, Field(ge=0.01, le=2000)]
Nonnegative = Annotated[float, Field(ge=0, le=2000)]
Coordinate = Annotated[float, Field(ge=-5000, le=5000)]
Angle = Annotated[float, Field(ge=-360, le=360)]


class Transform(StrictModel):
    x: Coordinate = 0
    y: Coordinate = 0
    z: Coordinate = 0
    rx: Angle = 0
    ry: Angle = 0
    rz: Angle = 0


class RoundSpecimen(StrictModel):
    kind: Literal["round_specimen"] = "round_specimen"
    length: Dimension = 100
    gauge_length: Dimension = 30
    grip_diameter: Dimension = 16
    gauge_diameter: Dimension = 8
    transition_length: Dimension = 15

    @model_validator(mode="after")
    def proportions(self):
        if self.gauge_diameter >= self.grip_diameter:
            raise ValueError("목 직경은 그립 직경보다 작아야 합니다.")
        if self.gauge_length + 2 * self.transition_length >= self.length - 0.02:
            raise ValueError("전체 길이는 평행부 길이 + 전이 길이 × 2보다 커야 합니다.")
        return self


class FlatSpecimen(StrictModel):
    kind: Literal["flat_specimen"] = "flat_specimen"
    length: Dimension = 120
    gauge_length: Dimension = 35
    grip_width: Dimension = 25
    gauge_width: Dimension = 10
    thickness: Dimension = 3
    transition_length: Dimension = 20

    @model_validator(mode="after")
    def proportions(self):
        if self.gauge_width >= self.grip_width:
            raise ValueError("목 폭은 그립 폭보다 작아야 합니다.")
        if self.gauge_length + 2 * self.transition_length >= self.length - 0.02:
            raise ValueError("전체 길이는 평행부 길이 + 전이 길이 × 2보다 커야 합니다.")
        return self


class Wafer(StrictModel):
    kind: Literal["wafer"] = "wafer"
    diameter: Dimension = 100
    thickness: Dimension = 0.525
    flat_depth: Nonnegative = 3

    @model_validator(mode="after")
    def proportions(self):
        if self.flat_depth >= self.diameter / 4:
            raise ValueError("플랫 깊이는 웨이퍼 직경의 1/4보다 작아야 합니다.")
        return self


class Link(StrictModel):
    kind: Literal["link"] = "link"
    length: Dimension = 110
    width: Dimension = 24
    thickness: Dimension = 6
    hole_diameter: Dimension = 8
    hole_spacing: Dimension = 80

    @model_validator(mode="after")
    def proportions(self):
        if self.length <= self.width:
            raise ValueError("링크 길이는 폭보다 커야 합니다.")
        if self.hole_diameter >= self.width - 0.2:
            raise ValueError("구멍 직경은 링크 폭보다 0.2 mm 이상 작아야 합니다.")
        if self.hole_spacing > self.length - self.width:
            raise ValueError("구멍 간격은 길이 − 폭 이하여야 합니다.")
        if self.hole_spacing <= self.hole_diameter + 0.2:
            raise ValueError("두 구멍 사이에 0.2 mm보다 큰 재료 폭이 필요합니다.")
        return self


class Plate(StrictModel):
    kind: Literal["plate"] = "plate"
    length: Dimension = 80
    width: Dimension = 60
    thickness: Dimension = 6
    hole_count: Literal[0, 2, 4] = 4
    hole_diameter: Dimension = 6
    hole_pitch_x: Dimension = 56
    hole_pitch_y: Dimension = 36

    @model_validator(mode="after")
    def proportions(self):
        if not self.hole_count:
            return self
        if self.hole_pitch_x + self.hole_diameter >= self.length - 0.2:
            raise ValueError("X 구멍 간격 + 직경은 판 길이보다 0.2 mm 이상 작아야 합니다.")
        if self.hole_pitch_x <= self.hole_diameter + 0.2:
            raise ValueError("X 방향 구멍이 서로 겹치거나 너무 가깝습니다.")
        if self.hole_count == 4:
            if self.hole_pitch_y + self.hole_diameter >= self.width - 0.2:
                raise ValueError("Y 구멍 간격 + 직경은 판 폭보다 0.2 mm 이상 작아야 합니다.")
            if self.hole_pitch_y <= self.hole_diameter + 0.2:
                raise ValueError("Y 방향 구멍이 서로 겹치거나 너무 가깝습니다.")
        elif self.hole_diameter >= self.width - 0.2:
            raise ValueError("구멍 직경이 판 폭보다 큽니다.")
        return self


class Bracket(StrictModel):
    kind: Literal["bracket"] = "bracket"
    length: Dimension = 60
    width: Dimension = 40
    height: Dimension = 50
    thickness: Dimension = 5
    hole_diameter: Dimension = 6
    hole_inset: Dimension = 12

    @model_validator(mode="after")
    def proportions(self):
        if self.thickness >= min(self.length, self.height) / 2:
            raise ValueError("브래킷 두께는 길이와 높이의 절반보다 작아야 합니다.")
        r = self.hole_diameter / 2
        if r + 0.1 >= self.width / 4:
            raise ValueError("구멍이 브래킷 폭에 비해 너무 큽니다.")
        if self.hole_inset <= r + 0.1:
            raise ValueError("구멍 중심의 가장자리 거리가 너무 작습니다.")
        if self.hole_inset + r + self.thickness >= min(self.length, self.height) - 0.1:
            raise ValueError("구멍이 브래킷 모서리 접합부와 겹칩니다.")
        return self


class Cylinder(StrictModel):
    kind: Literal["cylinder"] = "cylinder"
    diameter: Dimension = 30
    height: Dimension = 20
    bore_diameter: Nonnegative = 0

    @model_validator(mode="after")
    def proportions(self):
        if self.bore_diameter and (self.bore_diameter < 0.01 or self.bore_diameter >= self.diameter - 0.2):
            raise ValueError("내경은 0 또는 외경보다 0.2 mm 이상 작은 값이어야 합니다.")
        return self


class Point2D(StrictModel):
    x: Annotated[float, Field(ge=-1000, le=1000)]
    y: Annotated[float, Field(ge=-1000, le=1000)]


class SketchHole(Point2D):
    diameter: Dimension = 6


class SketchConstraint(StrictModel):
    kind: Literal["fixed", "horizontal", "vertical", "distance", "coincident", "angle"]
    a: int = Field(ge=0, le=31)
    b: int = Field(default=0, ge=0, le=31)
    value: Annotated[float, Field(ge=-360, le=2000)] = 0
    x: Annotated[float, Field(ge=-1000, le=1000)] = 0
    y: Annotated[float, Field(ge=-1000, le=1000)] = 0


class EntityBase(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r"^[a-zA-Z0-9_-]+$")
    construction: bool = False


class SketchLine(EntityBase):
    kind: Literal['line'] = 'line'
    start: Point2D
    end: Point2D


class SketchCircle(EntityBase):
    kind: Literal['circle'] = 'circle'
    center: Point2D
    radius: Dimension


class SketchArc(EntityBase):
    kind: Literal['arc'] = 'arc'
    center: Point2D
    radius: Dimension
    start_angle: Angle = 0
    sweep: Annotated[float,Field(ge=-359.99,le=359.99)] = 90


class SketchEllipse(EntityBase):
    kind: Literal['ellipse'] = 'ellipse'
    center: Point2D
    radius_x: Dimension
    radius_y: Dimension
    rotation: Angle = 0


class SketchSpline(EntityBase):
    kind: Literal['spline'] = 'spline'
    points: list[Point2D] = Field(min_length=3,max_length=24)
    style: Literal['fit','control'] = 'fit'
    closed: bool = False


class SketchPoint(EntityBase):
    kind: Literal['point'] = 'point'
    position: Point2D


class SketchText(EntityBase):
    kind: Literal['text'] = 'text'
    position: Point2D
    text: str = Field(min_length=1,max_length=32)
    size: Dimension = 10
    rotation: Angle = 0
    font: Literal['Arial','Malgun Gothic'] = 'Arial'


SketchEntity=Annotated[Union[SketchLine,SketchCircle,SketchArc,SketchEllipse,SketchSpline,SketchPoint,SketchText],Field(discriminator='kind')]


class EntityConstraint(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal['fixed','horizontal','vertical','coincident','distance','dx','dy','angle','radius','diameter','parallel','perpendicular','equal','concentric','collinear','tangent','normal','midpoint','symmetry','point_on','curvature']
    a: str = Field(min_length=1,max_length=40)
    b: str = Field(default='',max_length=40)
    c: str = Field(default='',max_length=40)
    a_point: Literal['start','end','center','mid','all'] = 'start'
    b_point: Literal['start','end','center','mid','all'] = 'start'
    value: Annotated[float,Field(ge=-4000,le=4000)] = 0
    x: Coordinate = 0
    y: Coordinate = 0
    reference: list[float] = Field(default_factory=list,max_length=64)
    mode: Literal['external','internal'] = 'external'
    expression: str = Field(default='',max_length=240)
    contact: bool = False

    @model_serializer(mode='wrap')
    def compatible_expression(self,handler):
        data=handler(self)
        if not self.expression:data.pop('expression',None)
        if not self.contact:data.pop('contact',None)
        return data


class SketchGroup(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1,max_length=80)
    entity_ids: list[str] = Field(min_length=1,max_length=128)


class Extrusion(StrictModel):
    kind: Literal["extrusion"] = "extrusion"
    thickness: Dimension = 8
    thickness_expression: str = Field(default='',max_length=240)
    direction: Literal[-1,1] = 1
    points: list[Point2D] = Field(default_factory=lambda: [Point2D(x=-35, y=-25), Point2D(x=35, y=-25), Point2D(x=35, y=10), Point2D(x=10, y=25), Point2D(x=-35, y=25)], min_length=3, max_length=32)
    holes: list[SketchHole] = Field(default_factory=list, max_length=16)
    constraints: list[SketchConstraint] = Field(default_factory=list, max_length=48)
    sketch_mode: Literal['polygon','entities'] = 'polygon'
    entities: list[SketchEntity] = Field(default_factory=list,max_length=128)
    entity_constraints: list[EntityConstraint] = Field(default_factory=list,max_length=160)
    profiles: list[Annotated[int,Field(ge=0,le=255)]] = Field(default_factory=list,max_length=64)
    groups: list[SketchGroup] = Field(default_factory=list,max_length=32)
    symmetric: bool = False
    reverse_depth: Nonnegative = 0
    taper: float = Field(default=0,ge=-60,le=60)
    thin_wall: Nonnegative = 0

    @model_serializer(mode='wrap')
    def compatible_groups(self,handler):
        data=handler(self)
        # Old history entries contain entire sketches. Do not inject a new empty
        # field into their exact before/after snapshots.
        if not self.groups:data.pop('groups',None)
        if not self.thickness_expression:data.pop('thickness_expression',None)
        if self.direction==1:data.pop('direction',None)
        for key in ('symmetric','reverse_depth','taper','thin_wall'):
            if not data.get(key):data.pop(key,None)
        return data

    @model_validator(mode="after")
    def simple_polygon(self):
        ids={e.id for e in self.entities}
        if len({g.id for g in self.groups})!=len(self.groups):raise ValueError('스케치 그룹 ID가 중복됩니다.')
        for group in self.groups:
            if len(set(group.entity_ids))!=len(group.entity_ids) or not set(group.entity_ids)<=ids:raise ValueError('그룹이 존재하지 않거나 중복된 스케치 요소를 참조합니다.')
        if self.sketch_mode=='entities':
            from .sketch_engine import solve_entities
            self.entities,_=solve_entities(self.entities,self.entity_constraints)
            return self
        if self.constraints:
            from .constraints import solve_sketch
            solved, _ = solve_sketch(self.points, self.constraints)
            self.points = [Point2D(x=p[0], y=p[1]) for p in solved]
        pts = [(p.x, p.y) for p in self.points]
        edges = list(zip(pts, pts[1:]+pts[:1]))

        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

        def distance(p, a, b):
            dx, dy = b[0]-a[0], b[1]-a[1]
            t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
            return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)

        if len(set(pts)) != len(pts) or any(math.dist(a, b) < .01 for a, b in edges):
            raise ValueError("스케치 점은 중복될 수 없으며 변 길이는 0.01 mm 이상이어야 합니다.")
        if abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in edges))/2 < .01:
            raise ValueError("스케치 면적이 너무 작거나 점이 한 직선 위에 있습니다.")
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i or j == i+1 or (i == 0 and j == len(edges)-1):
                    continue
                if (cross(a, b, c)*cross(a, b, d) < 0 and cross(c, d, a)*cross(c, d, b) < 0) or min(distance(c, a, b), distance(d, a, b), distance(a, c, d), distance(b, c, d)) < .01:
                    raise ValueError("스케치 외곽선이 교차하거나 서로 너무 가깝습니다.")
        for hole in self.holes:
            p = (hole.x, hole.y)
            inside = False
            for a, b in edges:
                if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
                    inside = not inside
            if not inside or min(distance(p, a, b) for a, b in edges) <= hole.diameter/2+.01:
                raise ValueError("스케치 구멍은 외곽선 안에 있어야 하며 가장자리와 겹칠 수 없습니다.")
        for i, h in enumerate(self.holes):
            for other in self.holes[i+1:]:
                if math.hypot(h.x-other.x, h.y-other.y) <= (h.diameter+other.diameter)/2+.01:
                    raise ValueError("스케치 구멍이 서로 겹칩니다.")
        return self


class ModelFrame(StrictModel):
    origin: list[Coordinate] = Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    normal: list[float] = Field(default_factory=lambda:[0,0,1],min_length=3,max_length=3)
    x_direction: list[float] = Field(default_factory=lambda:[1,0,0],min_length=3,max_length=3)

    @model_validator(mode='after')
    def orthogonal(self):
        if abs(sum(x*x for x in self.normal)-1)>1e-5 or abs(sum(x*x for x in self.x_direction)-1)>1e-5 or abs(sum(a*b for a,b in zip(self.normal,self.x_direction)))>1e-5:
            raise ValueError('모델링 기준 축은 서로 수직인 단위 벡터여야 합니다.')
        return self


def circle_profile(radius=5):
    return Extrusion(sketch_mode='entities',entities=[dict(id='profile-circle',kind='circle',center=dict(x=0,y=0),radius=radius)])


class ModelSection(StrictModel):
    sketch: Extrusion = Field(default_factory=circle_profile)
    frame: ModelFrame = Field(default_factory=ModelFrame)
    sketch_id: str = Field(default='',max_length=40)


class SweepPath(StrictModel):
    points: list[list[Coordinate]] = Field(default_factory=lambda:[[0,0,0],[0,0,40],[30,0,65]],min_length=2,max_length=64)
    smooth: bool = True
    sketch: Extrusion | None = None
    frame: ModelFrame = Field(default_factory=ModelFrame)
    sketch_id: str = Field(default='',max_length=40)

    @model_validator(mode='after')
    def valid_points(self):
        if any(len(p)!=3 for p in self.points) or any(math.dist(a,b)<.01 for a,b in zip(self.points,self.points[1:])):
            raise ValueError('경로에는 서로 다른 XYZ 점이 필요합니다.')
        return self


class SweepGeometry(StrictModel):
    kind: Literal['sweep'] = 'sweep'
    profile: ModelSection = Field(default_factory=ModelSection)
    path: SweepPath = Field(default_factory=SweepPath)
    solid: bool = True
    align_profile: bool = True
    frenet: bool = False


class LoftGeometry(StrictModel):
    kind: Literal['loft'] = 'loft'
    sections: list[ModelSection] = Field(default_factory=lambda:[ModelSection(sketch=circle_profile(20)),ModelSection(sketch=circle_profile(10),frame=ModelFrame(origin=[0,0,50]))],min_length=2,max_length=8)
    solid: bool = True
    ruled: bool = False


class RevolveGeometry(StrictModel):
    kind: Literal['revolve'] = 'revolve'
    profile: ModelSection
    axis_start: list[Coordinate] = Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    axis_direction: list[float] = Field(default_factory=lambda:[0,1,0],min_length=3,max_length=3)
    angle: float = Field(default=360,gt=0,le=360)

class ImportedGeometry(StrictModel):
    kind: Literal['imported'] = 'imported'
    asset_id: str = Field(min_length=1,max_length=80)

class SheetMetalGeometry(StrictModel):
    kind: Literal['sheetmetal'] = 'sheetmetal'
    length: Dimension = 60
    width: Dimension = 40
    flange_length: Dimension = 25
    thickness: Dimension = 2
    bend_radius: Dimension = 3
    bend_angle: float = Field(default=90,ge=1,le=175)
    k_factor: float = Field(default=.5,gt=0,le=.5)
    flat: bool = False

class ShapeAsset(StrictModel):
    name: str = Field(max_length=200)
    format: Literal['step','iges','stl','brep']
    data: str = Field(min_length=1,max_length=24_000_000)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

Geometry = Annotated[Union[RoundSpecimen, FlatSpecimen, Wafer, Link, Plate, Bracket, Cylinder, Extrusion, SweepGeometry, LoftGeometry,RevolveGeometry,ImportedGeometry,SheetMetalGeometry], Field(discriminator="kind")]

class FaceReference(StrictModel):
    index: int = Field(ge=0,le=100000)
    surface: str = Field(max_length=40)
    center: list[float] = Field(min_length=3,max_length=3)
    relative_center: list[float] = Field(min_length=3,max_length=3)
    normal: list[float] = Field(default_factory=list,max_length=3)
    area: float = Field(gt=0)

class FeatureState(StrictModel):
    suppressed: bool = False

    @model_serializer(mode='wrap')
    def compatible_state(self,handler):
        data=handler(self)
        if not self.suppressed:data.pop('suppressed',None)
        return data

class SolidFeature(FeatureState):
    id: str = Field(min_length=1,max_length=40)
    name: str = Field(default='솔리드 작업',max_length=80)
    kind: Literal['solid'] = 'solid'
    operation: Literal['shell','draft','boolean','split','mirror','linear_pattern','circular_pattern']
    support_feature: str = Field(default='base',max_length=40)
    faces: list[FaceReference] = Field(default_factory=list,max_length=128)
    size: float = Field(default=2,ge=-2000,le=2000)
    angle: float = Field(default=360,ge=-360,le=360)
    origin: list[Coordinate] = Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)
    direction: list[float] = Field(default_factory=lambda:[0,0,1],min_length=3,max_length=3)
    tool_part_id: str = Field(default='',max_length=40)
    boolean_mode: Literal['union','cut','intersect'] = 'union'
    count: int = Field(default=2,ge=2,le=64)
    count_y: int = Field(default=1,ge=1,le=64)
    spacing: list[Coordinate] = Field(default_factory=lambda:[30,30,0],min_length=3,max_length=3)
    keep_original: bool = True
    keep_side: Literal['all','positive','negative'] = 'all'

    @model_validator(mode='after')
    def valid_direction(self):
        if sum(v*v for v in self.direction)<1e-12:raise ValueError('기준 방향은 0 벡터가 될 수 없습니다.')
        if self.count*self.count_y>256:raise ValueError('한 패턴은 최대 256개입니다.')
        return self


class EdgeReference(StrictModel):
    index: int = Field(ge=0,le=100000)
    length: float = Field(ge=0,le=1000000)
    center: list[Coordinate] = Field(min_length=3,max_length=3)
    curve: str = Field(max_length=40)
    relative_center: list[float] = Field(default_factory=list,max_length=3)
    tangent: list[float] = Field(default_factory=list,max_length=3)

    @model_serializer(mode='wrap')
    def compatible_reference(self,handler):
        data=handler(self)
        for key in ('relative_center','tangent'):
            if not data[key]:data.pop(key,None)
        return data


class EdgeFeature(FeatureState):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(default='3D 필렛',min_length=1,max_length=80)
    kind: Literal['fillet','chamfer'] = 'fillet'
    size: Dimension = 2
    edges: list[EdgeReference] = Field(min_length=1,max_length=64)
    support_feature: str = Field(default='base',max_length=40)
    support_edge_count: int = Field(ge=1,le=100000)


class CylinderReference(StrictModel):
    index: int = Field(ge=0, le=2000)
    face_count: int = Field(ge=1, le=2000)
    diameter: Dimension
    length: Dimension
    frame: ModelFrame
    internal: bool


class ThreadFeature(FeatureState):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    name: str = Field(default='나사산', max_length=80)
    kind: Literal['thread'] = 'thread'
    cylinder: CylinderReference
    diameter: Dimension = 10
    pitch: float = Field(default=1.5, ge=.25, le=12)
    length: Dimension = 10
    offset: Nonnegative = 0
    clearance: float = Field(default=0, ge=0, le=1)
    handedness: Literal['right','left'] = 'right'
    reverse: bool = False
    support_feature: str = Field(default='base', max_length=40)

    @model_validator(mode='after')
    def proportions(self):
        if self.length < self.pitch or self.length/self.pitch > 32:
            raise ValueError('나사 길이는 1~32 피치 범위여야 합니다. 긴 나사는 구간을 줄이세요.')
        if self.offset+self.length > self.cylinder.length+1e-5:
            raise ValueError('시작 간격과 나사 길이의 합이 선택 원통 면 길이를 초과합니다.')
        if self.diameter-1.082532*self.pitch <= .1 or self.clearance > self.pitch/4:
            raise ValueError('지름에 비해 피치 또는 반경 여유가 너무 큽니다.')
        if not self.cylinder.internal and abs(self.diameter-self.cylinder.diameter)>1e-4:
            raise ValueError('수나사 호칭 지름은 선택한 축의 지름과 같아야 합니다. 축 치수를 먼저 바꾸세요.')
        if self.cylinder.internal and not self.diameter-1.082532*self.pitch-.15 <= self.cylinder.diameter < self.diameter-.05:
            raise ValueError('암나사 바탕 구멍 지름이 맞지 않습니다. 권장 바탕 지름 근처로 구멍을 먼저 만드세요.')
        return self


class SketchFeature(FeatureState):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(default="면 스케치", min_length=1, max_length=80)
    face: int = Field(ge=0, le=100000)
    support_face_count: int = Field(default=0, ge=0, le=100000)
    support_feature: str = Field(default="", max_length=40)
    origin: list[Coordinate] = Field(default_factory=list, max_length=3)
    x_direction: list[Annotated[float, Field(ge=-1, le=1)]] = Field(default_factory=list, max_length=3)
    normal: list[Annotated[float, Field(ge=-1, le=1)]] = Field(min_length=3, max_length=3)
    operation: Literal["add", "cut"] = "add"
    sketch: Extrusion
    sketch_id: str = Field(default='',max_length=40)
    reference: FaceReference | None = None
    through_all: bool = False
    end_face: FaceReference | None = None
    hole_finish: Literal['plain','counterbore','countersink'] = 'plain'
    head_diameter: Dimension = 10
    head_depth: Dimension = 3
    head_angle: float = Field(default=90,ge=10,le=170)

    @model_serializer(mode='wrap')
    def compatible_link(self,handler):
        data=handler(self)
        if not self.sketch_id:data.pop('sketch_id',None)
        if not self.reference:data.pop('reference',None)
        if not self.suppressed:data.pop('suppressed',None)
        if not self.through_all:data.pop('through_all',None)
        if self.end_face is None:data.pop('end_face',None)
        if self.hole_finish=='plain':
            for key in ('hole_finish','head_diameter','head_depth','head_angle'):data.pop(key,None)
        return data


class AssemblyMate(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["rigid", "revolute", "slider", "cylindrical",'pin_slot','planar','ball'] = "rigid"
    parent: str = Field(min_length=1, max_length=40)
    child: str = Field(min_length=1, max_length=40)
    parent_anchor: str = Field(default="origin", max_length=40)
    child_anchor: str = Field(default="origin", max_length=40)
    x: Coordinate = 0
    y: Coordinate = 0
    z: Coordinate = 0
    rx: Angle = 0
    ry: Angle = 0
    rz: Angle = 0
    limits: dict[Literal['x','y','z','rx','ry','rz'],list[float]] = Field(default_factory=dict,max_length=3)

    @model_validator(mode='after')
    def valid_limits(self):
        from .assembly_motion import JOINT_AXES
        for key,bounds in self.limits.items():
            maximum=360 if key.startswith('r') else 5000
            if key not in JOINT_AXES[self.kind] or len(bounds)!=2 or not -maximum<=bounds[0]<=bounds[1]<=maximum:raise ValueError('관절 운동 한계의 축 또는 최솟값/최댓값을 확인하세요.')
        return self

    @model_serializer(mode='wrap')
    def compatible_limits(self,handler):
        data=handler(self)
        if not self.limits:data.pop('limits',None)
        return data

class MotionLink(StrictModel):
    id: str = Field(min_length=1,max_length=40)
    driver: str = Field(min_length=1,max_length=40)
    driver_axis: Literal['x','y','z','rx','ry','rz'] = 'rz'
    driven: str = Field(min_length=1,max_length=40)
    driven_axis: Literal['x','y','z','rx','ry','rz'] = 'rz'
    ratio: float = Field(default=1,ge=-10000,le=10000)
    offset: Coordinate = 0


class JointAnchorFrame(StrictModel):
    face: int = Field(ge=0, le=100000)
    face_count: int = Field(ge=1, le=100000)
    support_feature: str = Field(default='base', max_length=40)
    origin: list[Coordinate] = Field(min_length=3, max_length=3)
    normal: list[float] = Field(min_length=3, max_length=3)
    x_direction: list[float] = Field(min_length=3, max_length=3)
    reference: FaceReference | None = None

    @model_serializer(mode='wrap')
    def compatible_reference(self,handler):
        data=handler(self)
        if self.reference is None:data.pop('reference',None)
        return data

    @model_validator(mode='after')
    def orthogonal_frame(self):
        if abs(sum(v*v for v in self.normal)-1)>1e-5 or abs(sum(v*v for v in self.x_direction)-1)>1e-5 or abs(sum(a*b for a,b in zip(self.normal,self.x_direction)))>1e-5:
            raise ValueError('조인트 기준 축은 서로 수직인 단위 벡터여야 합니다.')
        return self


class JointFrames(StrictModel):
    mate_id: str = Field(min_length=1, max_length=40)
    parent: JointAnchorFrame
    child: JointAnchorFrame
    flipped: bool = True


class Material(StrictModel):
    name: str = Field(default='사용자 재질',min_length=1,max_length=80)
    density: float = Field(default=2700,gt=0,le=30000)
    youngs_modulus: float = Field(default=69000,gt=0,le=1000000)
    poisson: float = Field(default=.33,gt=-1,lt=.5)


class Part(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    geometry: Geometry
    transform: Transform = Field(default_factory=Transform)
    color: str = Field(default="#70aebf", pattern=r"^#[0-9a-fA-F]{6}$")
    fixed: bool = False
    features: list[Union[SketchFeature,EdgeFeature,ThreadFeature,SolidFeature]] = Field(default_factory=list, max_length=128)
    profile_sketch_id: str = Field(default='',max_length=40)
    source_part_id: str = Field(default='',max_length=40)
    material: Material | None = None

    @model_serializer(mode='wrap')
    def compatible_profile(self,handler):
        data=handler(self)
        if not self.profile_sketch_id:data.pop('profile_sketch_id',None)
        if not self.source_part_id:data.pop('source_part_id',None)
        if self.material is None:data.pop('material',None)
        return data


class SketchSupportFace(StrictModel):
    index: int = Field(ge=0, le=100000)
    planar: Literal[True] = True
    normal: list[float] = Field(min_length=3, max_length=3)
    origin: list[Coordinate] = Field(min_length=3, max_length=3)
    x_direction: list[float] = Field(min_length=3, max_length=3)
    outline: list[list[list[float]]] = Field(default_factory=list)
    face_count: int = Field(ge=1, le=100000)
    projected_entities: list[SketchEntity] = Field(default_factory=list)
    projection_unsupported: int = Field(default=0, ge=0)
    reference: FaceReference | None = None

    @model_serializer(mode='wrap')
    def compatible_reference(self,handler):
        data=handler(self)
        if not self.reference:data.pop('reference',None)
        return data


class WorkPlane(StrictModel):
    plane: Literal['XY', 'XZ', 'YZ'] = 'XY'
    offset: Coordinate = 0
    placement: Transform = Field(default_factory=Transform)


class SavedSketchContext(StrictModel):
    plane: Literal['XY', 'XZ', 'YZ'] = 'XY'
    title: str = Field(default='스케치', max_length=160)
    part_id: str = Field(default='', max_length=40)
    support_feature: str = Field(default='', max_length=40)
    operation: Literal['add', 'cut'] = 'add'
    face: SketchSupportFace | None = None
    work_plane: WorkPlane | None = None

    @model_validator(mode='after')
    def independent_plane(self):
        if self.work_plane and (self.face or self.part_id or self.support_feature):
            raise ValueError('사용자 작업 평면과 부품 면 참조를 동시에 사용할 수 없습니다.')
        return self

    @model_serializer(mode='wrap')
    def compatible_plane(self,handler):
        data=handler(self)
        if self.work_plane is None:data.pop('work_plane',None)
        return data


class SavedSketch(StrictModel):
    """A sketch need not enclose a face or produce a solid to be saved."""
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(default="스케치", min_length=1, max_length=80)
    geometry: Extrusion
    context: SavedSketchContext = Field(default_factory=SavedSketchContext)


class LoopClosure(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(default='폐루프 연결',max_length=80)
    parent: str = Field(min_length=1,max_length=40)
    child: str = Field(min_length=1,max_length=40)
    parent_anchor: str = Field(default='origin',max_length=40)
    child_anchor: str = Field(default='origin',max_length=40)
    passive_joints: list[str] = Field(min_length=1,max_length=6)
    planar: bool = True
    offset: list[Coordinate] = Field(default_factory=lambda:[0,0,0],min_length=3,max_length=3)


class DesignStudy(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    kind: Literal['robot','tensile','drawing','specimen-rule','fit']
    name: str = Field(min_length=1,max_length=100)
    settings: dict[str,JsonValue] = Field(default_factory=dict,max_length=40)


class DimensionBinding(StrictModel):
    path: list[str|int] = Field(min_length=3,max_length=20)
    expression: str = Field(min_length=1,max_length=240)


class PartGroup(StrictModel):
    """Selection folders, independent of geometric and assembly constraints."""
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1,max_length=80)
    part_ids: list[str] = Field(min_length=1,max_length=256)


class Design(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="새 설계", min_length=1, max_length=100)
    mode: Literal["specimen", "robot"] = "specimen"
    units: Literal["mm"] = "mm"
    parts: list[Part] = Field(default_factory=list, max_length=256)
    mates: list[AssemblyMate] = Field(default_factory=list, max_length=255)
    sketches: list[SavedSketch] = Field(default_factory=list, max_length=64)
    joint_frames: list[JointFrames] = Field(default_factory=list, max_length=255)
    loops: list[LoopClosure] = Field(default_factory=list,max_length=4)
    studies: list[DesignStudy] = Field(default_factory=list,max_length=32)
    parameters: dict[str,str] = Field(default_factory=dict,max_length=64)
    dimension_bindings: list[DimensionBinding] = Field(default_factory=list,max_length=256)
    assets: dict[str,ShapeAsset] = Field(default_factory=dict,max_length=256)
    motion_links: list[MotionLink] = Field(default_factory=list,max_length=128)
    configurations: dict[str,dict[str,str]] = Field(default_factory=dict,max_length=64)
    part_groups: list[PartGroup] = Field(default_factory=list,max_length=256)

    @model_validator(mode='before')
    @classmethod
    def evaluate_dimensions(cls,data):
        from .parameters import evaluate_design
        from .associativity import resolve_profiles
        return resolve_profiles(evaluate_design(data))

    @model_serializer(mode='wrap')
    def compatible_parameters(self,handler):
        data=handler(self)
        for key in ('parameters','dimension_bindings','assets','motion_links','configurations','part_groups'):
            if not data.get(key):data.pop(key,None)
        return data

    @model_validator(mode="after")
    def unique_ids(self):
        from .parameters import parameter_values
        for name,values in self.configurations.items():
            if not name.strip() or len(name)>80:raise ValueError('설계 구성 이름은 1~80자로 입력하세요.')
            if not set(values)<=set(self.parameters):raise ValueError('설계 구성표가 삭제된 변수를 참조합니다.')
            parameter_values({**self.parameters,**values})
        if len({s.id for s in self.studies})!=len(self.studies):raise ValueError('해석 / 도면 ID가 중복됩니다.')
        if len({s.id for s in self.sketches}) != len(self.sketches):
            raise ValueError("스케치 ID는 중복될 수 없습니다.")
        ids = [p.id for p in self.parts]
        if len(ids) != len(set(ids)):
            raise ValueError("부품 ID는 중복될 수 없습니다.")
        grouped=set();group_ids=set()
        for group in self.part_groups:
            if group.id in group_ids or len(set(group.part_ids))!=len(group.part_ids) or not set(group.part_ids)<=set(ids) or grouped.intersection(group.part_ids):
                raise ValueError('그룹은 실제 부품을 중복 없이 포함해야 하며 부품은 한 그룹에만 속할 수 있습니다.')
            group_ids.add(group.id);grouped.update(group.part_ids)
        if len({m.id for m in self.mates}) != len(self.mates):
            raise ValueError("조립 구속 ID는 중복될 수 없습니다.")
        if len({f.mate_id for f in self.joint_frames}) != len(self.joint_frames) or any(f.mate_id not in {m.id for m in self.mates} for f in self.joint_frames):
            raise ValueError('면 조인트 기준은 실제 조립 구속 하나에 한 번만 연결해야 합니다.')
        for part in self.parts:
            if len({f.id for f in part.features}) != len(part.features):
                raise ValueError("피처 ID는 중복될 수 없습니다.")
        from .constraints import solve_assembly
        solve_assembly(self)
        return self


class HistoryChange(StrictModel):
    path: list[str | int] = Field(min_length=1, max_length=24)
    operation: Literal["set", "remove"] = "set"
    existed: bool = True
    before: JsonValue = None
    after: JsonValue = None


class HistoryEntry(StrictModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-zA-Z0-9_-]+$")
    parent: str | None = Field(default=None, max_length=60)
    label: str = Field(min_length=1, max_length=160)
    created_at: str = Field(min_length=1, max_length=40)
    source: Literal["manual", "local", "openai", "import"] = "manual"
    changes: list[HistoryChange] = Field(default_factory=list)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class HistoryJournal(StrictModel):
    version: Literal[1] = 1
    base: Design
    entries: list[HistoryEntry] = Field(min_length=1)
    cursor: str = Field(max_length=60)
    head: str = Field(max_length=60)


class Project(StrictModel):
    format: Literal["prompt-cad-project"] = "prompt-cad-project"
    version: Literal[1, 2] = 2
    design: Design
    prompt: str = Field(default="", max_length=4000)
    history: HistoryJournal | None = None

    @model_validator(mode="after")
    def consistent_history(self):
        if self.history:
            from .history import validate_history
            validate_history(self.history, self.design)
        return self


class DraftRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=4000)
    mode: Literal["specimen", "robot"] = "specimen"
    provider: Literal["local", "openai"] = "local"
    current: Design | None = None
    selected_part: str | None = Field(default=None, max_length=40)
    selected_feature: str | None = Field(default=None, max_length=40)
    selected_joint: str | None = Field(default=None, max_length=40)


GEOMETRY_TYPES = {c.model_fields["kind"].default: c for c in (RoundSpecimen, FlatSpecimen, Wafer, Link, Plate, Bracket, Cylinder, Extrusion, SweepGeometry, LoftGeometry)}
