"""Declarative, bounded two/four-layer PCB editing and geometric design aids.

The layout rules are geometric design aids, never manufacturing acceptance.
No executable plugins, imported scripts, inferred prices, or device models.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import csv
import hashlib
import io
import json
import math
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer
from . import pcb_geometry as geometry

Id = Annotated[str, Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')]
PinId = Annotated[str, Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')]
Coord = Annotated[float, Field(ge=-1000, le=1000)]
Layer = Literal['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
COPPER_LAYERS = ('F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu')


class PCBModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, revalidate_instances='always')


def source_url(value):
    if value:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError('출처는 HTTPS 주소로 입력하세요. / Source must be an HTTPS URL.')
    return value


class PCBQuote(PCBModel):
    status: Literal['unknown', 'reference', 'quoted'] = 'unknown'
    unit_price: Decimal | None = Field(default=None, ge=0, le=1000000000, decimal_places=6)
    currency: str = Field(default='KRW', pattern=r'^[A-Z]{3}$')
    as_of: date | None = None
    supplier: str = Field(default='', max_length=120)
    source_url: str = Field(default='', max_length=500)
    minimum_quantity: int = Field(default=1, ge=1, le=1000000)
    pack_quantity: int = Field(default=1, ge=1, le=1000000)
    note: str = Field(default='', max_length=1000)

    @model_serializer(mode='wrap')
    def json_safe_money_date(self,handler):
        # CAD journals/current snapshots use model_dump() in Python mode and
        # later hash with stdlib JSON. Keep typed money/date internally while
        # emitting JSON-safe exact decimal strings and ISO dates in every mode.
        data=handler(self)
        data['unit_price']=str(self.unit_price) if self.unit_price is not None else None
        data['as_of']=self.as_of.isoformat() if self.as_of is not None else None
        return data

    @model_validator(mode='after')
    def provenance(self):
        source_url(self.source_url)
        if self.status == 'unknown' and self.unit_price is not None:
            raise ValueError('미확인 가격은 금액 없이 저장하세요. / Unknown price has no amount.')
        if self.status != 'unknown' and (self.unit_price is None or self.as_of is None or not self.supplier or not self.source_url):
            raise ValueError('가격에는 금액·통화·기준일·판매처·출처가 필요합니다. / Price provenance required.')
        return self


class PCBPin(PCBModel):
    number: PinId
    name: str = Field(default='', max_length=80)
    net: Id | None = None
    x_mm: Coord = 0
    y_mm: Coord = 0
    diameter_mm: float = Field(default=1, ge=.05, le=20)
    shape: Literal['circle', 'rect', 'oval', 'roundrect'] = 'circle'
    size_x_mm: float | None = Field(default=None, ge=.05, le=20)
    size_y_mm: float | None = Field(default=None, ge=.05, le=20)
    rotation_deg: float = Field(default=0, ge=-360, le=360)
    roundrect_rratio: float = Field(default=.25, ge=0, le=.5)
    drill_mm: float = Field(default=0, ge=0, le=20, description='Circular hole only; oval/slot drills are unsupported and must be rejected.')
    layers: list[Layer] = Field(default_factory=lambda: ['F.Cu'], min_length=1, max_length=4)

    @model_serializer(mode='wrap')
    def legacy_circle_snapshot(self, handler):
        data = handler(self)
        if self.shape == 'circle' and self.size_x_mm is None and self.size_y_mm is None and self.rotation_deg == 0 and self.drill_mm == 0 and self.roundrect_rratio == .25:
            for key in ('shape', 'size_x_mm', 'size_y_mm', 'rotation_deg', 'roundrect_rratio', 'drill_mm'):
                data.pop(key, None)
        return data

    @model_validator(mode='after')
    def layer_set(self):
        if len(set(self.layers)) != len(self.layers):
            raise ValueError('패드 층은 중복 없이 지정하세요. / Duplicate pad layers.')
        if (self.size_x_mm is None) != (self.size_y_mm is None) or (self.shape != 'circle' and self.size_x_mm is None):
            raise ValueError('패드의 X/Y 크기를 함께 지정하세요. / Noncircular pads require both sizes.')
        sx, sy = self.size_x_mm or self.diameter_mm, self.size_y_mm or self.diameter_mm
        if self.shape == 'circle' and abs(sx-sy) > 1e-9:
            raise ValueError('원형 패드의 X/Y 크기는 같아야 합니다. / Circle pad sizes must be equal.')
        if self.drill_mm and self.drill_mm >= min(sx, sy):
            raise ValueError('원형 홀은 패드보다 작아야 합니다. / Circular drill must be smaller than the pad.')
        return self


class PCBDeviceModel(PCBModel):
    kind: Literal['none', 'resistor', 'capacitor', 'voltage_source', 'unsupported'] = 'unsupported'
    pin_a: PinId | None = None
    pin_b: PinId | None = None
    resistance_ohm: float | None = Field(default=None, gt=0, le=1e9)
    capacitance_f: float | None = Field(default=None, gt=0, le=1)
    dc_voltage_v: float | None = Field(default=None, ge=-1000, le=1000)
    ac_voltage_v: float | None = Field(default=None, ge=0, le=1000)
    ac_phase_deg: float = Field(default=0, ge=-360, le=360)

    @model_validator(mode='after')
    def model_values(self):
        expected = {'resistor': 'resistance_ohm', 'capacitor': 'capacitance_f', 'voltage_source': 'dc_voltage_v'}
        if self.kind in expected:
            if not self.pin_a or not self.pin_b or self.pin_a == self.pin_b or getattr(self, expected[self.kind]) is None:
                raise ValueError('모델의 서로 다른 두 핀과 수치를 지정하세요. / Model pins and value required.')
        for attr in ('resistance_ohm', 'capacitance_f', 'dc_voltage_v', 'ac_voltage_v'):
            if getattr(self, attr) is not None and attr not in ([expected.get(self.kind)] + (['ac_voltage_v'] if self.kind == 'voltage_source' else [])):
                raise ValueError('부품 종류와 모델 수치가 다릅니다. / Model value does not match its kind.')
        return self


class PCBComponent(PCBModel):
    ref: Id
    value: str = Field(default='', max_length=120)
    mpn: str = Field(default='', max_length=120)
    footprint: str = Field(default='declared-round-pads', max_length=160)
    footprint_basis: Literal['declared', 'datasheet_reference'] = 'declared'
    source_url: str = Field(default='', max_length=500)
    x_mm: Coord = 10
    y_mm: Coord = 10
    rotation_deg: float = Field(default=0, ge=-360, le=360)
    body_width_mm: float = Field(default=4, ge=.1, le=500)
    body_height_mm: float = Field(default=2, ge=.1, le=500)
    pins: list[PCBPin] = Field(default_factory=list, min_length=1, max_length=144)
    model: PCBDeviceModel = Field(default_factory=PCBDeviceModel)
    quote: PCBQuote = Field(default_factory=PCBQuote)
    fitted: bool = True

    @model_validator(mode='after')
    def pin_map(self):
        source_url(self.source_url)
        numbers = {p.number for p in self.pins}
        if len(numbers) != len(self.pins):
            raise ValueError('부품 핀 번호가 중복됩니다. / Duplicate pin number.')
        if self.footprint_basis == 'datasheet_reference' and not self.source_url:
            raise ValueError('데이터시트 기반 패드에는 출처가 필요합니다. / Footprint source required.')
        if self.model.kind in ('resistor', 'capacitor', 'voltage_source') and not {self.model.pin_a, self.model.pin_b} <= numbers:
            raise ValueError('회로 모델이 없는 핀을 참조합니다. / Unknown model pin.')
        return self


class PCBPoint(PCBModel):
    x_mm: Coord
    y_mm: Coord


class PCBPolygon(PCBModel):
    points: list[PCBPoint] = Field(min_length=3, max_length=8192)
    holes: list[list[PCBPoint]] = Field(default_factory=list, max_length=128)

    @model_validator(mode='after')
    def polygon_rings(self):
        geometry.validate_polygon(self.points, self.holes, allow_fractured=True)
        return self


class PCBVia(PCBModel):
    id: Id
    net: Id
    x_mm: Coord
    y_mm: Coord
    diameter_mm: float = Field(default=.6, ge=.05, le=20)
    drill_mm: float = Field(default=.3, gt=0, le=20)
    layers: list[Layer] = Field(default_factory=lambda: ['F.Cu', 'B.Cu'], min_length=2, max_length=4)

    @model_validator(mode='after')
    def dimensions_and_span(self):
        if self.drill_mm >= self.diameter_mm:
            raise ValueError('비아 홀은 구리 지름보다 작아야 합니다. / Via drill must be smaller than its diameter.')
        positions = [COPPER_LAYERS.index(layer) for layer in self.layers]
        if positions != sorted(set(positions)):
            raise ValueError('비아 층은 앞면에서 뒷면 순서로 지정하세요. / Via layers must be unique and ordered.')
        return self


class PCBZone(PCBModel):
    id: Id
    net: Id
    layer: Layer
    outline: list[PCBPoint] = Field(min_length=3, max_length=4096)
    holes: list[list[PCBPoint]] = Field(default_factory=list, max_length=128)
    filled_polygons: list[PCBPolygon] = Field(default_factory=list, max_length=512)

    @model_validator(mode='after')
    def declared_boundary(self):
        geometry.validate_polygon(self.outline, self.holes)
        # Filled polygons are stored independently. Their correspondence with
        # the declared boundary is a geometric inspection, never an inferred fill.
        return self


class PCBTrack(PCBModel):
    id: Id
    net: Id
    layer: Layer = 'F.Cu'
    width_mm: float = Field(default=.25, ge=.05, le=10)
    points: list[PCBPoint] = Field(min_length=2, max_length=32)

    @model_validator(mode='after')
    def nonzero(self):
        if any(a == b for a, b in zip(self.points, self.points[1:])):
            raise ValueError('배선의 연속 점은 달라야 합니다. / Zero length track segment.')
        return self


class PCBSimulationInput(PCBModel):
    analysis: Literal['dc', 'ac'] = 'dc'
    frequency_hz: float = Field(default=1000, gt=0, le=1e9)


class PCBBudget(PCBModel):
    board_quantity: int = Field(default=1, ge=1, le=100000)
    currency: str = Field(default='KRW', pattern=r'^[A-Z]{3}$')
    limit: Decimal | None = Field(default=None, ge=0, le=1000000000000, decimal_places=6)

    @model_serializer(mode='wrap')
    def json_safe_money(self,handler):
        data=handler(self);data['limit']=str(self.limit) if self.limit is not None else None;return data


class PCBProject(PCBModel):
    schema_version: Literal[1] = 1
    name: str = Field(default='PCB 설계', min_length=1, max_length=100)
    width_mm: float = Field(default=60, ge=2, le=500)
    height_mm: float = Field(default=40, ge=2, le=500)
    thickness_mm: float = Field(default=1.6, ge=.1, le=10)
    layer_count: Literal[2, 4] = 2
    clearance_mm: float = Field(default=.2, ge=.05, le=5)
    edge_clearance_mm: float = Field(default=.5, ge=0, le=10)
    nets: list[Id] = Field(default_factory=lambda: ['GND'], min_length=1, max_length=192)
    net_labels: dict[Id, Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=dict, max_length=192)
    components: list[PCBComponent] = Field(default_factory=list, max_length=64)
    tracks: list[PCBTrack] = Field(default_factory=list, max_length=1024)
    vias: list[PCBVia] = Field(default_factory=list, max_length=512)
    zones: list[PCBZone] = Field(default_factory=list, max_length=64)
    simulation: PCBSimulationInput = Field(default_factory=PCBSimulationInput)
    budget: PCBBudget = Field(default_factory=PCBBudget)

    @model_serializer(mode='wrap')
    def legacy_project_snapshot(self, handler):
        data = handler(self)
        for key, default in (('layer_count', 2), ('net_labels', {}), ('vias', []), ('zones', [])):
            if getattr(self, key) == default:
                data.pop(key, None)
        return data

    @model_validator(mode='after')
    def references(self):
        if 'GND' not in self.nets or len(set(self.nets)) != len(self.nets):
            raise ValueError('중복 없는 net과 GND를 지정하세요. / Unique nets including GND required.')
        for collection in ([c.ref for c in self.components], [obj.id for obj in [*self.tracks, *self.vias, *self.zones]]):
            if len(set(collection)) != len(collection):
                raise ValueError('부품·구리 ID가 중복됩니다. / Duplicate reference or copper ID.')
        if any(p.net and p.net not in self.nets for c in self.components for p in c.pins) or any(t.net not in self.nets for t in [*self.tracks, *self.vias, *self.zones]) or not set(self.net_labels) <= set(self.nets):
            raise ValueError('핀·배선이 등록되지 않은 net을 참조합니다. / Unknown net.')
        active = copper_layers(self)
        if any(layer not in active for c in self.components for pin in c.pins for layer in pin.layers) or any(obj.layer not in active for obj in [*self.tracks, *self.zones]):
            raise ValueError('보드에서 사용하지 않는 구리층입니다. / Inactive copper layer.')
        for via in self.vias:
            via_layers(self, via)
        if sum(len(t.points) - 1 for t in self.tracks) > 1024 or sum(len(c.pins) for c in self.components) > 512:
            raise ValueError('편집 한도: 패드 512개, 선분 1024개. / Layout complexity limit exceeded.')
        return self


def copper_layers(project):
    """Active copper in physical order; does not invent a fabrication stackup."""
    count = project.layer_count if isinstance(project, PCBProject) else project.get('layer_count', 2)
    if count not in (2, 4):
        raise ValueError('Only two or four copper layers are supported.')
    return list(COPPER_LAYERS if count == 4 else ('F.Cu', 'B.Cu'))


def via_layers(project, via):
    """Expand endpoint pairs; otherwise require a complete contiguous span."""
    active = copper_layers(project)
    layers = via.layers if isinstance(via, PCBVia) else via['layers']
    if any(layer not in active for layer in layers):
        raise ValueError('Via references an inactive copper layer.')
    positions = [active.index(layer) for layer in layers]
    if len(positions) < 2 or positions != sorted(set(positions)):
        raise ValueError('Via layers must be unique and ordered.')
    span = active[positions[0]:positions[-1]+1]
    if len(layers) != 2 and list(layers) != span:
        raise ValueError('Via layers must be an endpoint pair or complete contiguous span.')
    return span


def pcb_digest(project):
    p = PCBProject.model_validate(project)
    return hashlib.sha256(json.dumps(p.model_dump(mode='json'), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def pad_positions(project):
    p = PCBProject.model_validate(project)
    pads = []
    for c in p.components:
        a = math.radians(c.rotation_deg)
        for pin in c.pins:
            pads.append(dict(ref=c.ref, pin=pin.number, net=pin.net, radius=pin.diameter_mm/2, layers=pin.layers,
                diameter_mm=pin.diameter_mm, shape=pin.shape, size_x_mm=pin.size_x_mm or pin.diameter_mm,
                size_y_mm=pin.size_y_mm or pin.diameter_mm, rotation_deg=(c.rotation_deg+pin.rotation_deg)%360,
                roundrect_rratio=pin.roundrect_rratio, drill_mm=pin.drill_mm,
                x=c.x_mm + pin.x_mm*math.cos(a) - pin.y_mm*math.sin(a),
                y=c.y_mm + pin.x_mm*math.sin(a) + pin.y_mm*math.cos(a)))
    return pads


def point_segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def segment_distance(a, b, c, d):
    def cross(p, q, r): return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    ab = cross(a,b,c), cross(a,b,d)
    cd = cross(c,d,a), cross(c,d,b)
    if ab[0]*ab[1] <= 0 and cd[0]*cd[1] <= 0 and max(min(a[0],b[0]), min(c[0],d[0])) <= min(max(a[0],b[0]), max(c[0],d[0])) and max(min(a[1],b[1]), min(c[1],d[1])) <= min(max(a[1],b[1]), max(c[1],d[1])):
        return 0.0
    return min(point_segment_distance(a,c,d), point_segment_distance(b,c,d), point_segment_distance(c,a,b), point_segment_distance(d,a,b))


def track_segments(project):
    return [dict(id=t.id, net=t.net, layer=t.layer, radius=t.width_mm/2, a=(a.x_mm,a.y_mm), b=(b.x_mm,b.y_mm))
        for t in project.tracks for a,b in zip(t.points,t.points[1:])]


def inspect_layout(project, layers=None):
    p = PCBProject.model_validate(project)
    active = copper_layers(p)
    selected = active if layers is None else list(layers)
    if not selected or len(selected) != len(set(selected)) or any(layer not in active for layer in selected):
        raise ValueError('Inspection layers must be unique active copper layers.')
    pads = [pad for pad in pad_positions(p) if set(pad['layers']) & set(selected)]
    segments = [segment for segment in track_segments(p) if segment['layer'] in selected]
    vias = [dict(id=via.id,net=via.net,x=via.x_mm,y=via.y_mm,radius=via.diameter_mm/2,
        shape='circle',size_x_mm=via.diameter_mm,size_y_mm=via.diameter_mm,rotation_deg=0,
        roundrect_rratio=.25,drill_mm=via.drill_mm,layers=via_layers(p,via))
        for via in p.vias if set(via_layers(p,via)) & set(selected)]
    zones = [zone for zone in p.zones if zone.layer in selected]
    fills = []
    findings = []
    def report(code, refs, message, severity='error'):
        finding = dict(code=code,severity=severity,refs=refs,message=message)
        if finding not in findings:
            findings.append(finding)
    def inside(x,y,r): return min(x,y,p.width_mm-x,p.height_mm-y) + 1e-9 >= r+p.edge_clearance_mm
    def pad_inside(pad):
        left,top,right,bottom = geometry.pad_bounds(pad)
        return min(left,top,p.width_mm-right,p.height_mm-bottom)+1e-9 >= p.edge_clearance_mm
    for pad in pads:
        if not pad_inside(pad): report('pad_edge',[pad['ref'],pad['pin']],'패드가 보드 경계 여유 밖에 있습니다. / Pad edge clearance.')
    for via in vias:
        if not pad_inside(via): report('via_edge',[via['id']],'비아가 보드 경계 여유 밖에 있습니다. / Via edge clearance.')
    for s in segments:
        if not all(inside(*point,s['radius']) for point in (s['a'],s['b'])): report('track_edge',[s['id']],'배선이 보드 경계 여유 밖에 있습니다. / Track edge clearance.')
    for zone in zones:
        declared = geometry.region(zone.outline,zone.holes)
        if not zone.filled_polygons:
            report('zone_fill_missing',[zone.id],'영역 외곽선만 저장되어 있습니다. 구리 채움·연결은 확인되지 않았습니다. / Zone outline has no stored copper fill; connectivity is unverified.','warning')
        else:
            report('zone_fill_unverified',[zone.id],'저장된 채움 형상을 검사합니다. 재채움·제조 DRC 결과는 아닙니다. / Stored fill geometry only; no refill or manufacturing DRC is performed.','warning')
        for polygon in zone.filled_polygons:
            filled = geometry.region(polygon.points,polygon.holes)
            simple = geometry.is_simple_ring(polygon.points)
            fills.append(dict(id=zone.id,net=zone.net,layer=zone.layer,polygon=filled,simple=simple))
            if not simple:
                report('zone_contour_checks_partial',[zone.id],'분할·슬릿 채움 윤곽은 원점 순서로 보존합니다. 구리 간격·내부 연결 검증은 일부만 수행합니다. / Fractured or weakly-simple fill contours are preserved; copper clearance and internal connectivity remain unverified.','warning')
            if not geometry.region_within(filled,declared):
                report('zone_fill_boundary',[zone.id],'채움 구리가 선언한 영역·홀 경계와 다릅니다. / Stored copper fill exceeds the declared outline or covers a declared hole.')
            if not all(inside(x,y,0) for x,y in filled['points']):
                report('zone_edge',[zone.id],'채움 구리가 보드 경계 여유 밖에 있습니다. / Filled copper edge clearance.')
    drilled = [[pad['ref'],pad['pin']] for pad in pads if pad['drill_mm']] + [[via['id']] for via in vias]
    if drilled:
        report('drill_checks_partial',[ref for refs in drilled for ref in refs],
            '원형 홀을 보존합니다. 접촉은 구리 형상으로 확인하나 도금·환형링·홀 간격은 검증하지 않습니다. / Circular apertures are preserved; plating, annular-ring and drill clearance rules are not qualified. Drilled contact witnesses can leave connections unverified.','warning')
    if layers is not None and set(selected) != set(active):
        report('layer_subset',[*selected],'선택한 층의 구리만 검사합니다. 전체 보드 연결 검증은 아닙니다. / Only selected layers are inspected; this is a partial board check.','warning')
    for i,a in enumerate(pads):
        for b in pads[i+1:]:
            if not set(a['layers']) & set(b['layers']) & set(selected): continue
            gap = geometry.pad_gap(a,b)
            same = a['net'] is not None and a['net'] == b['net']
            ca,_ = geometry.pad_core(a); cb,_ = geometry.pad_core(b)
            rect_overlap = gap <= 1e-9 and geometry.core_overlap(ca,cb)
            if gap < (0 if same else p.clearance_mm) - 1e-9 or (same and rect_overlap):
                report('pad_collision' if same else 'pad_clearance',[a['ref'],a['pin'],b['ref'],b['pin']],'패드 간 충돌 또는 서로 다른 net 간격 부족. / Pad collision or net clearance.')
    for s in segments:
        for pad in pads:
            if s['layer'] not in pad['layers'] or s['net'] == pad['net']: continue
            if geometry.pad_track_gap(pad,s) < p.clearance_mm - 1e-9:
                report('track_pad_clearance',[s['id'],pad['ref'],pad['pin']],'배선이 다른 net의 패드에 너무 가깝습니다. / Track to pad clearance.')
    for i,a in enumerate(segments):
        for b in segments[i+1:]:
            if a['layer'] == b['layer'] and a['net'] != b['net'] and segment_distance(a['a'],a['b'],b['a'],b['b']) < a['radius']+b['radius']+p.clearance_mm-1e-9:
                report('track_clearance',[a['id'],b['id']],'같은 층의 서로 다른 net 배선이 교차하거나 너무 가깝습니다. / Track clearance or short.')
    for i,via in enumerate(vias):
        for other in vias[i+1:]:
            if via['net'] != other['net'] and set(via['layers']) & set(other['layers']) & set(selected) and geometry.pad_gap(via,other) < p.clearance_mm-1e-9:
                report('via_clearance',[via['id'],other['id']],'다른 net 비아의 구리 간격이 부족합니다. / Via copper clearance.')
        for pad in pads:
            if via['net'] != pad['net'] and set(via['layers']) & set(pad['layers']) & set(selected) and geometry.pad_gap(via,pad) < p.clearance_mm-1e-9:
                report('via_pad_clearance',[via['id'],pad['ref'],pad['pin']],'비아와 다른 net 패드의 간격이 부족합니다. / Via to pad clearance.')
        for segment in segments:
            if via['net'] != segment['net'] and segment['layer'] in via['layers'] and geometry.pad_track_gap(via,segment) < p.clearance_mm-1e-9:
                report('track_via_clearance',[segment['id'],via['id']],'배선과 다른 net 비아의 간격이 부족합니다. / Track to via clearance.')
    for i,fill in enumerate(fills):
        # Fracture bridges are representation edges, not necessarily copper.
        # Retain/render them, but do not invent clearance or connected islands.
        if not fill['simple']: continue
        for other in fills[i+1:]:
            if other['simple'] and fill['net'] != other['net'] and fill['layer'] == other['layer'] and geometry.regions_gap(fill['polygon'],other['polygon']) < p.clearance_mm-1e-9:
                report('zone_clearance',[fill['id'],other['id']],'다른 net 채움 구리의 간격이 부족합니다. / Stored fill copper clearance.')
        for pad in pads+vias:
            if fill['net'] != pad['net'] and fill['layer'] in pad['layers'] and geometry.pad_region_gap(pad,fill['polygon']) < p.clearance_mm-1e-9:
                refs = [fill['id'],pad['ref'],pad['pin']] if 'ref' in pad else [fill['id'],pad['id']]
                report('zone_pad_clearance',refs,'채움 구리와 다른 net 패드·비아의 간격이 부족합니다. / Stored fill to pad or via clearance.')
        for segment in segments:
            if fill['net'] != segment['net'] and fill['layer'] == segment['layer'] and geometry.track_region_gap(segment,fill['polygon']) < p.clearance_mm-1e-9:
                report('zone_track_clearance',[fill['id'],segment['id']],'채움 구리와 다른 net 배선의 간격이 부족합니다. / Stored fill to track clearance.')
    # Connectivity is based on intersecting stored copper, never equal labels,
    # via declarations alone, or a zone outline. Multi-layer pad declarations
    # and explicit via spans are bridges in this geometric model; plating is
    # not independently established. Holes cannot become copper proxies.
    def connected(a,b):
        alayers = a.get('layers',[a.get('layer')]); blayers = b.get('layers',[b.get('layer')])
        if not set(alayers) & set(blayers) & set(selected): return False
        ap, bp = 'shape' in a, 'shape' in b
        az, bz = 'polygon' in a, 'polygon' in b
        if ap and bp: return geometry.pads_connected(a,b)
        if ap or bp:
            pad, other = (a,b) if ap else (b,a)
            if 'polygon' not in other: return geometry.pad_track_connected(pad,other)
            if geometry.pad_region_gap(pad,other['polygon']) > 1e-9: return False
            if not pad['drill_mm']: return True
            return any(geometry.region_contains(point,other['polygon']) for point in geometry.pad_witnesses(pad)) or any(geometry.pad_contains(point,pad) for point in other['polygon']['points'])
        if az and bz: return geometry.regions_gap(a['polygon'],b['polygon']) <= 1e-9
        if az or bz:
            zone,segment = (a,b) if az else (b,a)
            return geometry.track_region_gap(segment,zone['polygon']) <= 1e-9
        return segment_distance(a['a'],a['b'],b['a'],b['b']) <= a['radius']+b['radius']+1e-9
    for net in p.nets:
        npads = [a for a in pads if a['net'] == net]
        nsegs = [a for a in segments if a['net'] == net]
        nvias = [a for a in vias if a['net'] == net]
        nfills = [a for a in fills if a['net'] == net and a['simple']]
        uncertain_fill = any(a['net'] == net and not a['simple'] for a in fills)
        objects = npads+nsegs+nvias+nfills
        roots = list(range(len(objects)))
        def root(i):
            while roots[i] != i:
                roots[i] = roots[roots[i]]; i = roots[i]
            return i
        def join(i,j): roots[root(j)] = root(i)
        for i,a in enumerate(objects):
            for j in range(i+1,len(objects)):
                b = objects[j]
                if connected(a,b): join(i,j)
        if len({root(i) for i in range(len(npads))}) > 1:
            report('unrouted_net',[net],'net 패드 사이의 저장된 구리 경로가 확인되지 않았습니다. / No verified stored copper path between all net pads.','warning' if uncertain_fill else 'error')
        for i in range(len(npads),len(objects)):
            if not any(root(i) == root(j) for j in range(len(npads))):
                obj = objects[i]
                code = 'orphan_via' if 'shape' in obj else 'orphan_zone' if 'polygon' in obj else 'orphan_track'
                report(code,[obj['id']],'구리가 같은 net 패드에 연결되었다는 근거가 없습니다. / Copper has no verified connection to a same-net pad.','warning' if uncertain_fill else 'error')
    errors = any(finding['severity'] == 'error' for finding in findings)
    return dict(status='needs_edit' if errors else 'partial_checks' if findings else 'geometric_checks_passed', pcb_sha256=pcb_digest(p), findings=findings,
        checked_layers=selected, manufacturing_qualified=False,
        limits=['Checks use declared pad outer shapes, straight copper, via spans and stored fill polygons. Hole-aware contact witnesses are conservative; clearance checks use outer copper envelopes and may flag a hole void.',
                'Zone outlines never imply filled or connected copper. Stored fills are not recomputed or certified; fractured fill copper clearance and internal connectivity remain unchecked.',
                'No plating, annular-ring, drill-to-drill rules, fabrication stackup, impedance, ampacity, manufacturing or thermal qualification.',
                'Logical netlist simulation is independent of actual copper routing.'])


def bom_report(project):
    p = PCBProject.model_validate(project)
    groups = defaultdict(list)
    for c in p.components:
        if c.fitted:
            # An absent MPN/value does not make an ideal source and resistor
            # the same purchase item. Anonymous items group by explicit model.
            identity=c.mpn if c.mpn else (json.dumps(dict(model=c.model.model_dump(mode='json'),
                pads=[dict(x=pin.x_mm,y=pin.y_mm,diameter=pin.diameter_mm,layers=pin.layers,
                    **{key:value for key,value in pin.model_dump(mode='json').items() if key in ('shape','size_x_mm','size_y_mm','rotation_deg','roundrect_rratio','drill_mm')}) for pin in c.pins],
                body=[c.body_width_mm,c.body_height_mm]),sort_keys=True) if c.model.kind in ('resistor','capacitor','voltage_source') else c.ref)
            key = (identity,c.value,c.footprint,json.dumps(c.quote.model_dump(mode='json'),sort_keys=True))
            groups[key].append(c)
    totals = defaultdict(Decimal); rows = []; unknown = []; target_total = Decimal(0)
    for components in groups.values():
        c, q = components[0], components[0].quote
        count = len(components)*p.budget.board_quantity
        purchase = math.ceil(max(count,q.minimum_quantity)/q.pack_quantity)*q.pack_quantity
        subtotal = q.unit_price*purchase if q.unit_price is not None else None
        row = dict(refs=[c.ref for c in components],mpn=c.mpn,value=c.value,footprint=c.footprint,required_quantity=count,
            purchase_quantity=purchase,quote=q.model_dump(mode='json'),subtotal=str(subtotal) if subtotal is not None else None)
        rows.append(row)
        if subtotal is None: unknown.extend(row['refs'])
        else:
            totals[q.currency] += subtotal
            if q.currency == p.budget.currency: target_total += subtotal
    complete = not unknown and all(row['quote']['currency'] == p.budget.currency for row in rows)
    return dict(rows=rows,known_subtotals={k:str(v) for k,v in sorted(totals.items())},unknown_refs=unknown,
        budget=p.budget.model_dump(mode='json'),budget_status=('incomplete' if not complete else 'not_set' if p.budget.limit is None else 'over' if target_total>p.budget.limit else 'within'),
        estimated_complete=complete,excludes=['PCB fabrication','assembly','shipping','tax','exchange conversion'],
        note='Reference/entered quotes are estimates at their stored date, not live offers. No exchange rate is invented.')


def bom_csv(project):
    stream = io.StringIO(newline='');writer = csv.writer(stream)
    writer.writerow(['Refs','MPN','Value','Footprint','Required','Purchase','Unit price','Currency','Price status','As of','Supplier','Source','Subtotal'])
    def cell(v):
        s = str(v or '')
        return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s
    for row in bom_report(project)['rows']:
        q = row['quote']
        writer.writerow([cell(v) for v in [','.join(row['refs']),row['mpn'],row['value'],row['footprint'],row['required_quantity'],row['purchase_quantity'],q['unit_price'],q['currency'],q['status'],q['as_of'],q['supplier'],q['source_url'],row['subtotal']]])
    return stream.getvalue()


def new_component(kind='resistor', ref='R1', x=10, y=10):
    model = dict(kind=kind)
    values = {'resistor':dict(resistance_ohm=1000),'capacitor':dict(capacitance_f=1e-6),'voltage_source':dict(dc_voltage_v=5,ac_voltage_v=1)}
    if kind in values: model.update(pin_a='P1',pin_b='P2',**values[kind])
    return PCBComponent(ref=ref,x_mm=x,y_mm=y,pins=[PCBPin(number='P1',x_mm=-2),PCBPin(number='P2',x_mm=2)],model=model)


def divider_example():
    p = PCBProject(name='5 V · 1 kΩ / 1 kΩ 분압 예제',nets=['GND','VIN','OUT'])
    for kind,ref,x,y,na,nb in [('voltage_source','V1',10,10,'VIN','GND'),('resistor','R1',25,10,'VIN','OUT'),('resistor','R2',40,10,'OUT','GND')]:
        c = new_component(kind,ref,x,y);c.pins[0].net=na;c.pins[1].net=nb;p.components.append(c)
    p.tracks = [PCBTrack(id='T1',net='VIN',points=[PCBPoint(x_mm=8,y_mm=10),PCBPoint(x_mm=8,y_mm=5),PCBPoint(x_mm=23,y_mm=5),PCBPoint(x_mm=23,y_mm=10)]),
        PCBTrack(id='T2',net='OUT',points=[PCBPoint(x_mm=27,y_mm=10),PCBPoint(x_mm=38,y_mm=10)]),
        PCBTrack(id='T3',net='GND',points=[PCBPoint(x_mm=12,y_mm=10),PCBPoint(x_mm=12,y_mm=18),PCBPoint(x_mm=42,y_mm=18),PCBPoint(x_mm=42,y_mm=10)])]
    return PCBProject.model_validate(p.model_dump())
