"""Read-only real-world evidence compared with the existing DC wiring study.

No measurement is acquired here. Even a ``measured`` reading is entered by a
user; its instrument, operating conditions and connection must be checked.
Photos and symptoms cannot prove continuity, ampacity, a fuse trip or safety.
"""
from __future__ import annotations

from collections import defaultdict, deque
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .electrical import ElectricalWorkspace, evaluate_electrical
from .electrical_safety import evaluate_electrical_safety

MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_TOTAL_PHOTO_BYTES = 30_000_000


class DiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DiagnosticPhoto(DiagnosisModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=260)
    path: str = Field(min_length=1, max_length=2000)
    size_bytes: int = Field(gt=0, le=MAX_PHOTO_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def inspect_photo(path: str | Path, identifier: str) -> DiagnosticPhoto:
    """Bounded local attachment metadata; does not perform visual diagnosis.

    Native UI and Codex transport additionally validate decoding/pixel bounds.
    Re-read before transmission to catch deleted/replaced attachments.
    """
    target = Path(path).expanduser().resolve(strict=True)
    if not target.is_file() or target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("사진은 PNG, JPEG, WebP 파일이어야 합니다. / Use a PNG, JPEG or WebP image.")
    size = target.stat().st_size
    if not 0 < size <= MAX_PHOTO_BYTES:
        raise ValueError("사진 한 장은 8 MiB 이하여야 합니다. / Each photo must be at most 8 MiB.")
    with target.open("rb") as source:
        content = source.read(MAX_PHOTO_BYTES + 1)
    if len(content) != size or len(content) > MAX_PHOTO_BYTES:
        raise ValueError("사진 파일이 변경되었습니다. 다시 첨부하세요. / Reattach the changed photo.")
    valid = ((target.suffix.lower() == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
        (target.suffix.lower() in (".jpg", ".jpeg") and content.startswith(b"\xff\xd8\xff")) or
        (target.suffix.lower() == ".webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP"))
    if not valid:
        raise ValueError("사진 확장자와 내용이 일치하지 않습니다. / Image extension and content disagree.")
    return DiagnosticPhoto(id=identifier, name=target.name, path=str(target), size_bytes=size,
        sha256=sha256(content).hexdigest())


class DiagnosticMeasurement(DiagnosisModel):
    id: str = Field(min_length=1, max_length=40)
    quantity: Literal["voltage", "current", "resistance", "continuity", "temperature"]
    value: float | None = Field(default=None, ge=-1e9, le=1e9)
    outcome: Literal["reading", "open"] = "reading"
    component_id: str = Field(default="", max_length=40)
    node_a: str = Field(default="", max_length=40)
    node_b: str = Field(default="", max_length=40)
    provenance: Literal["measured", "user_reported"] = "user_reported"
    power_state: Literal["powered", "unpowered", "unknown"] = "unknown"
    isolated: bool = False
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def reading_contract(self):
        if self.outcome == "open":
            if self.quantity != "resistance" or self.value is not None:
                raise ValueError("OL/open is only a resistance reading with no numeric value.")
        elif self.value is None:
            raise ValueError("A numeric reading is required; unknown is an omitted measurement.")
        if self.quantity in ("resistance", "continuity") and self.value is not None and self.value < 0:
            raise ValueError("Resistance and continuity cannot be negative.")
        if self.quantity == "continuity" and self.value not in (0, 1):
            raise ValueError("Continuity uses 1 = conducts, 0 = no continuity.")
        if self.quantity == "temperature" and self.value < -273.15:
            raise ValueError("Temperature cannot be below absolute zero.")
        if bool(self.node_a) != bool(self.node_b) or self.node_a and self.node_a == self.node_b:
            raise ValueError("Select two different measurement nodes.")
        if self.component_id and self.node_a:
            raise ValueError("Specify a component OR a node pair for a measurement.")
        if not self.component_id and not self.node_a:
            raise ValueError("A measurement needs a component or a node pair.")
        if self.quantity in ("current", "temperature") and not self.component_id:
            raise ValueError("Current and temperature readings need a component target.")
        return self


class ElectricalDiagnosisRequest(DiagnosisModel):
    symptoms: str = Field(default="", max_length=8000)
    operating_context: str = Field(default="", max_length=4000)
    selected_component_id: str = Field(default="", max_length=40)
    measurements: list[DiagnosticMeasurement] = Field(default_factory=list, max_length=64)
    photos: list[DiagnosticPhoto] = Field(default_factory=list, max_length=MAX_PHOTOS)

    @model_validator(mode="after")
    def bounded_unique(self):
        for values in (self.measurements, self.photos):
            if len({item.id for item in values}) != len(values):
                raise ValueError("Evidence IDs must be unique within each evidence type.")
        if sum(item.size_bytes for item in self.photos) > MAX_TOTAL_PHOTO_BYTES:
            raise ValueError("첨부 사진 합계는 30 MB 이하여야 합니다. / Photos total at most 30 MB.")
        return self


class DiagnosticEvidence(DiagnosisModel):
    basis: Literal["netlist", "dc_estimate", "entered_measurement", "user_report", "photo_hypothesis"]
    reference: str = ""
    detail: str
    value: float | None = None
    unit: str = ""


class DiagnosticFinding(DiagnosisModel):
    code: str
    severity: Literal["error", "warning", "pending", "info"]
    basis: Literal["netlist", "dc_estimate", "entered_measurement", "user_report", "photo_hypothesis"]
    component_ids: list[str] = Field(default_factory=list)
    message: str
    evidence: list[DiagnosticEvidence] = Field(default_factory=list)
    confirmations: list[str] = Field(default_factory=list)


class ElectricalDiagnosticReport(DiagnosisModel):
    schema_version: Literal[1] = 1
    status: Literal["fault_in_inputs", "needs_confirmation", "reviewed"]
    language: Literal["ko", "en"]
    workspace_name: str
    workspace_sha256: str
    available_component_ids: list[str]
    request: ElectricalDiagnosisRequest
    findings: list[DiagnosticFinding]
    unknowns: list[str]
    dc_solved: bool
    expected_branches: list[dict]
    scope: str
    ai_summary: str = ""
    ai_model: str = ""


def _reachable(node, graph):
    seen = {node}; queue = deque([node])
    while queue:
        for other in graph[queue.popleft()]:
            if other not in seen:
                seen.add(other); queue.append(other)
    return seen


def diagnose_electrical(raw: ElectricalWorkspace | dict | None,
        request: ElectricalDiagnosisRequest | dict | None = None, *, language="ko") -> ElectricalDiagnosticReport:
    """Compare actual entered evidence with model expectations, without edits.

    ``fault_in_inputs`` establishes a fault in entered wiring/ratings/readings,
    never that the actual device was inspected, powered or proven defective.
    """
    workspace = ElectricalWorkspace() if raw is None else ElectricalWorkspace.model_validate(raw).model_copy(deep=True)
    request = ElectricalDiagnosisRequest.model_validate(request or {}).model_copy(deep=True)
    lang = "en" if language == "en" else "ko"
    def word(ko, en): return en if lang == "en" else ko
    by_id = {item.id: item for item in workspace.components}
    if request.selected_component_id and request.selected_component_id not in by_id:
        raise ValueError("진단 대상 부품이 현재 회로에 없습니다. / Diagnosis target is not in this circuit.")
    for measurement in request.measurements:
        if measurement.component_id and measurement.component_id not in by_id:
            raise ValueError("측정 대상 부품이 현재 회로에 없습니다. / Measurement component is not in this circuit.")
        if measurement.node_a and not {measurement.node_a, measurement.node_b} <= set(workspace.nodes):
            raise ValueError("측정 노드가 현재 회로에 없습니다. / Measurement nodes are not in this circuit.")
    try: result = evaluate_electrical(workspace)
    except ValueError: result = None
    safety = evaluate_electrical_safety(workspace, result=result, language=lang)
    expected = {item.id: item for item in result.components} if result else {}
    findings = []
    def add(code, severity, basis, ids, message, evidence=(), confirmations=()):
        findings.append(DiagnosticFinding(code=code, severity=severity, basis=basis,
            component_ids=ids, message=message, evidence=list(evidence), confirmations=list(confirmations)))
    generic_confirmation = word("실제 배선·부품 모델·계측 조건이 저장된 회로와 일치하는지 확인하세요.",
        "Confirm that actual wiring, component model and measurement conditions match the stored circuit.")
    for issue in safety.issues:
        basis = "netlist" if issue.scenario == "topology" else "dc_estimate"
        evidence = [DiagnosticEvidence(basis=basis, reference=issue.scenario, detail=issue.message,
            value=issue.measured_value, unit=issue.unit)]
        if issue.limit is not None:
            evidence.append(DiagnosticEvidence(basis="netlist", detail=word("입력한 정격", "Declared limit"),
                value=issue.limit, unit=issue.unit))
        add(issue.code, issue.severity, basis, issue.component_ids,
            word("저장 회로 점검: ", "Stored circuit review: ") + issue.message, evidence, [generic_confirmation])
    graph = defaultdict(set)
    for item in workspace.components:
        if ((item.kind in ("wire", "switch") and item.closed) or
                item.analysis_enabled and item.kind in ("resistor", "inductor")):
            graph[item.a].add(item.b); graph[item.b].add(item.a)
        if item.kind == "wire" and not item.closed:
            add("netlist_open_wire", "warning", "netlist", [item.id],
                word(f"{item.name}: 저장된 전선이 개방 상태입니다. 실제 단선 확인은 별도입니다.",
                     f"{item.name}: the stored wire is open. Actual physical continuity remains unverified."),
                [DiagnosticEvidence(basis="netlist", reference=item.id, detail="closed=false")],
                [word("전원을 분리하고 잔류 전압이 없는지 확인한 뒤 해당 전선을 분리하여 도통을 확인하세요.",
                    "Disconnect power, confirm stored energy is discharged, then isolate this conductor before checking continuity.")])
    sources = [item for item in workspace.components if item.kind == "battery" and item.closed and item.analysis_enabled]
    for item in workspace.components:
        if item.kind not in ("load", "motor", "actuator", "mcu") or not sources: continue
        a_nodes, b_nodes = _reachable(item.a, graph), _reachable(item.b, graph)
        if not any(source.a in a_nodes and source.b in b_nodes for source in sources):
            add("netlist_supply_path_missing", "warning", "netlist", [item.id],
                word(f"{item.name}: 같은 전원의 공급·리턴 쌍이 저장 배선에 없습니다. 의도된 회로인지 확인하세요.",
                    f"{item.name}: the stored wiring has no paired supply/return path from the same source. Confirm the intended circuit."),
                [DiagnosticEvidence(basis="netlist", reference=item.id, detail=f"{item.a} / {item.b}")],
                [generic_confirmation])
    units = dict(voltage="V", current="A", resistance="Ω", continuity="1/0", temperature="°C")
    for reading in request.measurements:
        item = by_id.get(reading.component_id)
        branch = expected.get(reading.component_id)
        value = reading.value
        label = item.name if item else f"{reading.node_a} / {reading.node_b}"
        ids = [item.id] if item else []
        evidence = [DiagnosticEvidence(basis="entered_measurement", reference=reading.id, value=value,
            unit=units[reading.quantity], detail=f"{reading.provenance}; {reading.power_state}; isolated={reading.isolated}; " +
                ("OL/open" if reading.outcome == "open" else str(value)) + (f"; {reading.note}" if reading.note else ""))]
        if reading.quantity in ("resistance", "continuity"):
            if reading.power_state != "unpowered" or not reading.isolated:
                add("continuity_test_conditions_unknown", "pending", "entered_measurement", ids,
                    word(f"{label}: 저항·도통 결과는 전원 분리와 시험 경로 분리가 확인되어야 해석할 수 있습니다.",
                        f"{label}: resistance/continuity requires confirmed power removal and an isolated test path."), evidence,
                    [word("전원을 분리하고 잔류 전압·병렬 경로를 확인하세요. 인가된 회로에서 저항·도통을 재지 마세요.",
                        "Remove power and verify discharge/parallel paths. Do not measure resistance or continuity on an energized circuit.")])
            elif (reading.outcome == "open" or reading.quantity == "continuity" and value == 0):
                conductor = item is not None and item.kind in ("wire", "switch", "inductor", "resistor")
                intended_closed = item is not None and (item.kind not in ("wire", "switch") or item.closed)
                add("reported_open_path", "warning" if conductor and intended_closed else "info", "entered_measurement", ids,
                    word(f"{label}: 분리된 시험 경로에서 개방/무도통이 입력되었습니다. 프로브 접촉·부품 종류·의도된 접점 상태를 확인해야 단선 원인을 확정할 수 있습니다.",
                        f"{label}: an isolated-path open/no-continuity reading was entered. Probe contact, component type and intended contact state still need confirmation before attributing a broken conductor."), evidence,
                    [word("계측기·프로브를 알려진 도체로 확인하고 대상 양 끝 접촉을 재확인하세요.",
                        "Check the instrument/leads on a known conductor and confirm contact at both target ends.")])
            elif reading.quantity == "resistance" and item and item.kind == "wire" and branch and branch.resistance_ohm is not None:
                resistance = branch.resistance_ohm
                if value > max(resistance * 2, resistance + .1):
                    add("reported_wire_high_resistance", "warning", "entered_measurement", ids,
                        word(f"{label}: 입력한 저항 {value:g} Ω가 저장 전선의 저항 추정 {resistance:.4g} Ω보다 큽니다. 접촉·리드 저항 또는 손상 가능성을 확인하세요.",
                            f"{label}: entered resistance {value:g} Ω exceeds stored-wire estimate {resistance:.4g} Ω. Check contact/lead resistance or possible damage."),
                        [*evidence, DiagnosticEvidence(basis="dc_estimate", reference=item.id, detail="Stored wire resistance", value=resistance, unit="Ω")],
                        [word("리드 영점 보정 또는 적합한 4선식 측정으로 접점과 도체를 구분하세요.",
                            "Account for lead/contact resistance or use a suitable four-wire measurement to separate conductor and contact loss.")])
            if (reading.power_state == "unpowered" and reading.isolated and reading.node_a and
                    reading.outcome == "reading" and (reading.quantity == "continuity" and value == 1 or
                        reading.quantity == "resistance" and value < .1)):
                matched_sources = [source.id for source in sources
                    if {source.a, source.b} == {reading.node_a, reading.node_b}]
                if matched_sources:
                    add("reported_supply_short_hypothesis", "warning", "entered_measurement", matched_sources,
                        word(f"{label}: 전원 공급·리턴 사이에 낮은 저항/도통이 입력되었습니다. 쇼트 또는 의도된 저저항 부하·남은 병렬 경로의 가설이며 원인은 미정입니다.",
                            f"{label}: low resistance/continuity was entered across supply and return. A short, intended low-resistance load or remaining parallel path are hypotheses; cause is unknown."), evidence,
                        [word("전원·저장 에너지가 분리·방전되었는지 확인하고 전원 장치와 각 부하·분기를 분리하여 경로를 좁히세요. 의심되는 쇼트에 전원을 인가하지 마세요.",
                            "Confirm power removal and discharge, disconnect the source and isolate each load/branch to locate the path. Do not apply power to a suspected short.")])
            continue
        if reading.quantity in ("current", "voltage") and reading.power_state != "powered":
            add("operating_measurement_conditions_unknown", "pending", "entered_measurement", ids,
                word(f"{label}: 전원 인가 상태가 확인되지 않아 동작 DC 추정과 비교하지 않습니다.",
                    f"{label}: operating power state is unconfirmed; this reading is not compared with the DC operating estimate."), evidence,
                [generic_confirmation]); continue
        limit = None
        if item:
            if reading.quantity == "current": limit = item.max_current_a
            elif reading.quantity == "temperature" and item.safety: limit = item.safety.max_temperature_c
            elif reading.quantity == "voltage":
                limit = item.safety.max_voltage_v if item.safety else None
                if limit is None and item.kind == "capacitor" and item.rated_voltage_v: limit = item.rated_voltage_v
        if limit is not None and (value if reading.quantity == "temperature" else abs(value)) > limit:
            add("reported_" + reading.quantity + "_limit_exceeded", "error", "entered_measurement", ids,
                word(f"{label}: 입력한 {value:g} {units[reading.quantity]}가 선언 정격 {limit:g} {units[reading.quantity]}를 초과합니다. 실제 정격·계측 위치·조건을 확인하세요.",
                    f"{label}: entered {value:g} {units[reading.quantity]} exceeds declared limit {limit:g} {units[reading.quantity]}. Verify the actual rating, measurement location and conditions."),
                [*evidence, DiagnosticEvidence(basis="netlist", reference=item.id, detail="Declared limit", value=limit, unit=units[reading.quantity])],
                [generic_confirmation])
        elif item and reading.quantity in ("current", "temperature") and limit is None:
            add("reported_" + reading.quantity + "_rating_unknown", "pending", "entered_measurement", ids,
                word(f"{label}: 정격이 미입력되어 계측값만으로 과전류·과열을 확정할 수 없습니다.",
                    f"{label}: the rating is unknown; this reading alone cannot establish overload/overheating."), evidence,
                [word("실제 제품과 배치·냉각 조건의 정격을 입력하세요. 사진의 색·굵기로 정격을 추정하지 않습니다.",
                    "Enter the actual product/installation/cooling rating. Photo color or apparent diameter does not establish a rating.")])
        predicted = None
        if reading.quantity == "current" and branch and branch.analysis_enabled:
            predicted = branch.current_a
        elif reading.quantity == "voltage":
            if item and branch and branch.analysis_enabled: predicted = branch.voltage_drop_v
            elif result and reading.node_a in result.node_voltages_v and reading.node_b in result.node_voltages_v:
                predicted = result.node_voltages_v[reading.node_a] - result.node_voltages_v[reading.node_b]
        if predicted is not None and abs(value - predicted) > max(abs(predicted) * .2, .01 if reading.quantity == "current" else .1):
            low_current = reading.quantity == "current" and abs(predicted) > .01 and abs(value) < abs(predicted) * .1
            add("open_path_hypothesis" if low_current else "reported_" + reading.quantity + "_differs_from_dc", "warning", "entered_measurement", ids,
                word(f"{label}: 입력값 {value:g} {units[reading.quantity]}와 DC 추정 {predicted:.4g} {units[reading.quantity]}가 다릅니다. " +
                     ("개방·접점 불량·전원 꺼짐·제어 상태의 가설이며 단선 확정이 아닙니다." if low_current else "실제 배선·부하 상태·전원 강하·계측 방향을 확인하세요. 원인은 미정입니다."),
                    f"{label}: entered {value:g} {units[reading.quantity]} differs from DC estimate {predicted:.4g} {units[reading.quantity]}. " +
                     ("Open path, poor contact, inactive supply or control state are hypotheses; a broken wire is not established." if low_current else "Check actual wiring, load state, source sag and measurement direction. The cause remains unknown.")),
                [*evidence, DiagnosticEvidence(basis="dc_estimate", reference=item.id if item else "node_pair", detail="Operating-point estimate", value=predicted, unit=units[reading.quantity])],
                [generic_confirmation])
        elif predicted is None and reading.quantity in ("current", "voltage"):
            add("dc_measurement_comparison_unavailable", "pending", "entered_measurement", ids,
                word(f"{label}: 같은 위치의 유효한 DC 추정이 없어 계측값과 비교할 수 없습니다. 제외된 부품이나 부유 노드의 0 V·0 A를 추정하지 않습니다.",
                    f"{label}: no valid DC estimate is available at this location. Zero V/A is not assumed for excluded components or floating nodes."),
                evidence, [generic_confirmation])
    if request.symptoms.strip():
        add("reported_symptoms", "info", "user_report", [request.selected_component_id] if request.selected_component_id else [],
            word("증상을 기록했습니다. 증상 자체는 고장 원인·허용 전류·실제 온도의 증거가 아닙니다.",
                "Symptoms were recorded. Symptoms alone do not establish cause, current rating or actual temperature."),
            [DiagnosticEvidence(basis="user_report", reference="symptoms", detail=request.symptoms)],
            [word("증상 발생 시점과 전원·부하·접점 상태를 계측값과 함께 기록하세요.",
                "Record when symptoms occur and the source/load/contact state together with measurements.")])
    unknowns = [word("실제 하드웨어는 검사·작동·계측하지 않았습니다. 입력한 측정값의 계측기·극성·위치·오차는 별도 확인이 필요합니다.",
        "Actual hardware was not inspected, operated or measured. Instrument, polarity, location and uncertainty of entered readings require confirmation."),
        word("DC는 저장 회로의 저항 등가 동작점입니다. 스위칭·펌웨어·접점 간헐 고장·퓨즈 용단·열 과도 현상은 해석하지 않습니다.",
        "DC is the stored circuit's resistive operating point. Switching, firmware, intermittent contacts, fuse trips and thermal transients are not simulated.")]
    if request.photos:
        unknowns.append(word("첨부 사진은 로컬 점검에서 분석하지 않았습니다. Codex 사진 진단 버튼으로만 전송하며 사진은 절연 내부 도통·전선 정격·실제 온도를 증명하지 못합니다.",
            "Attached photos were not analyzed by local review. Only the Codex photo diagnosis button transmits them; photos cannot prove hidden continuity, wire rating or actual temperature."))
    if not request.measurements:
        unknowns.append(word("실제 계측값이 없습니다. 저장 회로 오류를 실제 장치의 고장으로 확정하지 않습니다.",
            "No actual readings were entered. Stored circuit faults do not establish a physical device fault."))
    scope = word("입력 근거를 비교하는 읽기 전용 진단입니다. 실제 고장·안전 인증이 아니며 회로·코드·기기를 변경하거나 외부 기기를 작동하지 않습니다.",
        "Read-only comparison of entered evidence. This is not physical fault/safety certification. It does not alter circuit, code or hardware or operate external devices.")
    status = "fault_in_inputs" if any(item.severity == "error" for item in findings) else (
        "needs_confirmation" if request.photos or not request.measurements or any(item.severity in ("warning", "pending") for item in findings) else "reviewed")
    return ElectricalDiagnosticReport(status=status, language=lang, workspace_name=workspace.name,
        workspace_sha256=sha256(workspace.model_dump_json().encode("utf-8")).hexdigest(),
        available_component_ids=list(by_id), request=request,
        findings=findings, unknowns=unknowns, dc_solved=result is not None,
        expected_branches=[item.model_dump(mode="json") for item in result.components] if result else [], scope=scope)


def diagnostic_report_text(report: ElectricalDiagnosticReport | dict) -> str:
    report = ElectricalDiagnosticReport.model_validate(report)
    labels = dict(netlist="저장 회로 / netlist", dc_estimate="DC 추정 / DC estimate",
        entered_measurement="입력 계측 / entered reading", user_report="증상 / user report",
        photo_hypothesis="AI 가설 · 확인 필요 / AI hypothesis · requires confirmation")
    lines = [f"{report.workspace_name} · {report.status}", report.scope]
    if report.request.operating_context:
        lines.append("동작 조건 / Operating context: " + report.request.operating_context)
    for photo in report.request.photos:
        lines.append(f"사진 / Photo: {photo.id} · {photo.name} · SHA-256 {photo.sha256}")
    for reading in report.request.measurements:
        value = "OL/open" if reading.outcome == "open" else str(reading.value)
        lines.append(f"입력 계측 / Entered reading: {reading.id} · {reading.quantity} · " +
            f"{reading.component_id or reading.node_a+' / '+reading.node_b} · {value} · {reading.provenance} · " +
            f"{reading.power_state} · isolated={reading.isolated} · {reading.note}")
    if report.ai_summary: lines.append("Codex · " + report.ai_summary)
    for finding in report.findings:
        lines.append(f"\n[{finding.severity} · {labels[finding.basis]}] {finding.message}")
        for evidence in finding.evidence:
            value = "" if evidence.value is None else f" · {evidence.value:.5g} {evidence.unit}"
            lines.append(f"  [{labels[evidence.basis]} · {evidence.reference}] {evidence.detail}{value}")
        for confirmation in finding.confirmations: lines.append("  → " + confirmation)
    lines.append("\n미확인 / Unknowns\n" + "\n".join("• " + item for item in report.unknowns))
    return "\n".join(lines)
