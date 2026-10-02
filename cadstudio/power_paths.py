"""Build one explicit, independently named DC power path in an electrical workspace.

The path uses only existing circuit component kinds. Values supplied by the
caller are operating assumptions, not product certifications or firmware tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .electrical import ElectricalResult, ElectricalWorkspace, evaluate_electrical


REQUIRED_POWER_INPUTS = {
    "source_voltage_v": "배터리 전압(V)",
    "positive_wire_length_mm": "공급선 길이(mm)",
    "positive_wire_cross_section_mm2": "공급선 단면적(mm²)",
    "return_wire_length_mm": "리턴선 길이(mm)",
    "return_wire_cross_section_mm2": "리턴선 단면적(mm²)",
    "load_voltage_v": "부하 정격 전압(V)",
    "load_current_a": "부하 정격 전류(A)",
}


class PowerInputRequired(ValueError):
    """A user or verified source must supply these operating values before retry."""

    def __init__(self, missing_fields: tuple[str, ...]):
        self.missing_fields = missing_fields
        labels = ", ".join(f"{REQUIRED_POWER_INPUTS[field]} ({field})" for field in missing_fields)
        super().__init__(f"전원 경로 설계에 실제 입력값이 필요합니다: {labels}. 값을 확인한 뒤 다시 요청하세요.")


def require_power_inputs(raw_spec: dict | "PowerPathSpec") -> None:
    """Do not let a planner's absent/zero placeholders become guessed ratings."""
    if isinstance(raw_spec, PowerPathSpec):
        return
    missing = []
    for field in REQUIRED_POWER_INPUTS:
        value = raw_spec.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            missing.append(field)
    if missing:
        raise PowerInputRequired(tuple(missing))


class PowerPathSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(default="전원 경로", min_length=1, max_length=60)
    source_voltage_v: float = Field(gt=0, le=1000)
    source_internal_resistance_ohm: float = Field(default=0, ge=0, le=10000)
    source_max_current_a: float | None = Field(default=None, gt=0, le=10000)
    source_enabled: bool = True
    source_part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")

    switch_closed: bool = True
    switch_contact_resistance_ohm: float = Field(default=0.01, gt=0, le=1000)
    switch_max_current_a: float | None = Field(default=None, gt=0, le=10000)
    switch_part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")

    positive_wire_length_mm: float = Field(gt=0, le=1e7)
    positive_wire_cross_section_mm2: float = Field(gt=0, le=1e5)
    positive_wire_resistivity_ohm_mm2_per_m: float = Field(default=0.01724, gt=0, le=100)
    positive_wire_catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    positive_wire_max_current_a: float | None = Field(default=None, gt=0, le=10000)
    positive_wire_part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")

    return_wire_length_mm: float = Field(gt=0, le=1e7)
    return_wire_cross_section_mm2: float = Field(gt=0, le=1e5)
    return_wire_resistivity_ohm_mm2_per_m: float = Field(default=0.01724, gt=0, le=100)
    return_wire_catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    return_wire_max_current_a: float | None = Field(default=None, gt=0, le=10000)
    return_wire_part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")

    load_kind: Literal["load", "motor", "mcu"] = "load"
    load_voltage_v: float = Field(gt=0, le=1000)
    load_current_a: float = Field(gt=0, le=10000)
    load_startup_current_a: float | None = Field(default=None, gt=0, le=10000)
    load_part_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]*$")

    @model_validator(mode="after")
    def motor_only_startup(self):
        if self.load_startup_current_a is not None and self.load_kind != "motor":
            raise ValueError("기동 전류는 모터 부하에만 입력할 수 있습니다.")
        return self


@dataclass(frozen=True)
class CapacityCheck:
    label: str
    current_a: float
    entered_limit_a: float | None
    status: Literal["unverified", "within_entered_limit", "over_entered_limit"]
    margin_a: float | None


@dataclass(frozen=True)
class PowerPathReport:
    state: Literal["source_off", "switch_open", "energized", "no_current"]
    current_a: float
    load_voltage_v: float | None
    open_circuit_power_w: float
    terminal_output_w: float
    battery_internal_loss_w: float
    positive_wire_drop_v: float
    positive_wire_loss_w: float
    return_wire_drop_v: float
    return_wire_loss_w: float
    switch_loss_w: float
    load_power_w: float
    balance_error_w: float
    capacities: tuple[CapacityCheck, ...]
    startup_current_a: float | None
    startup_capacities: tuple[CapacityCheck, ...]


