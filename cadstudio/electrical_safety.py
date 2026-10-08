"""Read-only faults and declared limits for the stored physical wiring.

The DC model is unchanged: it is an operating-point estimate, not a board,
firmware, fuse-trip, or thermal-transient emulator. Temperature is estimated
only from explicit loss, assembled thermal resistance, ambient and duty.
"""
from __future__ import annotations

from collections import defaultdict, deque
from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .electrical import ElectricalComponent, ElectricalResult, ElectricalWorkspace, evaluate_electrical

THERMAL_REFERENCE_URL = "https://www.ti.com/lit/an/spra953c/spra953c.pdf"


class SafetyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ElectricalSafetyIssue(SafetyModel):
    code: str
    severity: Literal["error", "warning", "pending", "info"]
    component_ids: list[str] = Field(default_factory=list)
    scenario: Literal["topology", "running", "startup"] = "running"
    message: str
    measured_value: float | None = None
    limit: float | None = None
    unit: str = ""


class ElectricalSafetyBranch(SafetyModel):
    id: str
    name: str
    part_id: str = ""
    current_a: float | None = None
    startup_current_a: float | None = None
    dissipated_power_w: float | None = None
    startup_dissipated_power_w: float | None = None
    estimated_temperature_c: float | None = None
    heat_basis: Literal["resistive_loss", "declared_loss_fraction", "unknown", "excluded", "off"]


class ElectricalSafetyReport(SafetyModel):
    status: Literal["fault", "attention", "pending", "assessed"]
    dc_solved: bool
    issues: list[ElectricalSafetyIssue]
    branches: list[ElectricalSafetyBranch]
    scope: str
    thermal_reference_url: str = THERMAL_REFERENCE_URL


def _wire_path(start, end, graph):
    """A supply bypass consists solely of closed wire/contact branches."""
    queue = deque([start]); seen = {start}; previous = {}
    while queue:
        node = queue.popleft()
        if node == end:
            path = []
            while node != start:
                node, identifier = previous[node]; path.append(identifier)
            return list(reversed(path))
        for neighbor, identifier in graph[node]:
            if neighbor not in seen:
                seen.add(neighbor); previous[neighbor] = (node, identifier); queue.append(neighbor)
    return None


def _loss(component, branch):
    if branch is None or not component.analysis_enabled:
        return None, "excluded"
    if component.kind in ("battery", "wire", "switch") and not component.closed:
        return 0.0, "off"
    if component.kind == "capacitor":
        # ESR, ripple current and leakage were not specified by the DC model.
        return None, "unknown"
    if component.kind == "battery":
        return branch.current_a ** 2 * component.internal_resistance_ohm, "resistive_loss"
    if component.kind in ("wire", "switch", "resistor", "inductor"):
        return max(0.0, branch.power_w), "resistive_loss"
    if component.safety is not None and component.safety.heat_loss_fraction is not None:
        return max(0.0, branch.power_w) * component.safety.heat_loss_fraction, "declared_loss_fraction"
    return None, "unknown"


def _source_loop_through_contact(source, contact, graph):
    """Find a source/load loop without walking through a shared return twice.

    This avoids attributing every high-voltage source on a common ground to a
    fuse in an otherwise separate low-voltage circuit. It does not rate the
    interrupt capacity or sum arbitrary multiple-source loops.
    """
    def reachable(start, end, blocked):
        if start in blocked or end in blocked:
            return False
        todo = deque([start]); seen = {start}
        while todo:
            node = todo.popleft()
            if node == end:
                return True
            for other, identifier in graph[node]:
                if identifier != contact.id and other not in seen and other not in blocked:
                    seen.add(other); todo.append(other)
        return False
    return any(reachable(source.a, first, {source.b, second}) and
        reachable(second, source.b, {source.a, first})
        for first, second in ((contact.a, contact.b), (contact.b, contact.a)))


