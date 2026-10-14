"""Declarative, bounded PCB editing. Circular pads and straight copper only.

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

Id = Annotated[str, Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')]
PinId = Annotated[str, Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')]
Coord = Annotated[float, Field(ge=-1000, le=1000)]
Layer = Literal['F.Cu', 'B.Cu']


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
    layers: list[Layer] = Field(default_factory=lambda: ['F.Cu'], min_length=1, max_length=2)

    @model_validator(mode='after')
    def layer_set(self):
        if len(set(self.layers)) != len(self.layers):
            raise ValueError('패드 층은 중복 없이 지정하세요. / Duplicate pad layers.')
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
    clearance_mm: float = Field(default=.2, ge=.05, le=5)
    edge_clearance_mm: float = Field(default=.5, ge=0, le=10)
    nets: list[Id] = Field(default_factory=lambda: ['GND'], min_length=1, max_length=192)
    components: list[PCBComponent] = Field(default_factory=list, max_length=64)
    tracks: list[PCBTrack] = Field(default_factory=list, max_length=256)
    simulation: PCBSimulationInput = Field(default_factory=PCBSimulationInput)
    budget: PCBBudget = Field(default_factory=PCBBudget)

    @model_validator(mode='after')
    def references(self):
        if 'GND' not in self.nets or len(set(self.nets)) != len(self.nets):
            raise ValueError('중복 없는 net과 GND를 지정하세요. / Unique nets including GND required.')
        for collection in ([c.ref for c in self.components], [t.id for t in self.tracks]):
            if len(set(collection)) != len(collection):
                raise ValueError('부품·배선 ID가 중복됩니다. / Duplicate reference or track ID.')
        if any(p.net and p.net not in self.nets for c in self.components for p in c.pins) or any(t.net not in self.nets for t in self.tracks):
            raise ValueError('핀·배선이 등록되지 않은 net을 참조합니다. / Unknown net.')
        if sum(len(t.points) - 1 for t in self.tracks) > 1024 or sum(len(c.pins) for c in self.components) > 512:
            raise ValueError('편집 한도: 패드 512개, 선분 1024개. / Layout complexity limit exceeded.')
        return self


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


def inspect_layout(project):
    p = PCBProject.model_validate(project)
    pads, segments = pad_positions(p), track_segments(p)
    findings = []
    def report(code, refs, message): findings.append(dict(code=code, severity='error', refs=refs, message=message))
    def inside(x,y,r): return min(x,y,p.width_mm-x,p.height_mm-y) + 1e-9 >= r+p.edge_clearance_mm
    for pad in pads:
        if not inside(pad['x'],pad['y'],pad['radius']): report('pad_edge',[pad['ref'],pad['pin']],'패드가 보드 경계 여유 밖에 있습니다. / Pad edge clearance.')
    for s in segments:
        if not all(inside(*point,s['radius']) for point in (s['a'],s['b'])): report('track_edge',[s['id']],'배선이 보드 경계 여유 밖에 있습니다. / Track edge clearance.')
    for i,a in enumerate(pads):
        for b in pads[i+1:]:
            if not set(a['layers']) & set(b['layers']): continue
            gap = math.hypot(a['x']-b['x'],a['y']-b['y']) - a['radius'] - b['radius']
            same = a['net'] is not None and a['net'] == b['net']
            if gap < (0 if same else p.clearance_mm) - 1e-9:
                report('pad_collision' if same else 'pad_clearance',[a['ref'],a['pin'],b['ref'],b['pin']],'패드 간 충돌 또는 서로 다른 net 간격 부족. / Pad collision or net clearance.')
    for s in segments:
        for pad in pads:
            if s['layer'] not in pad['layers'] or s['net'] == pad['net']: continue
            if point_segment_distance((pad['x'],pad['y']),s['a'],s['b']) < s['radius'] + pad['radius'] + p.clearance_mm - 1e-9:
                report('track_pad_clearance',[s['id'],pad['ref'],pad['pin']],'배선이 다른 net의 패드에 너무 가깝습니다. / Track to pad clearance.')
    for i,a in enumerate(segments):
        for b in segments[i+1:]:
            if a['layer'] == b['layer'] and a['net'] != b['net'] and segment_distance(a['a'],a['b'],b['a'],b['b']) < a['radius']+b['radius']+p.clearance_mm-1e-9:
                report('track_clearance',[a['id'],b['id']],'같은 층의 서로 다른 net 배선이 교차하거나 너무 가깝습니다. / Track clearance or short.')
    # Actual copper connectivity: connected pads, segment intersections and
    # declared multi-layer pads. Same net names alone never prove routing.
    for net in p.nets:
        npads = [a for a in pads if a['net'] == net]
        nsegs = [a for a in segments if a['net'] == net]
        objects = npads + nsegs
        roots = list(range(len(objects)))
        def root(i):
            while roots[i] != i:
                roots[i] = roots[roots[i]]; i = roots[i]
            return i
        def join(i,j): roots[root(j)] = root(i)
        for i,a in enumerate(objects):
            for j in range(i+1,len(objects)):
                b = objects[j]
                ap, bp = i < len(npads), j < len(npads)
                if ap and bp:
                    connected = bool(set(a['layers']) & set(b['layers'])) and math.hypot(a['x']-b['x'],a['y']-b['y']) <= a['radius']+b['radius']+1e-9
                elif ap:
                    connected = b['layer'] in a['layers'] and point_segment_distance((a['x'],a['y']),b['a'],b['b']) <= a['radius']+b['radius']+1e-9
                else:
                    connected = a['layer'] == b['layer'] and segment_distance(a['a'],a['b'],b['a'],b['b']) <= a['radius']+b['radius']+1e-9
                if connected: join(i,j)
        if len({root(i) for i in range(len(npads))}) > 1:
            report('unrouted_net',[net],'net의 패드가 구리로 모두 연결되지 않았습니다. / Disconnected copper islands.')
        for i in range(len(npads),len(objects)):
            if not any(root(i) == root(j) for j in range(len(npads))):
                report('orphan_track',[objects[i]['id']],'배선이 같은 net 패드에 연결되지 않았습니다. / Orphan track.')
    return dict(status='needs_edit' if findings else 'geometric_checks_passed', pcb_sha256=pcb_digest(p), findings=findings,
        limits=['Circular pads and straight segments only. No pours, vias, drills, impedance, ampacity, manufacturing or thermal qualification.',
                'Logical netlist simulation is independent of actual copper routing.'])


def bom_report(project):
    p = PCBProject.model_validate(project)
    groups = defaultdict(list)
    for c in p.components:
        if c.fitted:
            # An absent MPN/value does not make an ideal source and resistor
            # the same purchase item. Anonymous items group by explicit model.
            identity=c.mpn if c.mpn else (json.dumps(dict(model=c.model.model_dump(mode='json'),
                pads=[dict(x=pin.x_mm,y=pin.y_mm,diameter=pin.diameter_mm,layers=pin.layers) for pin in c.pins],
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