@dataclass(frozen=True)
class PowerPathBuild:
    workspace: ElectricalWorkspace
    result: ElectricalResult
    ids: dict[str, str]
    report: PowerPathReport


def _unique_prefix(workspace: ElectricalWorkspace) -> str:
    used_ids = {component.id for component in workspace.components}
    used_nodes = set(workspace.nodes)
    for number in range(1, 10000):
        prefix = f"powerpath_{number:04d}"
        ids = {f"{prefix}_{suffix}" for suffix in ("source", "switch", "feed", "load", "return")}
        nodes = {f"PWR{number:04d}_{suffix}" for suffix in ("SOURCE", "SWITCHED", "LOAD", "RETURN")}
        if ids.isdisjoint(used_ids) and nodes.isdisjoint(used_nodes):
            return prefix
    raise ValueError("사용 가능한 전원 경로 ID가 없습니다.")


def _wire_resistance_fields(catalog_id: str, area_mm2: float, manual_resistivity: float) -> dict:
    if not catalog_id:
        return {"resistivity_ohm_mm2_per_m": manual_resistivity}
    from .mechanical_catalog import get_catalog_entry
    entry = get_catalog_entry(catalog_id)
    if entry is None or entry.wire_spec is None:
        raise ValueError(f"{catalog_id}: 정확한 전선 SKU의 제조사 명목 DC 저항 자료가 없습니다.")
    # The existing circuit model stores rho and computes rho * length / area.
    # Choosing rho = measured/source DCR per metre * entered area makes the
    # solver use exactly the source-backed DCR, without inferring an AWG area.
    return {"resistivity_ohm_mm2_per_m": entry.wire_spec.dcr_ohm_per_m * area_mm2,
            "catalog_id": entry.catalog_id, "source_url": entry.source_url}


