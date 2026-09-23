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
    kind: Literal['fixed','horizontal','vertical','coincident','distance','dx','dy','angle','radius','diameter','parallel','perpendicular','equal','concentric','collinear','tangent','midpoint','symmetry','point_on','curvature']
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


class SketchGroup(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1,max_length=80)
    entity_ids: list[str] = Field(min_length=1,max_length=128)


class Extrusion(StrictModel):
    kind: Literal["extrusion"] = "extrusion"
    thickness: Dimension = 8
    points: list[Point2D] = Field(default_factory=lambda: [Point2D(x=-35, y=-25), Point2D(x=35, y=-25), Point2D(x=35, y=10), Point2D(x=10, y=25), Point2D(x=-35, y=25)], min_length=3, max_length=32)
    holes: list[SketchHole] = Field(default_factory=list, max_length=16)
    constraints: list[SketchConstraint] = Field(default_factory=list, max_length=48)
    sketch_mode: Literal['polygon','entities'] = 'polygon'
    entities: list[SketchEntity] = Field(default_factory=list,max_length=128)
    entity_constraints: list[EntityConstraint] = Field(default_factory=list,max_length=160)
    profiles: list[Annotated[int,Field(ge=0,le=255)]] = Field(default_factory=list,max_length=64)
    groups: list[SketchGroup] = Field(default_factory=list,max_length=32)

    @model_serializer(mode='wrap')
    def compatible_groups(self,handler):
        data=handler(self)
        # Old history entries contain entire sketches. Do not inject a new empty
        # field into their exact before/after snapshots.
        if not self.groups:data.pop('groups',None)
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


Geometry = Annotated[Union[RoundSpecimen, FlatSpecimen, Wafer, Link, Plate, Bracket, Cylinder, Extrusion, SweepGeometry, LoftGeometry], Field(discriminator="kind")]


class EdgeReference(StrictModel):
    index: int = Field(ge=0,le=2000)
    length: float = Field(ge=0,le=1000000)
    center: list[Coordinate] = Field(min_length=3,max_length=3)
    curve: str = Field(max_length=40)


class EdgeFeature(StrictModel):
    id: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(default='3D 필렛',min_length=1,max_length=80)
    kind: Literal['fillet','chamfer'] = 'fillet'
    size: Dimension = 2
    edges: list[EdgeReference] = Field(min_length=1,max_length=64)
    support_feature: str = Field(default='base',max_length=40)
    support_edge_count: int = Field(ge=1,le=2000)


class SketchFeature(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(default="면 스케치", min_length=1, max_length=80)
    face: int = Field(ge=0, le=500)
    support_face_count: int = Field(default=0, ge=0, le=500)
    support_feature: str = Field(default="", max_length=40)
    origin: list[Coordinate] = Field(default_factory=list, max_length=3)
    x_direction: list[Annotated[float, Field(ge=-1, le=1)]] = Field(default_factory=list, max_length=3)
    normal: list[Annotated[float, Field(ge=-1, le=1)]] = Field(min_length=3, max_length=3)
    operation: Literal["add", "cut"] = "add"
    sketch: Extrusion


class AssemblyMate(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["rigid", "revolute", "slider", "cylindrical"] = "rigid"
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


class JointAnchorFrame(StrictModel):
    face: int = Field(ge=0, le=500)
    face_count: int = Field(ge=1, le=500)
    support_feature: str = Field(default='base', max_length=40)
    origin: list[Coordinate] = Field(min_length=3, max_length=3)
    normal: list[float] = Field(min_length=3, max_length=3)
    x_direction: list[float] = Field(min_length=3, max_length=3)

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


class Part(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    geometry: Geometry
    transform: Transform = Field(default_factory=Transform)
    color: str = Field(default="#70aebf", pattern=r"^#[0-9a-fA-F]{6}$")
    fixed: bool = False
    features: list[Union[SketchFeature,EdgeFeature]] = Field(default_factory=list, max_length=16)


class SketchSupportFace(StrictModel):
    index: int = Field(ge=0, le=500)
    planar: Literal[True] = True
    normal: list[float] = Field(min_length=3, max_length=3)
    origin: list[Coordinate] = Field(min_length=3, max_length=3)
    x_direction: list[float] = Field(min_length=3, max_length=3)
    outline: list[list[list[float]]] = Field(default_factory=list)
    face_count: int = Field(ge=1, le=500)
    projected_entities: list[SketchEntity] = Field(default_factory=list)
    projection_unsupported: int = Field(default=0, ge=0)


class SavedSketchContext(StrictModel):
    plane: Literal['XY', 'XZ', 'YZ'] = 'XY'
    title: str = Field(default='스케치', max_length=160)
    part_id: str = Field(default='', max_length=40)
    support_feature: str = Field(default='', max_length=40)
    operation: Literal['add', 'cut'] = 'add'
    face: SketchSupportFace | None = None


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


class Design(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="새 설계", min_length=1, max_length=100)
    mode: Literal["specimen", "robot"] = "specimen"
    units: Literal["mm"] = "mm"
    parts: list[Part] = Field(default_factory=list, max_length=12)
    mates: list[AssemblyMate] = Field(default_factory=list, max_length=11)
    sketches: list[SavedSketch] = Field(default_factory=list, max_length=64)
    joint_frames: list[JointFrames] = Field(default_factory=list, max_length=11)
    loops: list[LoopClosure] = Field(default_factory=list,max_length=4)
    studies: list[DesignStudy] = Field(default_factory=list,max_length=32)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.studies})!=len(self.studies):raise ValueError('해석 / 도면 ID가 중복됩니다.')
        if len({s.id for s in self.sketches}) != len(self.sketches):
            raise ValueError("스케치 ID는 중복될 수 없습니다.")
        ids = [p.id for p in self.parts]
        if len(ids) != len(set(ids)):
            raise ValueError("부품 ID는 중복될 수 없습니다.")
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


GEOMETRY_TYPES = {c.model_fields["kind"].default: c for c in (RoundSpecimen, FlatSpecimen, Wafer, Link, Plate, Bracket, Cylinder, Extrusion, SweepGeometry, LoftGeometry)}
