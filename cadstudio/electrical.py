"""Small, deterministic DC wiring study attached to a CAD design.

This is a resistive operating-point calculation, not SPICE, firmware execution,
or a physical motor/driver model.  A motor's rated and optional starting current
define two *separate* equivalent-resistance estimates at its rated voltage.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Literal
from urllib.parse import urlsplit

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ElectricalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Identifier = str
Kind = Literal["battery", "wire", "switch", "resistor", "load", "motor", "mcu"]


class ElectricalComponent(ElectricalModel):
    id: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    kind: Kind
    a: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    b: Identifier = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    source_url: str = Field(default="", max_length=500)
    voltage_v: float = Field(default=0, ge=0, le=1000)
    internal_resistance_ohm: float = Field(default=0, ge=0, le=10000)
    resistance_ohm: float = Field(default=0, ge=0, le=1e9)
    rated_voltage_v: float = Field(default=0, ge=0, le=1000)
    rated_current_a: float = Field(default=0, ge=0, le=10000)
    max_current_a: float | None = Field(default=None, gt=0, le=10000)
    startup_current_a: float | None = Field(default=None, gt=0, le=10000)
    length_mm: float = Field(default=0, ge=0, le=1e7)
    cross_section_mm2: float = Field(default=0, ge=0, le=1e5)
    # Copper near room temperature, in ohm * mm^2 / m. User may override.
    resistivity_ohm_mm2_per_m: float = Field(default=0.01724, gt=0, le=100)
    closed: bool = True
    contact_resistance_ohm: float = Field(default=0.01, gt=0, le=1000)
    # MCU signal pins are passive net labels. They are not included in the DC
    # equivalent resistance of the MCU and do not simulate digital logic.
    signal_pins: dict[str, Identifier] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def required_values(self):
        if self.a == self.b:
            raise ValueError("전장 부품 양 끝은 서로 다른 노드에 연결해야 합니다.")
        if self.kind == "battery" and self.voltage_v <= 0:
            raise ValueError("배터리의 개방 전압(V)을 입력하세요.")
        if self.kind == "wire" and (self.length_mm <= 0 or self.cross_section_mm2 <= 0):
            raise ValueError("전선의 길이(mm)와 단면적(mm²)을 입력하세요.")
        if self.kind == "resistor" and self.resistance_ohm <= 0:
            raise ValueError("저항값(Ω)을 입력하세요.")
        if self.kind in ("load", "motor", "mcu") and (self.rated_voltage_v <= 0 or self.rated_current_a <= 0):
            raise ValueError("부하의 정격 전압(V)과 전류(A)를 입력하세요.")
        if self.startup_current_a is not None and self.kind != "motor":
            raise ValueError("기동 전류는 모터에만 지정할 수 있습니다.")
        if self.signal_pins and self.kind != "mcu":
            raise ValueError("신호 핀은 MCU에만 지정할 수 있습니다.")
        if self.source_url:
            parsed = urlsplit(self.source_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or any(character.isspace() or ord(character) < 32 for character in self.source_url)):
                raise ValueError("제품 사양 출처는 안전한 HTTPS 주소로 지정하세요.")
        for pin, node in self.signal_pins.items():
            if (not pin or len(pin) > 40 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in pin)
                    or not node or len(node) > 40):
                raise ValueError("MCU 핀 이름과 노드 ID는 영문·숫자·_·-만 사용할 수 있습니다.")
        return self


class ElectricalWorkspace(ElectricalModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="전장 회로", min_length=1, max_length=100)
    nodes: list[Identifier] = Field(default_factory=lambda: ["GND"], min_length=1, max_length=128)
    components: list[ElectricalComponent] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def valid_netlist(self):
        if "GND" not in self.nodes or len(set(self.nodes)) != len(self.nodes):
            raise ValueError("기준 노드 GND를 한 번 포함하고 노드 ID는 중복 없이 지정하세요.")
        if any(not node or len(node) > 40 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in node) for node in self.nodes):
            raise ValueError("노드 ID는 영문·숫자·_·-만 사용할 수 있습니다.")
        if len({component.id for component in self.components}) != len(self.components):
            raise ValueError("전장 부품 ID는 중복될 수 없습니다.")
        allowed = set(self.nodes)
        if any(component.a not in allowed or component.b not in allowed for component in self.components):
            raise ValueError("전장 부품은 등록된 노드 두 개에 연결해야 합니다.")
        if any(node not in allowed for component in self.components for node in component.signal_pins.values()):
            raise ValueError("MCU 신호 핀은 등록된 노드에 연결해야 합니다.")
        return self


class ElectricalBranchResult(ElectricalModel):
    id: str
    name: str
    kind: Kind
    a: str
    b: str
    part_id: str = ""
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
    current = component.startup_current_a if startup and component.kind == "motor" and component.startup_current_a else component.rated_current_a
    return component.rated_voltage_v / current


def _is_active(component: ElectricalComponent) -> bool:
    # ``closed`` was already persisted for switches in v1. Applying the same
    # default-True field to wires and battery output keeps old files powered.
    return component.kind not in ("wire", "switch", "battery") or component.closed


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
    for component in active:
        if component.kind in ("wire", "switch", "resistor"):
            power_graph[component.a].add(component.b)
            power_graph[component.b].add(component.a)
        if component.kind in ("wire", "switch"):
            signal_graph[component.a].add(component.b)
            signal_graph[component.b].add(component.a)
        else:
            signal_terminals[component.a].add((component.id, "terminal:a"))
            signal_terminals[component.b].add((component.id, "terminal:b"))
        if component.kind == "mcu":
            for pin, node in component.signal_pins.items():
                signal_terminals[node].add((component.id, f"pin:{pin}"))
    sources = [component for component in active if component.kind == "battery"]
    checks: dict[str, tuple[bool, bool, bool, dict[str, bool]]] = {}
    for component in active:
        if component.kind != "mcu":
            continue
        supply_nodes = _reachable(component.a, power_graph)
        return_nodes = _reachable(component.b, power_graph)
        supply = any(source.a in supply_nodes for source in sources)
        return_path = any(source.b in return_nodes for source in sources)
        paired = any(source.a in supply_nodes and source.b in return_nodes for source in sources)
        pins = {}
        for pin, node in component.signal_pins.items():
            net_nodes = _reachable(node, signal_graph)
            pins[pin] = any(
                any(owner != component.id or terminal in ("terminal:a", "terminal:b")
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
        if not _is_active(component):
            if component.kind == "wire":
                warnings.append(f"{component.name}: 전선이 단선되어 전류가 흐르지 않습니다. 연결 상태를 확인하세요.")
            elif component.kind == "battery":
                warnings.append(f"{component.name}: 전원 인가가 꺼져 배터리 출력이 0 A입니다. 저장된 전압 정격은 변경되지 않았습니다.")
            same_network = component.b in _reachable(component.a, graph)
            results.append(ElectricalBranchResult(id=component.id, name=component.name, kind=component.kind,
                a=component.a, b=component.b, part_id=component.part_id, current_a=0,
                voltage_drop_v=(internal_voltages[component.a] - internal_voltages[component.b]) if same_network and component.kind!="battery" else None,
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
        if component.kind in ("motor", "mcu", "load"):
            if component.kind == "mcu" and drop < 0:
                warnings.append(f"{component.name}: MCU 전원 극성이 반대입니다. 실제 연결 전에 확인하세요.")
            if abs(drop) > component.rated_voltage_v * 1.1:
                warnings.append(f"{component.name}: 정격 {component.rated_voltage_v:.3g} V보다 10% 이상 높은 전압입니다. 허용 범위를 확인하세요.")
            if abs(drop) < component.rated_voltage_v * 0.9:
                warnings.append(f"{component.name}: 정격 {component.rated_voltage_v:.3g} V보다 10% 이상 낮은 전압입니다. 제품의 최소 동작 전압을 확인하세요.")
            if component.kind == "motor" and not startup and abs(current) > component.rated_current_a * 1.05:
                warnings.append(f"{component.name}: 명목 전류 {component.rated_current_a:.3g} A보다 5% 이상 큽니다. 모터 정격과 구동 조건을 확인하세요.")
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
    starting = _solve(workspace, startup=True) if any(c.kind == "motor" and c.startup_current_a for c in workspace.components) else None
    return ElectricalResult(**running.model_dump(), startup=starting)