def build_power_path(existing: ElectricalWorkspace | dict | None, raw_spec: PowerPathSpec | dict) -> PowerPathBuild:
    """Append, validate, and calculate a five-component single-source loop.

    The caller's workspace is never mutated. The only common net is GND; all
    other new nodes and identifiers are unique, so old branches are preserved.
    """
    require_power_inputs(raw_spec)
    spec = PowerPathSpec.model_validate(raw_spec)
    workspace = ElectricalWorkspace.model_validate(existing or {"nodes": ["GND"], "components": []})
    prefix = _unique_prefix(workspace)
    number = prefix.split("_")[-1]
    src, switched, load_plus, load_minus = (f"PWR{number}_{suffix}" for suffix in
                                            ("SOURCE", "SWITCHED", "LOAD", "RETURN"))
    ids = {key: f"{prefix}_{key}" for key in ("source", "switch", "feed", "load", "return")}
    names = {
        "source": f"{spec.name} · 배터리",
        "switch": f"{spec.name} · 스위치",
        "feed": f"{spec.name} · 공급선",
        "load": f"{spec.name} · 부하",
        "return": f"{spec.name} · 리턴선",
    }
    parts = [
        dict(id=ids["source"], name=names["source"], kind="battery", a=src, b="GND",
             voltage_v=spec.source_voltage_v, internal_resistance_ohm=spec.source_internal_resistance_ohm,
             max_current_a=spec.source_max_current_a, closed=spec.source_enabled, part_id=spec.source_part_id),
        dict(id=ids["switch"], name=names["switch"], kind="switch", a=src, b=switched,
             closed=spec.switch_closed, contact_resistance_ohm=spec.switch_contact_resistance_ohm,
             max_current_a=spec.switch_max_current_a, part_id=spec.switch_part_id),
        dict(id=ids["feed"], name=names["feed"], kind="wire", a=switched, b=load_plus,
             length_mm=spec.positive_wire_length_mm, cross_section_mm2=spec.positive_wire_cross_section_mm2,
             **_wire_resistance_fields(spec.positive_wire_catalog_id,
                                       spec.positive_wire_cross_section_mm2,
                                       spec.positive_wire_resistivity_ohm_mm2_per_m),
             max_current_a=spec.positive_wire_max_current_a, part_id=spec.positive_wire_part_id),
        dict(id=ids["load"], name=names["load"], kind=spec.load_kind, a=load_plus, b=load_minus,
             rated_voltage_v=spec.load_voltage_v, rated_current_a=spec.load_current_a,
             part_id=spec.load_part_id, **({"startup_current_a": spec.load_startup_current_a}
                                       if spec.load_startup_current_a is not None else {})),
        dict(id=ids["return"], name=names["return"], kind="wire", a=load_minus, b="GND",
             length_mm=spec.return_wire_length_mm, cross_section_mm2=spec.return_wire_cross_section_mm2,
             **_wire_resistance_fields(spec.return_wire_catalog_id,
                                       spec.return_wire_cross_section_mm2,
                                       spec.return_wire_resistivity_ohm_mm2_per_m),
             max_current_a=spec.return_wire_max_current_a, part_id=spec.return_wire_part_id),
    ]
    candidate = ElectricalWorkspace.model_validate({**workspace.model_dump(),
        "nodes": [*workspace.nodes, src, switched, load_plus, load_minus],
        "components": [*[component.model_dump() for component in workspace.components], *parts]})
    result = evaluate_electrical(candidate)
    branches = {branch.id: branch for branch in result.components}
    source = branches[ids["source"]]
    current = abs(source.current_a)
    feed = branches[ids["feed"]]
    return_wire = branches[ids["return"]]
    switch = branches[ids["switch"]]
    load = branches[ids["load"]]
    limits = (
        ("배터리", spec.source_max_current_a),
        ("스위치", spec.switch_max_current_a),
        ("공급선", spec.positive_wire_max_current_a),
        ("리턴선", spec.return_wire_max_current_a),
    )
    capacities = tuple(_capacity(label, current, limit) for label, limit in limits)
    # The solver's startup scenario is workspace-wide. Show a startup row for
    # this newly built path only when THIS load supplied a motor-start value;
    # an unrelated old motor must not make a new MCU path appear to start.
    startup_current = (abs(next(branch.current_a for branch in result.startup.components
                               if branch.id == ids["source"]))
                       if spec.load_kind == "motor" and spec.load_startup_current_a is not None
                       and result.startup is not None else None)
    startup_capacities = (tuple(_capacity(label, startup_current, limit) for label, limit in limits)
                          if startup_current is not None else ())
    open_power = spec.source_voltage_v * current
    internal_loss = current * current * spec.source_internal_resistance_ohm
    terminal_output = -source.power_w if spec.source_enabled else 0.0
    feed_loss = feed.power_w
    return_loss = return_wire.power_w
    switch_loss = switch.power_w
    load_power = load.power_w
    report = PowerPathReport(
        state="source_off" if not spec.source_enabled else "switch_open" if not spec.switch_closed
              else "no_current" if current < 1e-12 else "energized",
        current_a=current, load_voltage_v=load.voltage_drop_v,
        open_circuit_power_w=open_power, terminal_output_w=terminal_output,
        battery_internal_loss_w=internal_loss,
        positive_wire_drop_v=abs(feed.voltage_drop_v or 0.0), positive_wire_loss_w=feed_loss,
        return_wire_drop_v=abs(return_wire.voltage_drop_v or 0.0), return_wire_loss_w=return_loss,
        switch_loss_w=switch_loss, load_power_w=load_power,
        balance_error_w=abs(terminal_output - (feed_loss + return_loss + switch_loss + load_power)),
        capacities=capacities, startup_current_a=startup_current,
        startup_capacities=startup_capacities)
    return PowerPathBuild(candidate, result, ids, report)


def _capacity(label: str, current: float, limit: float | None) -> CapacityCheck:
    if limit is None:
        return CapacityCheck(label, current, None, "unverified", None)
    margin = limit - current
    return CapacityCheck(label, current, limit,
                         "over_entered_limit" if margin < -limit * 1e-8 else "within_entered_limit", margin)