def evaluate_electrical_safety(raw: ElectricalWorkspace | dict | None,
                               result: ElectricalResult | None = None,
                               language: str = "ko") -> ElectricalSafetyReport:
    """Check topology even if missing ratings or conflicting sources block DC.

    A supplied result must belong to these same branches; normally omit it and
    solve the workspace once. No workspace, source state, fuse or file is edited.
    Missing ratings are pending, never an assertion that hardware is safe.
    """
    workspace = ElectricalWorkspace() if raw is None else ElectricalWorkspace.model_validate(raw)
    english = language == "en"
    issues = []

    def add(code, severity, components, ko, en, scenario="running", **values):
        issues.append(ElectricalSafetyIssue(code=code, severity=severity,
            component_ids=[item.id for item in components], scenario=scenario,
            message=en if english else ko, **values))

    graph = defaultdict(list)
    load_graph = defaultdict(list)
    parent = {node: node for node in workspace.nodes}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]; node = parent[node]
        return node

    for component in workspace.components:
        conducting = ((component.kind in ("wire", "switch") and component.closed) or
            (component.analysis_enabled and component.kind in ("resistor", "inductor", "motor", "actuator", "mcu", "load")))
        if conducting:
            load_graph[component.a].append((component.b, component.id))
            load_graph[component.b].append((component.a, component.id))
        if component.kind in ("wire", "switch") and component.closed:
            graph[component.a].append((component.b, component.id))
            graph[component.b].append((component.a, component.id))
            parent[find(component.a)] = find(component.b)
    sources = [item for item in workspace.components
               if item.kind == "battery" and item.analysis_enabled and item.closed]
    component_by_id = {item.id: item for item in workspace.components}
    for source in sources:
        path = _wire_path(source.a, source.b, graph)
        if path is not None:
            add("source_short_circuit", "error", [source, *[component_by_id[key] for key in path]],
                f"{source.name}: 전원 양극과 리턴이 부하 없이 전선·닫힌 접점으로 연결되어 있습니다. 쇼트 경로를 제거하세요. 퓨즈가 있더라도 자동 용단을 가정하지 않습니다.",
                f"{source.name}: source positive and return are connected through only wires/closed contacts. Remove this short path; a fuse is not assumed to have tripped.", "topology")
    for index, left in enumerate(sources):
        for right in sources[index + 1:]:
            same = find(left.a) == find(right.a) and find(left.b) == find(right.b)
            reverse = find(left.a) == find(right.b) and find(left.b) == find(right.a)
            if (same and not isclose(left.voltage_v, right.voltage_v, rel_tol=1e-8, abs_tol=1e-8)) or reverse:
                add("conflicting_sources", "error", [left, right],
                    f"{left.name} / {right.name}: 서로 다른 개방 전압 또는 반대 극성의 전원을 직접 병렬 연결했습니다. 순환전류·배터리 역충전 경로를 확인하세요.",
                    f"{left.name} / {right.name}: sources with different open-circuit voltages or reversed polarities are directly paralleled. Review circulating current and battery reverse charging.", "topology")
    if not sources:
        add("no_active_source", "info", [], "인가된 DC 전원이 없습니다. 0 A는 장치가 정상 구동된다는 뜻이 아닙니다.",
            "No DC source is enabled. Zero current does not establish successful device operation.", "topology")
    if result is not None:
        current_identity = {(item.id, item.kind, item.a, item.b, item.analysis_enabled) for item in workspace.components}
        result_identity = {(item.id, item.kind, item.a, item.b, item.analysis_enabled) for item in result.components}
        if current_identity != result_identity:
            raise ValueError("Safety report DC result does not match the supplied circuit branches.")
    else:
        try:
            result = evaluate_electrical(workspace)
        except ValueError:
            add("dc_not_solved", "pending", [], "DC 동작점을 계산하지 못했습니다. 위 결선 오류와 전원·실제 부품값을 확인하세요. 전류·열 수치는 추정하지 않았습니다.",
                "The DC operating point could not be solved. Review wiring faults, sources and actual values; current and heat were not guessed.")
    running = {item.id: item for item in result.components} if result else {}
    starting = {item.id: item for item in result.startup.components} if result and result.startup else {}
    rows = []
    for component in workspace.components:
        normal = running.get(component.id); peak = starting.get(component.id)
        enabled = component.analysis_enabled and normal is not None
        loss, basis = _loss(component, normal); peak_loss, _ = _loss(component, peak)
        temperature = None
        spec = component.safety
        if not component.analysis_enabled:
            add("analysis_excluded", "pending", [component], f"{component.name}: 동작 모델·실제 입력값이 없어 회로 계산에서 제외했습니다. 전류와 온도는 미검증입니다.",
                f"{component.name}: excluded from DC analysis because operating values/model are missing; current and temperature are unverified.")
        if spec and spec.fuse_current_a is not None:
            add("fuse_trip_not_modelled", "pending", [component], f"{component.name}: 퓨즈 {spec.fuse_current_a:g} A 정격만 확인합니다. 시간-전류 곡선·차단용량·주위온도 보정이 없어 자동 용단·보호 성공을 판정하지 않습니다.",
                f"{component.name}: only the {spec.fuse_current_a:g} A fuse rating is checked. Without a time-current curve, interrupt rating and ambient derating, trip time and protection success remain unverified.")
            if spec.max_voltage_v is None:
                add("fuse_dc_voltage_unknown", "pending", [component],
                    f"{component.name}: 확인된 DC 전압 정격이 없습니다. AC 전압 정격을 DC 차단 정격으로 사용하지 않습니다.",
                    f"{component.name}: no verified DC voltage rating is declared. An AC rating is not treated as a DC interrupt rating.")
            if spec.max_voltage_v is not None and component.closed:
                supplied = [source.voltage_v for source in sources if _source_loop_through_contact(source, component, load_graph)]
                if supplied and max(supplied) > spec.max_voltage_v * (1 + 1e-8):
                    voltage = max(supplied)
                    add("fuse_supply_voltage_exceeded", "error", [component],
                        f"{component.name}: 연결된 전원 개방 전압 {voltage:g} V가 퓨즈 DC 전압 정격 {spec.max_voltage_v:g} V를 초과합니다. 닫힌 퓨즈의 작은 전압 강하가 차단 전압을 대신하지 않습니다.",
                        f"{component.name}: connected source open-circuit voltage {voltage:g} V exceeds the fuse's DC voltage rating {spec.max_voltage_v:g} V. Small closed-contact voltage drop is not its interrupt voltage.",
                        measured_value=voltage, limit=spec.max_voltage_v, unit="V")
        for scenario, branch in (("running", normal), ("startup", peak)):
            if branch is None or not component.analysis_enabled:
                continue
            current = abs(branch.current_a)
            if component.kind == "battery" and branch.current_a < -1e-8:
                add("source_backfeed", "warning", [component],
                    f"{component.name}: 전원으로 {current:.4g} A가 역류합니다. 충전·회생을 허용하는 전원인지 확인해야 합니다.",
                    f"{component.name}: {current:.4g} A flows back into the source. Charging/regeneration capability must be established.", scenario,
                    measured_value=current, unit="A")
            if component.max_current_a is not None and current > component.max_current_a * (1 + 1e-8):
                add("current_limit_exceeded", "error", [component], f"{component.name}: {current:.4g} A로 입력한 허용 전류 {component.max_current_a:g} A를 초과했습니다.",
                    f"{component.name}: {current:.4g} A exceeds its entered current limit {component.max_current_a:g} A.", scenario,
                    measured_value=current, limit=component.max_current_a, unit="A")
            if spec and spec.fuse_current_a is not None and current > spec.fuse_current_a * (1 + 1e-8):
                add("fuse_rating_exceeded", "warning", [component], f"{component.name}: {current:.4g} A가 퓨즈 정격 {spec.fuse_current_a:g} A를 초과합니다. 퓨즈가 이미 끊어졌다고 가정하지 않습니다.",
                    f"{component.name}: {current:.4g} A exceeds fuse rating {spec.fuse_current_a:g} A; the fuse is not assumed to have opened.", scenario,
                    measured_value=current, limit=spec.fuse_current_a, unit="A")
            voltage_limit = spec.max_voltage_v if spec else None
            if voltage_limit is None and component.kind == "capacitor" and component.rated_voltage_v > 0:
                voltage_limit = component.rated_voltage_v
            if voltage_limit is not None and branch.voltage_drop_v is not None and abs(branch.voltage_drop_v) > voltage_limit * (1 + 1e-8):
                add("voltage_limit_exceeded", "error", [component], f"{component.name}: 단자 전압 {abs(branch.voltage_drop_v):.4g} V가 허용 {voltage_limit:g} V를 초과합니다.",
                    f"{component.name}: terminal voltage {abs(branch.voltage_drop_v):.4g} V exceeds maximum {voltage_limit:g} V.", scenario,
                    measured_value=abs(branch.voltage_drop_v), limit=voltage_limit, unit="V")
            if component.kind == "capacitor" and component.capacitor_polarized and branch.voltage_drop_v is not None and branch.voltage_drop_v < -1e-8:
                add("reverse_capacitor", "error", [component], f"{component.name}: 극성 캐패시터가 역방향으로 연결되었습니다.",
                    f"{component.name}: the polarized capacitor is reverse biased.", scenario)
            if component.kind == "mcu" and branch.voltage_drop_v is not None and branch.voltage_drop_v < -1e-8:
                add("reverse_board_supply", "error", [component], f"{component.name}: MCU / MPU 전원 극성이 반대입니다.",
                    f"{component.name}: the MCU / MPU supply polarity is reversed.", scenario)
            dissipated, _ = _loss(component, branch)
            if spec and spec.rated_power_w is not None and dissipated is not None and dissipated > spec.rated_power_w * (1 + 1e-8):
                add("dissipation_rating_exceeded", "error" if scenario == "running" else "warning", [component],
                    f"{component.name}: 열 손실 {dissipated:.4g} W가 입력한 연속 허용 손실 {spec.rated_power_w:g} W를 초과합니다. 기동 펄스 허용은 별도입니다.",
                    f"{component.name}: heat loss {dissipated:.4g} W exceeds entered continuous dissipation {spec.rated_power_w:g} W. Starting pulse limits are separate.", scenario,
                    measured_value=dissipated, limit=spec.rated_power_w, unit="W")
        if enabled and basis != "off":
            if component.kind in ("battery", "wire", "switch", "inductor") and component.max_current_a is None and not (spec and spec.fuse_current_a is not None):
                add("current_rating_missing", "pending", [component], f"{component.name}: 실제 배치·온도 조건의 허용 전류가 없어 과전류 여부를 확정할 수 없습니다.",
                    f"{component.name}: no current limit for the actual installation/temperature is declared; overload cannot be fully assessed.")
            if component.kind == "resistor" and not (spec and spec.rated_power_w is not None):
                add("power_rating_missing", "pending", [component], f"{component.name}: 허용 손실(W)이 없어 저항의 과부하를 평가할 수 없습니다.",
                    f"{component.name}: resistor power rating is missing, so dissipation overload cannot be assessed.")
            if loss is None:
                add("heat_loss_unknown", "pending", [component], f"{component.name}: 실제 열 손실이 미정입니다. 모터의 입력 전력 전체나 캐패시터의 0 A를 온도 근거로 사용하지 않습니다.",
                    f"{component.name}: actual heat loss is unknown. Total motor input power or a capacitor's zero settled-DC current is not a temperature estimate.")
            thermal_known = (spec is not None and spec.thermal_resistance_k_per_w is not None
                and spec.ambient_temperature_c is not None and spec.duty_cycle is not None)
            if loss is not None and thermal_known:
                temperature = spec.ambient_temperature_c + loss * spec.duty_cycle * spec.thermal_resistance_k_per_w
                if spec.max_temperature_c is not None and temperature > spec.max_temperature_c + max(1e-8, abs(spec.max_temperature_c) * 1e-8):
                    add("temperature_limit_exceeded", "error", [component], f"{component.name}: 입력한 냉각·환경 조건의 정상상태 추정 {temperature:.4g} °C가 허용 {spec.max_temperature_c:g} °C를 초과합니다.",
                        f"{component.name}: steady-state estimate {temperature:.4g} °C for the entered cooling/environment exceeds {spec.max_temperature_c:g} °C.",
                        measured_value=temperature, limit=spec.max_temperature_c, unit="°C")
                if spec.max_temperature_c is None:
                    add("temperature_rating_missing", "pending", [component], f"{component.name}: 추정 온도는 있지만 허용 온도가 없어 과열 판정은 미정입니다.",
                        f"{component.name}: temperature was estimated, but overheating remains unverified without a temperature limit.")
            elif loss is not None:
                add("thermal_conditions_missing", "pending", [component], f"{component.name}: 실제 조립의 열저항·주위온도·듀티가 없어 온도를 계산하지 않았습니다. 손실(W)만 표시합니다.",
                    f"{component.name}: assembled thermal resistance, ambient or duty is missing. Only heat loss in watts is shown; temperature was not guessed.")
        rows.append(ElectricalSafetyBranch(id=component.id, name=component.name, part_id=component.part_id,
            current_a=normal.current_a if enabled else None,
            startup_current_a=peak.current_a if enabled and peak else None,
            dissipated_power_w=loss, startup_dissipated_power_w=peak_loss,
            estimated_temperature_c=temperature, heat_basis=basis))
    status = ("fault" if any(item.severity == "error" for item in issues) else
              "attention" if any(item.severity == "warning" for item in issues) else
              "pending" if any(item.severity == "pending" for item in issues) else "assessed")
    scope = ("Stored wiring and declared DC limits only. Temperature is a steady-state average-power estimate for explicitly entered assembled conditions; thermal transients, hotspots, fuse trip, motor control and hardware safety certification are outside this report."
             if english else "저장된 배선·입력한 DC 정격만 검토합니다. 온도는 명시한 실제 조립 조건의 평균 손실 기반 정상상태 추정입니다. 열 과도·국부 과열·퓨즈 용단·모터 제어·실물 안전 인증은 판정하지 않습니다.")
    return ElectricalSafetyReport(status=status, dc_solved=result is not None,
        issues=issues, branches=rows, scope=scope)
