"""Small, deterministic DC wiring study attached to a CAD design.

This is a resistive operating-point calculation, not SPICE, firmware execution,
or a physical motor/driver model. A motor/actuator's rated and optional starting
current define two separate equivalent-resistance estimates at its rated voltage.
Capacitors are open at settled DC; inductors retain their winding resistance.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Literal
from urllib.parse import urlsplit

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from .measurement_specs import MeasurementSpec, ForceChainSpec


class ElectricalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Identifier = str
Kind = Literal["battery", "wire", "switch", "resistor", "capacitor", "inductor",
               "load", "motor", "actuator", "mcu"]


class ElectricalWireEndpoint(ElectricalModel):
    component_id: str = Field(min_length=1,max_length=40,pattern=r"^[A-Za-z0-9_-]+$")
    terminal: str = Field(min_length=1,max_length=48,pattern=r"^(a|b|(pin|port|supply):[A-Za-z0-9_-]+)$")


class ElectricalComponent(ElectricalModel):
    id: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    kind: Kind
    a: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    b: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    source_url: str = Field(default="", max_length=500)
    # A physical CAD registration may precede verified operating values. It is
    # then a passive wiring/reference feature, not an invented DC load.
    analysis_enabled: bool = True
    part_registration: bool = False
    voltage_v: float = Field(default=0, ge=0, le=1000)
    internal_resistance_ohm: float = Field(default=0, ge=0, le=10000)
    resistance_ohm: float = Field(default=0, ge=0, le=1e9)
    # Stored in SI units. DC capacitors are open circuits; inductors use their
    # measured winding resistance after the transient has settled.
    capacitance_f: float = Field(default=0, ge=0, le=10000)
    inductance_h: float = Field(default=0, ge=0, le=10000)
    winding_resistance_ohm: float = Field(default=0, ge=0, le=1e9)
    capacitor_polarized: bool = False
    rated_voltage_v: float = Field(default=0, ge=0, le=1000)
    rated_current_a: float = Field(default=0, ge=0, le=10000)
    max_current_a: float | None = Field(default=None, gt=0, le=10000)
    startup_current_a: float | None = Field(default=None, gt=0, le=10000)
    length_mm: float = Field(default=0, ge=0, le=1e7)
    cross_section_mm2: float = Field(default=0, ge=0, le=1e5)
    # Copper near room temperature, in ohm * mm^2 / m. User may override.
    resistivity_ohm_mm2_per_m: float = Field(default=0.01724, gt=0, le=100)
    closed: bool = True
    wire_color: str | None = Field(default=None,pattern=r"^#[0-9a-fA-F]{6}$")
    wire_endpoints: list[ElectricalWireEndpoint] = Field(default_factory=list,max_length=2)
    contact_resistance_ohm: float = Field(default=0.01, gt=0, le=1000)
    # MCU signal pins and user-declared sensor/driver signal terminals are
    # passive net labels. They add no GPIO output resistance or digital logic.
    signal_pins: dict[str, Identifier] = Field(default_factory=dict, max_length=144)
    terminal_pins: dict[str, Identifier] = Field(default_factory=dict, max_length=144)
    board_supply_pins: dict[str, Identifier] = Field(default_factory=dict, max_length=144)
    supply_pinout_catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    # Opt-in physical board pin provenance. Legacy arbitrary labels remain
    # readable until the user explicitly binds them to an exact board pinout.
    pinout_catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    product_pinout_catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    measurement: MeasurementSpec | None = None

    @model_serializer(mode="wrap")
    def compatible_registration_fields(self, handler):
        data = handler(self)
        # These fields were added after circuit snapshots were already stored
        # in journals. Keep absent legacy defaults absent, while retaining
        # explicit defaults in newer snapshots and every nondefault value.
        # Replaying history must still compare exact before/after values.
        for field, default in (("analysis_enabled", True), ("part_registration", False),
                               ("terminal_pins", {}), ("pinout_catalog_id", ""),
                               ("product_pinout_catalog_id", ""), ("board_supply_pins", {}),
                               ("supply_pinout_catalog_id", ""), ("capacitance_f", 0),
                               ("inductance_h", 0), ("winding_resistance_ohm", 0),
                               ("capacitor_polarized", False)):
            if field not in self.model_fields_set and getattr(self, field) == default:
                data.pop(field, None)
        for field,default in (("wire_color",None),("wire_endpoints",[]),("measurement",None)):
            if field not in self.model_fields_set and getattr(self,field)==default:data.pop(field,None)
        return data

    @model_validator(mode="after")
    def required_values(self):
        if self.a == self.b:
            raise ValueError("전장 부품 양 끝은 서로 다른 노드에 연결해야 합니다.")
        if self.measurement is not None and self.kind not in ('load','mcu'):
            raise ValueError('Measurement references attach to sensor/ADC loads or MCU boards, not power or motor branches.')
        if (self.wire_color or self.wire_endpoints) and self.kind!='wire':
            raise ValueError("전선 색과 연결 단자 정보는 전선에만 지정합니다.")
        if self.wire_endpoints and (len(self.wire_endpoints)!=2 or self.wire_endpoints[0]==self.wire_endpoints[1]):
            raise ValueError("전선에는 서로 다른 시작·도착 단자 두 개를 지정하세요.")
        if self.analysis_enabled and self.kind == "battery" and self.voltage_v <= 0:
            raise ValueError("배터리의 개방 전압(V)을 입력하세요.")
        if self.analysis_enabled and self.kind == "wire" and (self.length_mm <= 0 or self.cross_section_mm2 <= 0):
            raise ValueError("전선의 길이(mm)와 단면적(mm²)을 입력하세요.")
        if self.analysis_enabled and self.kind == "resistor" and self.resistance_ohm <= 0:
            raise ValueError("저항값(Ω)을 입력하세요.")
        if self.analysis_enabled and self.kind == "capacitor" and self.capacitance_f <= 0:
            raise ValueError("캐패시터의 정전용량(F)을 입력하세요.")
        if self.analysis_enabled and self.kind == "inductor" and (self.inductance_h <= 0 or self.winding_resistance_ohm <= 0):
            raise ValueError("코일의 인덕턴스(H)와 실제 권선 저항(Ω)을 입력하세요. 이상적 단락으로 대신 계산하지 않습니다.")
        if self.analysis_enabled and self.kind in ("load", "motor", "actuator", "mcu") and (self.rated_voltage_v <= 0 or self.rated_current_a <= 0):
            raise ValueError("부하의 정격 전압(V)과 전류(A)를 입력하세요.")
        if self.startup_current_a is not None and self.kind not in ("motor", "actuator"):
            raise ValueError("기동 전류는 모터·액추에이터에만 지정할 수 있습니다.")
        if (self.capacitance_f or self.capacitor_polarized) and self.kind != "capacitor":
            raise ValueError("정전용량과 극성은 캐패시터에만 지정할 수 있습니다.")
        if (self.inductance_h or self.winding_resistance_ohm) and self.kind != "inductor":
            raise ValueError("인덕턴스와 권선 저항은 코일에만 지정할 수 있습니다.")
        if self.signal_pins and self.kind != "mcu":
            raise ValueError("신호 핀은 MCU에만 지정할 수 있습니다.")
        if self.terminal_pins and self.kind not in ("load", "motor", "actuator"):
            raise ValueError("추가 신호 단자는 일반 부하·센서·드라이버·모터·액추에이터 항목에만 지정할 수 있습니다.")
        if self.pinout_catalog_id and self.kind != "mcu":
            raise ValueError("물리 핀 모식도는 MCU / 보드 항목에만 연결할 수 있습니다.")
        if (self.board_supply_pins or self.supply_pinout_catalog_id) and self.kind != "mcu":
            raise ValueError("물리 보드 전원 연결은 MCU / MPU 보드에만 지정합니다.")
        if self.part_registration and not self.part_id:
            raise ValueError("전장 등록은 실제 CAD 부품 ID에 연결해야 합니다.")
        if self.source_url:
            parsed = urlsplit(self.source_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or any(character.isspace() or ord(character) < 32 for character in self.source_url)):
                raise ValueError("제품 사양 출처는 안전한 HTTPS 주소로 지정하세요.")
        for pin, node in (*self.signal_pins.items(), *self.terminal_pins.items(), *self.board_supply_pins.items()):
            if (not pin or len(pin) > 40 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in pin)
                    or not node or len(node) > 40
                    or not all(c.isascii() and (c.isalnum() or c in "_-") for c in node)):
                raise ValueError("MCU 핀 이름과 노드 ID는 영문·숫자·_·-만 사용할 수 있습니다.")
        if self.pinout_catalog_id:
            from .mcu_connections import validate_bound_pin_map

            validate_bound_pin_map(self.catalog_id, self.pinout_catalog_id, self.signal_pins)
        if self.product_pinout_catalog_id:
            from .mcu_connections import validate_bound_terminal_map

            validate_bound_terminal_map(self.catalog_id, self.product_pinout_catalog_id, self.terminal_pins)
        if self.board_supply_pins or self.supply_pinout_catalog_id:
            from .board_supply import validate_board_supply_map
            validate_board_supply_map(self.catalog_id,self.supply_pinout_catalog_id,self.board_supply_pins)
        if self.part_registration and self.catalog_id:
            from .board_pins import board_pinout
            from .electrical_catalog import get_catalog_entry
            from .product_diagrams import product_diagram

            entry = get_catalog_entry(self.catalog_id)
            board = board_pinout(self.catalog_id)
            product = product_diagram(self.catalog_id)
            if entry is None or (entry.reference_only and product is None):
                raise ValueError("전장 등록에는 확인된 특정 제품 모델을 선택하세요. 제품군·미확인 모델은 수동 등록을 사용하세요.")
            expected = entry.suggested_kind or ("mcu" if board else "load")
            if self.kind != expected:
                raise ValueError("등록된 실제 제품 모델과 전장 부품 종류가 일치하지 않습니다.")
            if board and self.pinout_catalog_id != self.catalog_id:
                raise ValueError("등록된 MCU 제품의 물리 핀 모식도 연결을 유지하세요.")
            if product and self.product_pinout_catalog_id != self.catalog_id:
                raise ValueError("등록된 실제 제품의 물리 단자 모식도 연결을 유지하세요.")
            if self.analysis_enabled and (entry.reference_only or entry.suggested_kind is None):
                raise ValueError("이 제품의 동작 회로 모델은 지원하지 않습니다. 물리 모식도·수동 결선으로 등록하고 DC 계산은 제외하세요.")
        return self


class ElectricalSchematicPosition(ElectricalModel):
    """Cosmetic diagram coordinates, independent of CAD millimetres and nets."""

    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)


class ElectricalWorkspace(ElectricalModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="전장 회로", min_length=1, max_length=100)
    nodes: list[Identifier] = Field(default_factory=lambda: ["GND"], min_length=1, max_length=128)
    components: list[ElectricalComponent] = Field(default_factory=list, max_length=256)
    schematic_positions: dict[Identifier, ElectricalSchematicPosition] = Field(default_factory=dict, max_length=256)
    force_chain: ForceChainSpec | None = None

    @model_serializer(mode="wrap")
    def compatible_schematic_positions(self, handler):
        data = handler(self)
        # Journals created before the circuit canvas compare exact snapshots.
        # Retain an explicit empty layout and in-place additions, while an
        # absent legacy layout stays absent during load/save and undo/redo.
        if "schematic_positions" not in self.model_fields_set and not self.schematic_positions:
            data.pop("schematic_positions", None)
        if 'force_chain' not in self.model_fields_set and self.force_chain is None:data.pop('force_chain',None)
        return data

    @model_validator(mode="after")
    def valid_netlist(self):
        if "GND" not in self.nodes or len(set(self.nodes)) != len(self.nodes):
            raise ValueError("기준 노드 GND를 한 번 포함하고 노드 ID는 중복 없이 지정하세요.")
        if any(not node or len(node) > 40 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in node) for node in self.nodes):
            raise ValueError("노드 ID는 영문·숫자·_·-만 사용할 수 있습니다.")
        if len({component.id for component in self.components}) != len(self.components):
            raise ValueError("전장 부품 ID는 중복될 수 없습니다.")
        component_ids = {component.id for component in self.components}
        if any(identifier not in component_ids for identifier in self.schematic_positions):
            raise ValueError("회로도 배치는 등록된 전장 부품 ID에만 지정할 수 있습니다.")
        allowed = set(self.nodes)
        if any(component.a not in allowed or component.b not in allowed for component in self.components):
            raise ValueError("전장 부품은 등록된 노드 두 개에 연결해야 합니다.")
        if any(node not in allowed for component in self.components for node in component.signal_pins.values()):
            raise ValueError("MCU 신호 핀은 등록된 노드에 연결해야 합니다.")
        if any(node not in allowed for component in self.components for node in component.terminal_pins.values()):
            raise ValueError("추가 신호 단자는 등록된 노드에 연결해야 합니다.")
        if any(node not in allowed for component in self.components for node in component.board_supply_pins.values()):
            raise ValueError("물리 보드 전원 핀은 등록된 노드에 연결해야 합니다.")
        return self


class ElectricalBranchResult(ElectricalModel):
    id: str
    name: str
    kind: Kind
    a: str
    b: str
    part_id: str = ""
    analysis_enabled: bool = True
    current_a: float
    voltage_drop_v: float | None
    power_w: float
    resistance_ohm: float | None
    current_direction: Literal["a_to_b", "b_to_a"]
    # A paired source path is checked without treating the MCU itself as a
    # return wire. None denotes a branch that is not an MCU.
    supply_connected: bool | None = None
    return_connected: bool | None = None
    signal_pin_connected: dict[str, bool] = Field(default_factory=dict)


class ElectricalScenario(ElectricalModel):
    node_voltages_v: dict[str, float]
    components: list[ElectricalBranchResult]
    source_power_w: float
    absorbed_power_w: float
    warnings: list[str]


class ElectricalResult(ElectricalScenario):
    startup: ElectricalScenario | None = None


def _resistance(component: ElectricalComponent, startup: bool) -> float:
    if component.kind == "battery":
        return component.internal_resistance_ohm
    if component.kind == "wire":
        return component.resistivity_ohm_mm2_per_m * (component.length_mm / 1000) / component.cross_section_mm2
    if component.kind == "switch":
        return component.contact_resistance_ohm
    if component.kind == "resistor":
        return component.resistance_ohm
    if component.kind == "inductor":
        return component.winding_resistance_ohm
    current = component.startup_current_a if startup and component.kind in ("motor", "actuator") and component.startup_current_a else component.rated_current_a
    return component.rated_voltage_v / current


def _is_active(component: ElectricalComponent) -> bool:
    # ``closed`` was already persisted for switches in v1. Applying the same
    # default-True field to wires and battery output keeps old files powered.
    return (component.analysis_enabled and component.kind != "capacitor"
            and (component.kind not in ("wire", "switch", "battery") or component.closed))


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        for neighbor in graph[queue.popleft()]:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _connection_checks(workspace: ElectricalWorkspace, active: list[ElectricalComponent]):
    """Check passive wiring only; device models must not become return leads.

    A supply resistor is allowed in the power path because its voltage loss is
    evaluated by the DC solver. Signal continuity is narrower: only closed
    wires/switches are traversed, then a *different* device terminal must be
    reached. This is not a logic or firmware-functionality claim.
    """
    power_graph: dict[str, set[str]] = defaultdict(set)
    signal_graph: dict[str, set[str]] = defaultdict(set)
    signal_terminals: dict[str, set[tuple[str, str]]] = defaultdict(set)
    active_ids = {component.id for component in active}
    for component in workspace.components:
        if (component.kind in ("wire", "switch") and component.closed
                or component.id in active_ids and component.kind in ("resistor", "inductor")):
            power_graph[component.a].add(component.b)
            power_graph[component.b].add(component.a)
        if component.kind in ("wire", "switch"):
            if component.closed:
                signal_graph[component.a].add(component.b)
                signal_graph[component.b].add(component.a)
        else:
            signal_terminals[component.a].add((component.id, "terminal:a"))
            signal_terminals[component.b].add((component.id, "terminal:b"))
        if component.kind == "mcu":
            for pin, node in component.signal_pins.items():
                signal_terminals[node].add((component.id, f"pin:{pin}"))
        for pin, node in component.terminal_pins.items():
            signal_terminals[node].add((component.id, f"port:{pin}"))
    sources = [component for component in active if component.kind == "battery"]
    checks: dict[str, tuple[bool, bool, bool, dict[str, bool]]] = {}
    for component in workspace.components:
        if component.kind != "mcu":
            continue
        supply_nodes = _reachable(component.a, power_graph)
        return_nodes = _reachable(component.b, power_graph)
        supply = any(source.a in supply_nodes for source in sources)
        return_path = any(source.b in return_nodes for source in sources)
        paired = any(source.a in supply_nodes and source.b in return_nodes for source in sources)
        pins = {}
        for pin, node in component.signal_pins.items():
            from .mcu_connections import pin_aliases

            same_gpio = {f"pin:{alias}" for alias in pin_aliases(component, pin)}
            net_nodes = _reachable(node, signal_graph)
            pins[pin] = any(
                any(owner != component.id or terminal not in same_gpio
                    for owner, terminal in signal_terminals[reached])
                for reached in net_nodes
            )
        checks[component.id] = (supply, return_path, paired, pins)
    return checks


def _solve(workspace: ElectricalWorkspace, startup: bool) -> ElectricalScenario:
    active = [c for c in workspace.components if _is_active(c)]
    connections = _connection_checks(workspace, active)
    graph: dict[str, set[str]] = defaultdict(set)
    used = {"GND"}
    for component in active:
        graph[component.a].add(component.b)
        graph[component.b].add(component.a)
        used.update((component.a, component.b))
    grounded = _reachable("GND", graph)
    floating = used - grounded
    references = {"GND"}
    floating_islands: list[tuple[set[str], bool]] = []
    while floating:
        island = _reachable(min(floating), graph)
        island_sources = [c for c in active if c.kind == "battery" and c.a in island]
        # A floating island has no absolute potential. With a source we can
        # still calculate relative drops/currents; without one all its active
        # passive branches have zero current. In both cases omit absolute node
        # voltages, rather than falsely reporting an arbitrary gauge as 0 V.
        references.add(island_sources[0].b if island_sources else min(island))
        floating_islands.append((island, bool(island_sources)))
        floating -= island

    nodes = [node for node in workspace.nodes if node in used and node not in references]
    node_index = {node: i for i, node in enumerate(nodes)}
    sources = [c for c in active if c.kind == "battery"]
    size = len(nodes) + len(sources)
    matrix = np.zeros((size, size), dtype=float)
    rhs = np.zeros(size, dtype=float)

    def stamp(node: str, index: int, value: float):
        if node not in references:
            matrix[node_index[node], index] += value

    for component in active:
        if component.kind == "battery":
            index = len(nodes) + sources.index(component)
            # Positive battery current is delivered from b -> a. KCL at a is -I.
            stamp(component.a, index, -1)
            stamp(component.b, index, 1)
            if component.a not in references:
                matrix[index, node_index[component.a]] += 1
            if component.b not in references:
                matrix[index, node_index[component.b]] -= 1
            matrix[index, index] = component.internal_resistance_ohm
            rhs[index] = component.voltage_v
        else:
            resistance = _resistance(component, startup)
            if resistance <= 0 or not np.isfinite(resistance) or not np.isfinite(1 / resistance):
                raise ValueError(f"{component.name}: 회로 해석 범위를 벗어난 저항값입니다. 길이·단면적·정격을 확인하세요.")
            conductance = 1 / resistance
            for node, other in ((component.a, component.b), (component.b, component.a)):
                if node not in references:
                    matrix[node_index[node], node_index[node]] += conductance
                    if other not in references:
                        matrix[node_index[node], node_index[other]] -= conductance

    try:
        solution = np.linalg.solve(matrix, rhs) if size else np.empty(0)
    except np.linalg.LinAlgError as error:
        raise ValueError("회로를 계산할 수 없습니다. 기준 노드와 전압원 연결을 확인하세요.") from error
    if not np.all(np.isfinite(solution)):
        raise ValueError("회로 계산 결과가 유한하지 않습니다. 연결과 부품값을 확인하세요.")
    internal_voltages = {node: 0.0 for node in references}
    internal_voltages.update({node: float(solution[i]) for node, i in node_index.items()})
    voltages = {node: value for node, value in internal_voltages.items() if node in grounded}
    results: list[ElectricalBranchResult] = []
    warnings: list[str] = []
    if active and not sources:
        warnings.append("전원이 없어 이 회로의 전류가 0 A입니다. 배터리 또는 DC 전원을 연결하세요.")
    for island, powered in floating_islands:
        label = "배터리 회로" if powered else "무전원 회로"
        warnings.append(f"{label}가 기준 노드 GND와 분리되어 절대 노드 전위는 미정입니다: " + ", ".join(sorted(island)))
    source_power = 0.0
    absorbed_power = 0.0
    for component in workspace.components:
        if not component.analysis_enabled:
            supply_connected = return_connected = None
            signal_pin_connected = {}
            if component.kind == "mcu":
                supply_connected, return_connected, _, signal_pin_connected = connections[component.id]
                for pin, connected in signal_pin_connected.items():
                    if not connected:
                        warnings.append(f"{component.name}: 신호 핀 {pin}에 다른 활성 부품 단자가 연결되지 않았습니다. 단선 여부를 확인하세요.")
            warnings.append(f"{component.name}: 정격 입력 전 · 회로 계산 제외. 수동 핀 연결만 표시하며 0 A는 확인된 소비전류가 아닙니다.")
            results.append(ElectricalBranchResult(id=component.id, name=component.name, kind=component.kind,
                a=component.a, b=component.b, part_id=component.part_id, analysis_enabled=False,
                current_a=0, voltage_drop_v=None, power_w=0, resistance_ohm=None, current_direction="a_to_b",
                supply_connected=supply_connected, return_connected=return_connected,
                signal_pin_connected=signal_pin_connected))
            continue
        if not _is_active(component):
            if component.kind == "wire":
                warnings.append(f"{component.name}: 전선이 단선되어 전류가 흐르지 않습니다. 연결 상태를 확인하세요.")
            elif component.kind == "battery":
                warnings.append(f"{component.name}: 전원 인가가 꺼져 배터리 출력이 0 A입니다. 저장된 전압 정격은 변경되지 않았습니다.")
            same_network = component.b in _reachable(component.a, graph)
            drop = (internal_voltages[component.a] - internal_voltages[component.b]) if same_network and component.kind != "battery" else None
            if component.kind == "capacitor":
                warnings.append(f"{component.name}: 캐패시터는 정상상태 DC에서 개방 회로로 계산합니다. 충·방전 시간, 돌입 전류, 리플·누설·ESR은 해석하지 않습니다.")
                if drop is None:
                    warnings.append(f"{component.name}: 두 단자의 DC 전압 차가 미정이어서 전압·극성 정격을 점검할 수 없습니다.")
                else:
                    if component.capacitor_polarized and drop < 0:
                        warnings.append(f"{component.name}: 극성 캐패시터의 A(+) / B(-) 연결이 반대입니다.")
                    if component.rated_voltage_v and abs(drop) > component.rated_voltage_v * (1 + 1e-8):
                        warnings.append(f"{component.name}: {abs(drop):.3g} V로 캐패시터 전압 정격 {component.rated_voltage_v:.3g} V를 초과합니다.")
                if not component.rated_voltage_v:
                    warnings.append(f"{component.name}: 캐패시터 전압 정격이 미입력 상태입니다.")
            results.append(ElectricalBranchResult(id=component.id, name=component.name, kind=component.kind,
                a=component.a, b=component.b, part_id=component.part_id, current_a=0,
                voltage_drop_v=drop,
                power_w=0, resistance_ohm=None, current_direction="a_to_b"))
            continue
        drop = internal_voltages[component.a] - internal_voltages[component.b]
        resistance = _resistance(component, startup)
        if component.kind == "battery":
            current = float(solution[len(nodes) + sources.index(component)])
            power = -drop * current  # Negative means terminal power delivered.
            source_power += -power
            direction = "b_to_a"
            return_graph: dict[str, set[str]] = defaultdict(set)
            for other in active:
                if other.id != component.id:
                    return_graph[other.a].add(other.b)
                    return_graph[other.b].add(other.a)
            if component.b not in _reachable(component.a, return_graph):
                warnings.append(f"{component.name}: 배터리 출력이 무부하·개방 회로여서 전류가 0 A입니다. 공급 배선을 확인하세요.")
        else:
            current = drop / resistance
            power = drop * current
            absorbed_power += power
            direction = "a_to_b"
        supply_connected = return_connected = None
        signal_pin_connected = {}
        if component.kind == "mcu":
            supply_connected, return_connected, paired, signal_pin_connected = connections[component.id]
            if not supply_connected:
                warnings.append(f"{component.name}: MCU VCC가 배터리의 양극에 연결되지 않았습니다. 전원 배선을 확인하세요.")
            if not return_connected:
                warnings.append(f"{component.name}: MCU GND/리턴이 배터리의 음극에 연결되지 않았습니다. 리턴 배선을 확인하세요.")
            if supply_connected and return_connected and not paired:
                warnings.append(f"{component.name}: MCU VCC와 GND/리턴이 같은 전원에 연결되지 않았습니다.")
            for pin, connected in signal_pin_connected.items():
                if not connected:
                    warnings.append(f"{component.name}: 신호 핀 {pin}에 다른 활성 부품 단자가 연결되지 않았습니다. 단선 여부를 확인하세요.")
        results.append(ElectricalBranchResult(id=component.id, name=component.name, kind=component.kind,
            a=component.a, b=component.b, part_id=component.part_id, current_a=float(current),
            voltage_drop_v=float(drop), power_w=float(power), resistance_ohm=float(resistance),
            current_direction=direction, supply_connected=supply_connected,
            return_connected=return_connected, signal_pin_connected=signal_pin_connected))
        if component.max_current_a is not None and abs(current) > component.max_current_a * (1 + 1e-8):
            warnings.append(f"{component.name}: {abs(current):.3g} A로 지정한 최대 {component.max_current_a:.3g} A를 초과합니다.")
        if component.kind == "inductor":
            warnings.append(f"{component.name}: 정상상태 DC의 권선 저항만 계산합니다. 인덕턴스에 따른 과도응답·포화·차단 역기전력은 해석하지 않습니다.")
        if component.kind == "actuator":
            warnings.append(f"{component.name}: 입력한 정격의 DC 저항 등가 부하입니다. 실제 액추에이터의 힘·속도·스트로크·드라이버 동작은 별도 검증이 필요합니다.")
        if component.kind in ("motor", "actuator", "mcu", "load"):
            if component.kind == "mcu" and drop < 0:
                warnings.append(f"{component.name}: MCU 전원 극성이 반대입니다. 실제 연결 전에 확인하세요.")
            if abs(drop) > component.rated_voltage_v * 1.1:
                warnings.append(f"{component.name}: 정격 {component.rated_voltage_v:.3g} V보다 10% 이상 높은 전압입니다. 허용 범위를 확인하세요.")
            if abs(drop) < component.rated_voltage_v * 0.9:
                warnings.append(f"{component.name}: 정격 {component.rated_voltage_v:.3g} V보다 10% 이상 낮은 전압입니다. 제품의 최소 동작 전압을 확인하세요.")
            if component.kind in ("motor", "actuator") and not startup and abs(current) > component.rated_current_a * 1.05:
                device = "액추에이터" if component.kind == "actuator" else "모터"
                warnings.append(f"{component.name}: 명목 전류 {component.rated_current_a:.3g} A보다 5% 이상 큽니다. {device} 정격과 구동 조건을 확인하세요.")
    return ElectricalScenario(node_voltages_v=voltages, components=results,
        source_power_w=float(source_power), absorbed_power_w=float(absorbed_power), warnings=warnings)


def evaluate_electrical(raw: ElectricalWorkspace | dict) -> ElectricalResult:
    """Evaluate operating current and voltage; add a starting estimate if provided.

    A battery's positive node is ``a``. Its positive current denotes delivered
    current from ``b`` to ``a``. All other branch currents are positive ``a`` to
    ``b``. Open switches have zero current and possibly unknown voltage drop.
    """
    workspace = ElectricalWorkspace.model_validate(raw)
    running = _solve(workspace, startup=False)
    starting = _solve(workspace, startup=True) if any(c.analysis_enabled and c.kind in ("motor", "actuator") and c.startup_current_a for c in workspace.components) else None
    if any(component.signal_pins for component in workspace.components):
        from .mcu_connections import topology_warnings

        pin_warnings = topology_warnings(workspace)
        running.warnings.extend(warning for warning in pin_warnings if warning not in running.warnings)
        if starting is not None:
            starting.warnings.extend(warning for warning in pin_warnings if warning not in starting.warnings)
    return ElectricalResult(**running.model_dump(), startup=starting)