def format_power_path_report(build: PowerPathBuild, language: str = "ko") -> str:
    """Plain-language report of this bounded DC approximation, never a safety certification."""
    report = build.report
    if language == "en":
        state = {"source_off": "battery output OFF", "switch_open": "switch open",
                 "no_current": "0 A; inspect the wiring", "energized": "powered in the DC model"}[report.state]
        load_voltage = "undetermined" if report.load_voltage_v is None else f"{report.load_voltage_v:.5g} V"
        lines = [
            f"Path state: {state}",
            f"Current {report.current_a:.5g} A · load terminal voltage {load_voltage}",
            f"Source open-circuit voltage × current {report.open_circuit_power_w:.5g} W · terminal output {report.terminal_output_w:.5g} W",
            f"Battery internal I²R {report.battery_internal_loss_w:.5g} W · positive lead I²R {report.positive_wire_loss_w:.5g} W · return lead I²R {report.return_wire_loss_w:.5g} W",
            f"Positive/return lead drops {report.positive_wire_drop_v:.5g} / {report.return_wire_drop_v:.5g} V · switch loss {report.switch_loss_w:.5g} W · load power {report.load_power_w:.5g} W",
            f"Power-balance residual {report.balance_error_w:.3g} W",
            "Checks against entered limits only; not a product rating or safety certification:",
        ]
        def capacity_line(capacity, prefix=""):
            label = prefix + capacity.label
            if capacity.status == "unverified":
                return f"WARN · {label}: current limit not entered; capacity unverified"
            if capacity.status == "over_entered_limit":
                return f"FAIL · {label}: {capacity.current_a:.4g} A > entered limit {capacity.entered_limit_a:.4g} A"
            return f"CHECK · {label}: {capacity.margin_a:.4g} A below entered limit"
        names = {"배터리": "Battery", "스위치": "Switch", "공급선": "Positive lead", "리턴선": "Return lead"}
        for capacity in report.capacities:
            translated = CapacityCheck(names[capacity.label], capacity.current_a,
                                       capacity.entered_limit_a, capacity.status, capacity.margin_a)
            lines.append(capacity_line(translated))
        if report.startup_current_a is not None:
            lines.append(f"Separate motor-starting resistance estimate: {report.startup_current_a:.5g} A · not PWM or driver simulation")
            for capacity in report.startup_capacities:
                translated = CapacityCheck(names[capacity.label], capacity.current_a,
                                           capacity.entered_limit_a, capacity.status, capacity.margin_a)
                lines.append(capacity_line(translated, "Starting "))
        if build.result.warnings:
            lines.extend("DC solver note (Korean): " + warning for warning in build.result.warnings)
        lines.append("DC resistance-equivalent model only. Firmware, motor drivers and physical wiring are not verified.")
        return "\n".join(lines)
    state = {"source_off": "배터리 출력 OFF", "switch_open": "스위치 열림",
             "no_current": "전류 0 A · 결선 확인 필요", "energized": "DC 모델에서 전원 경로 도통"}[report.state]
    load_voltage = "미정" if report.load_voltage_v is None else f"{report.load_voltage_v:.5g} V"
    lines = [
        f"경로 상태: {state}",
        f"전류 {report.current_a:.5g} A · 부하 단자 전압 {load_voltage}",
        f"배터리 개방전압×전류 {report.open_circuit_power_w:.5g} W · 단자 출력 {report.terminal_output_w:.5g} W",
        f"배터리 내부 I²R {report.battery_internal_loss_w:.5g} W · 공급선 I²R {report.positive_wire_loss_w:.5g} W · 리턴선 I²R {report.return_wire_loss_w:.5g} W",
        f"공급선/리턴선 전압강하 {report.positive_wire_drop_v:.5g} / {report.return_wire_drop_v:.5g} V · 스위치 손실 {report.switch_loss_w:.5g} W · 부하 소비 {report.load_power_w:.5g} W",
        f"전력 회계 잔차 {report.balance_error_w:.3g} W",
        "입력한 정격 기준 확인 · 제품 허용 범위나 제작 안전 인증은 아닙니다:",
    ]
    for capacity in report.capacities:
        if capacity.status == "unverified":
            lines.append(f"WARN · {capacity.label}: 허용 전류 미입력 → 용량 미검증")
        elif capacity.status == "over_entered_limit":
            lines.append(f"FAIL · {capacity.label}: {capacity.current_a:.4g} A > 입력 한계 {capacity.entered_limit_a:.4g} A")
        else:
            lines.append(f"CHECK · {capacity.label}: 입력 한계보다 {capacity.margin_a:.4g} A 낮음")
    if report.startup_current_a is not None:
        lines.append(f"모터 기동 별도 저항 등가 근사: {report.startup_current_a:.5g} A · PWM/드라이버 해석 아님")
        for capacity in report.startup_capacities:
            if capacity.status == "unverified":
                lines.append(f"WARN · 기동 {capacity.label}: 허용 전류 미입력 → 용량 미검증")
            elif capacity.status == "over_entered_limit":
                lines.append(f"FAIL · 기동 {capacity.label}: {capacity.current_a:.4g} A > 입력 한계 {capacity.entered_limit_a:.4g} A")
            else:
                lines.append(f"CHECK · 기동 {capacity.label}: 입력 한계보다 {capacity.margin_a:.4g} A 낮음")
    if build.result.warnings:
        lines.extend("DC 주의: " + warning for warning in build.result.warnings)
    lines.append("DC 저항 등가 모델만 계산합니다. MCU 코드·스위칭 회로·모터 제어·실물 배선은 검증하지 않습니다.")
    return "\n".join(lines)
