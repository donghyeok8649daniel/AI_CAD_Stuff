"""Read-only electrical workbench coverage and passive wiring diagnostics.

This report never solves a DC operating point, loads CAD geometry, guesses a
product from a body's name/color, or approves hardware/firmware execution.
Unused GPIOs are counted, not treated as faults. Assigned pads are checked for
an external endpoint through closed wires/switches; internal regulators,
drivers and board rails are never inferred.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .board_pins import board_pinout
from .electrical_catalog import get_catalog_entry
from .models import Design
from .mcu_connections import connection_endpoints
from .product_diagrams import product_diagram


class ReadinessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ElectricalReadinessIssue(ReadinessModel):
    code: str
    severity: Literal["blocked", "pending", "info"]
    message: str
    next_action: str = ""
    component_id: str = ""
    part_id: str = ""
    terminal: str = ""


class ElectricalPartReadiness(ReadinessModel):
    part_id: str
    name: str
    role: str
    component_ids: tuple[str, ...] = ()
    registration_status: Literal["registered", "legacy", "unregistered", "duplicate"]
    issues: tuple[ElectricalReadinessIssue, ...] = ()


class ElectricalComponentReadiness(ReadinessModel):
    component_id: str
    name: str
    kind: str
    part_id: str
    catalog_id: str
    model_status: Literal["exact", "family", "unknown", "custom"]
    registration_status: Literal["registered", "legacy", "circuit_only", "duplicate"]
    diagram_available: bool
    analysis_enabled: bool
    power_status: Literal["documented", "missing", "isolated", "not_applicable", "undocumented"]
    available_terminals: int = 0
    assigned_terminals: int = 0
    isolated_terminals: int = 0
    unassigned_terminals: int = 0
    undocumented_pins: tuple[str, ...] = ()
    # True means only a stored passive path to an explicit source terminal.
    # It does not establish input/output direction, voltage, or energization.
    supply_path_connected: bool | None = None
    return_path_connected: bool | None = None
    issues: tuple[ElectricalReadinessIssue, ...] = ()


class ElectricalReadinessReport(ReadinessModel):
    schema_version: Literal[1] = 1
    status: Literal["empty", "needs_attention", "review_only"]
    counts: dict[str, int] = Field(default_factory=dict)
    parts: tuple[ElectricalPartReadiness, ...] = ()
    components: tuple[ElectricalComponentReadiness, ...] = ()
    issues: tuple[ElectricalReadinessIssue, ...] = ()
    hardware_execution_supported: Literal[False] = False
    firmware_execution_supported: Literal[False] = False
    dc_calculation_performed: Literal[False] = False
    scope_note: str


_DEVICE_KINDS = frozenset(("mcu", "load", "motor", "actuator"))


def build_electrical_readiness(raw: Design | dict, language: str = "ko") -> ElectricalReadinessReport:
    """Summarize explicit roles and stored connections without editing a Design.

    ``electrical_parts`` and ``unregistered_parts`` count explicit electrical
    roles only. ``parts`` also exposes bodies with an actual stored circuit link,
    even if their role is different; ``candidate_parts`` counts that union.
    Legacy links and family discovery labels do not become physical registrations.
    Existing validated Designs are inspected directly, avoiding a full asset copy.
    """
    design = raw if isinstance(raw, Design) else Design.model_validate(raw)
    english = language == "en"
    body_by_id = {part.id: part for part in design.parts}
    workspace = design.electrical
    components = tuple(workspace.components) if workspace else ()
    links = defaultdict(list)
    for component in components:
        if component.part_id:
            links[component.part_id].append(component)

    def issue(code, ko, en, action_ko, action_en, *, severity="pending", component=None,
              part_id="", terminal=""):
        return ElectricalReadinessIssue(code=code, severity=severity, message=en if english else ko,
            next_action=action_en if english else action_ko,
            component_id=component.id if component else "",
            part_id=component.part_id if component else part_id, terminal=terminal)

    part_rows = []
    for part in design.parts:
        linked = links.get(part.id, ())
        if part.role != "electrical" and not linked:
            continue
        status = ("duplicate" if len(linked) > 1 else "registered" if linked and linked[0].part_registration
                  else "legacy" if linked else "unregistered")
        problems = []
        if status in ("unregistered", "legacy"):
            problems.append(issue("cad_registration_missing", "CAD 전장 부품의 물리 제품 등록이 없습니다.",
                "This electrical CAD body has no physical product registration.",
                "정확한 모델 또는 사용자 정의 전장 부품으로 등록하세요.",
                "Register an exact model or a custom electrical component.", part_id=part.id))
        if status == "duplicate":
            problems.append(issue("duplicate_cad_link", "CAD 부품 하나에 여러 회로 항목이 연결되어 있습니다.",
                "Multiple circuit items refer to one CAD body.", "중복 링크를 검토한 후 물리 등록을 하나로 정리하세요.",
                "Review duplicate links before keeping one physical registration.", severity="blocked", part_id=part.id))
        if linked and part.role != "electrical":
            problems.append(issue("cad_role_mismatch", "회로 링크가 있지만 CAD 역할이 전장으로 지정되지 않았습니다.",
                "This body has a circuit link but its CAD role is not electrical.",
                "의도한 부품 역할과 실제 전장 등록을 확인하세요.", "Review the intended body role and registration.", part_id=part.id))
        part_rows.append(ElectricalPartReadiness(part_id=part.id, name=part.name, role=part.role,
            component_ids=tuple(component.id for component in linked), registration_status=status, issues=tuple(problems)))

    # Closed conductors only. An abstract MCU/load is never a through-wire.
    parent = {node: node for node in workspace.nodes} if workspace else {}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for component in components:
        if component.kind in ("wire", "switch") and component.closed:
            parent[find(component.a)] = find(component.b)
    endpoints = connection_endpoints(workspace) if workspace else ()
    endpoint_by_key = {(endpoint.component_id, endpoint.terminal): endpoint for endpoint in endpoints}
    endpoints_by_component = defaultdict(list)
    peers_by_net = defaultdict(set)
    for endpoint in endpoints:
        endpoints_by_component[endpoint.component_id].append(endpoint)
        if endpoint.node is not None and endpoint.kind not in ("wire", "switch"):
            peers_by_net[find(endpoint.node)].add(endpoint.component_id)
    sources = [item for item in components if item.kind == "battery" and item.closed and item.voltage_v > 0]
    source_positive = {find(item.a) for item in sources}
    source_returns = {find(item.b) for item in sources}
    component_rows = []
    for component in components:
        entry = get_catalog_entry(component.catalog_id)
        board = board_pinout(component.catalog_id)
        product = product_diagram(component.catalog_id)
        model_status = ("custom" if not component.catalog_id else "unknown" if entry is None
                        else "family" if entry.reference_only and not board and not product else "exact")
        registration = ("duplicate" if component.part_id and len(links[component.part_id]) > 1 else
                        "registered" if component.part_registration else "legacy" if component.part_id else "circuit_only")
        problems = []

        def add(code, ko, en, action_ko, action_en, **kwargs):
            problems.append(issue(code, ko, en, action_ko, action_en, component=component, **kwargs))

        if component.part_id and component.part_id not in body_by_id:
            add("missing_cad_body", "저장된 회로 링크의 CAD 부품이 없습니다.", "The stored circuit link refers to a missing CAD body.",
                "실제 CAD 부품을 다시 연결하거나 오래된 링크를 제거하세요.", "Relink an actual body or remove the stale link.", severity="blocked")
        if registration == "duplicate":
            add("duplicate_cad_link", "CAD 부품 하나에 여러 회로 항목이 연결되어 있습니다.",
                "Multiple circuit items refer to one CAD body.", "실제 물리 부품과 중복 링크를 확인하세요.",
                "Review the physical body and duplicate links.", severity="blocked")
        if registration == "legacy":
            add("legacy_cad_link", "기존 느슨한 CAD 링크이며 물리 제품 등록은 아닙니다.",
                "This is a legacy CAD link, not a physical product registration.",
                "기존 결선을 확인하며 물리 제품으로 등록하세요.", "Register the physical product while reviewing existing wiring.")
        if model_status in ("family", "unknown"):
            add("exact_model_missing", "정확한 제품 모델이 확인되지 않았습니다.", "An exact product model has not been established.",
                "제품군이 아닌 정확한 주문 코드와 공식 단자 자료를 선택하세요.", "Choose an exact order code and official terminal reference.")
        diagram_available = bool(board or product)
        if component.kind in _DEVICE_KINDS and not diagram_available:
            add("physical_diagram_missing", "확인된 실제 핀·단자 모식도가 없습니다.", "No verified physical pin or terminal diagram is available.",
                "정확한 제품을 선택하거나 사용자 단자와 출처를 명시하세요.", "Select an exact product or document custom terminals and their source.")
        if model_status == "exact" and not component.source_url:
            add("product_source_missing", "제품 출처 링크가 저장되지 않았습니다.", "The product's source link is not stored.",
                "정확한 모델 등록에서 공식 자료 출처를 확인하세요.", "Review the official source when registering the exact model.")
        if not component.analysis_enabled:
            add("dc_model_excluded", "DC 계산에서 제외된 항목입니다. 0 A를 확인된 소비전류로 볼 수 없습니다.",
                "Excluded from the DC model; zero current is not a verified operating current.",
                "지원하는 모델과 실제 동작점이 있을 때만 DC 계산을 설정하세요.",
                "Enable DC review only for a supported model with a documented operating point.")

        required = {"battery": ("voltage_v",), "wire": ("length_mm", "cross_section_mm2"),
            "resistor": ("resistance_ohm",), "capacitor": ("capacitance_f",),
            "inductor": ("inductance_h", "winding_resistance_ohm")}.get(component.kind,
                ("rated_voltage_v", "rated_current_a") if component.kind in _DEVICE_KINDS else ())
        missing_values = [field for field in required if getattr(component, field) <= 0]
        if missing_values:
            add("operating_values_missing", "동작점·치수 입력이 누락되었습니다: " + ", ".join(missing_values),
                "Missing operating values/dimensions: " + ", ".join(missing_values),
                "실제 조건의 값을 입력하세요. 공급기 용량을 소비전류로 사용하지 마세요.",
                "Enter actual operating values; a supply capacity is not a consumption current.")

        known_signal = {pin.key for pin in board.pins if pin.kind == "signal"} if board else set()
        known_supply = {pin.key for pin in board.pins if pin.kind in ("power", "ground")} if board else set()
        known_ports = {port.key for port in product.terminals} if product else set()
        undocumented = tuple(sorted((*["pin:" + key for key in component.signal_pins if key not in known_signal],
            *["supply:" + key for key in component.board_supply_pins if key not in known_supply],
            *["port:" + key for key in component.terminal_pins if key not in known_ports])))
        if undocumented:
            add("undocumented_pin_labels", "공식 모식도에 없는 사용자·기존 단자 이름이 있습니다.",
                "Some custom/legacy terminal labels are not in the verified diagram.",
                "각 이름과 실제 핀 번호의 대응을 확인하세요.", "Review each label's mapping to the actual physical pin.")
        if board and component.signal_pins and component.pinout_catalog_id != component.catalog_id:
            add("signal_provenance_pending", "보드 신호 연결이 정확한 핀 모식도에 명시적으로 연결되지 않았습니다.",
                "The board signal map is not explicitly bound to its exact physical pinout.",
                "기존 신호 연결을 검토한 후 정확한 보드 모식도에 등록하세요.",
                "Review legacy signals before binding the exact board pinout.")
        if product and component.terminal_pins and component.product_pinout_catalog_id != component.catalog_id:
            add("terminal_provenance_pending", "제품 단자 연결의 모식도 출처가 확인되지 않았습니다.",
                "The product terminal mapping is not bound to its exact diagram.",
                "기존 단자 연결을 검토한 후 정확한 제품 모식도에 등록하세요.",
                "Review legacy terminal connections before binding the exact diagram.")

        # Once real or user-defined named pads exist, spare abstract DC A/B
        # placeholders are not physical wiring omissions. Custom two-terminal
        # items without named pads retain their explicitly stored A/B endpoints.
        named_pads = bool(component.signal_pins or component.terminal_pins or component.board_supply_pins)
        physical = [endpoint for endpoint in endpoints_by_component[component.id]
                    if endpoint.terminal not in ("a", "b")] if diagram_available or named_pads else endpoints_by_component[component.id]
        assigned = [endpoint for endpoint in physical if endpoint.node is not None]
        isolated = [endpoint for endpoint in assigned
                    if not (peers_by_net[find(endpoint.node)] - {component.id})]
        # Never require all unused GPIOs or optional output rails to be wired.
        for endpoint in isolated:
            if endpoint.terminal in ("a", "b") and component.kind in ("wire", "switch"):
                continue
            add("isolated_terminal", "할당된 단자에 닫힌 배선을 통한 외부 연결 대상이 없습니다.",
                "The assigned terminal has no external endpoint through closed wiring.",
                "단자·전선·스위치와 상대 부품 연결을 확인하세요.",
                "Review the terminal, wire/switch state and destination component.", terminal=endpoint.terminal)
        power = [endpoint for endpoint in physical if endpoint.pin_kind == "power"] if diagram_available else []
        returns = [endpoint for endpoint in physical if endpoint.pin_kind == "ground"] if diagram_available else []
        power_nodes = [endpoint.node for endpoint in power if endpoint.node is not None]
        return_nodes = [endpoint.node for endpoint in returns if endpoint.node is not None]
        missing_supply = bool(power) and not power_nodes
        missing_return = bool(returns) and not return_nodes
        if missing_supply:
            add("physical_supply_missing", "모식도의 전력 핀·단자 연결이 지정되지 않았습니다. 입력·출력 방향은 따로 확인해야 합니다.",
                "No power-labelled diagram terminal has been assigned; input/output direction still requires review.",
                "제조사 자료에서 입력·출력·참조·바이패스를 구분해 필요한 실제 단자를 연결하세요. DC A/B와는 별개입니다.",
                "Check input/output/reference/bypass functions in manufacturer data and wire the required terminals; DC A/B is separate.")
        if missing_return:
            add("physical_return_missing", "실제 GND·리턴 핀 연결이 지정되지 않았습니다.",
                "No physical ground/return pad has been assigned.",
                "실제 리턴 단자와 전원 리턴 경로를 지정하세요.", "Assign the actual return pad and supply return path.")
        power_isolated = any(endpoint in isolated for endpoint in (*power, *returns) if endpoint.node is not None)
        power_status = ("not_applicable" if component.kind not in _DEVICE_KINDS else "undocumented" if not diagram_available
                        else "missing" if missing_supply or missing_return else "isolated" if power_isolated
                        else "documented" if power or returns else "not_applicable")
        supply_path = any(find(node) in source_positive for node in power_nodes) if power_nodes else None
        return_path = any(find(node) in source_returns for node in return_nodes) if return_nodes else None
        if power_nodes and not supply_path:
            add("supply_source_unresolved", "전력 표시 단자에서 명시된 공급원 +까지 수동 배선 경로가 없습니다. 출력·참조·바이패스는 입력으로 간주하지 않습니다.",
                "No passive path from a power-labelled terminal to an explicit source positive was found; outputs/references/bypasses are not assumed to be inputs.",
                "레귤레이터·드라이버 내부 연결을 가정하지 말고 공급원을 명시하세요.",
                "Declare the source without assuming internal regulator or driver connections.")
        if return_nodes and not return_path:
            add("return_source_unresolved", "물리 리턴에서 명시된 공급원 리턴까지 경로가 확인되지 않았습니다.",
                "No passive path to an explicit source return was found.",
                "공급원 리턴과 연결 경로를 확인하세요.", "Review the source return and its explicit wiring path.")
        if component.kind == "wire" and not component.wire_endpoints:
            add("wire_endpoints_undocumented", "전선의 실제 시작·도착 핀 정보가 없습니다.",
                "This wire has no documented physical endpoint pair.",
                "실제 부품·핀에서 전선을 연결하세요.", "Connect the wire using actual component terminals.")
        if component.kind == "wire" and component.wire_endpoints:
            declared = [endpoint_by_key.get((endpoint.component_id, endpoint.terminal))
                        for endpoint in component.wire_endpoints]
            if any(endpoint is None for endpoint in declared):
                add("wire_endpoint_missing", "전선에 지정된 실제 부품·단자가 존재하지 않습니다.",
                    "A declared physical wire endpoint no longer exists.",
                    "삭제되거나 바뀐 부품·단자를 확인해 전선을 다시 연결하세요.",
                    "Reconnect the wire after reviewing deleted or changed terminals.", severity="blocked")
            elif {endpoint.node for endpoint in declared} != {component.a, component.b}:
                add("wire_endpoint_net_mismatch", "전선의 핀 정보와 저장된 시작·도착 노드가 서로 다릅니다.",
                    "The wire's physical endpoint metadata disagrees with its stored nets.",
                    "실제 핀을 선택해 전선 연결을 수정하세요.",
                    "Correct the wire using the actual component terminals.", severity="blocked")
        component_rows.append(ElectricalComponentReadiness(component_id=component.id, name=component.name,
            kind=component.kind, part_id=component.part_id, catalog_id=component.catalog_id,
            model_status=model_status, registration_status=registration, diagram_available=diagram_available,
            analysis_enabled=component.analysis_enabled, power_status=power_status,
            available_terminals=len(physical), assigned_terminals=len(assigned), isolated_terminals=len(isolated),
            unassigned_terminals=len(physical) - len(assigned), undocumented_pins=undocumented,
            supply_path_connected=supply_path, return_path_connected=return_path, issues=tuple(problems)))

    all_issues = tuple(problem for row in (*part_rows, *component_rows) for problem in row.issues)
    electrical = [row for row in part_rows if row.role == "electrical"]
    counts = dict(electrical_parts=len(electrical), candidate_parts=len(part_rows),
        registered_parts=sum(row.registration_status == "registered" for row in part_rows),
        registered_electrical_parts=sum(row.registration_status == "registered" for row in electrical),
        unregistered_parts=sum(row.registration_status != "registered" for row in electrical),
        linked_parts=sum(bool(row.component_ids) for row in part_rows),
        role_mismatch_parts=sum(row.role != "electrical" for row in part_rows),
        components=len(component_rows), registered_components=sum(row.registration_status == "registered" for row in component_rows),
        legacy_components=sum(row.registration_status == "legacy" for row in component_rows),
        custom_components=sum(row.model_status == "custom" for row in component_rows),
        exact_models=sum(row.model_status == "exact" for row in component_rows),
        missing_diagrams=sum(row.kind in _DEVICE_KINDS and not row.diagram_available for row in component_rows),
        pending_components=sum(any(problem.severity == "pending" for problem in row.issues) for row in component_rows),
        blocked_components=sum(any(problem.severity == "blocked" for problem in row.issues) for row in component_rows),
        wires=sum(row.kind == "wire" for row in component_rows),
        undocumented_wires=sum(problem.code == "wire_endpoints_undocumented" for problem in all_issues),
        invalid_wire_endpoints=sum(problem.code in ("wire_endpoint_missing", "wire_endpoint_net_mismatch") for problem in all_issues))
    return ElectricalReadinessReport(status="empty" if not part_rows and not component_rows else
        "needs_attention" if any(problem.severity in ("pending", "blocked") for problem in all_issues) else "review_only",
        counts=counts, parts=tuple(part_rows), components=tuple(component_rows), issues=all_issues,
        scope_note=("Stored CAD registrations and passive wiring only. DC values must be calculated separately; "
                    "GPIO logic, firmware, motor commutation, hardware operation and safety are not verified." if english else
                    "CAD 제품 등록과 저장된 수동 결선만 확인합니다. DC 값은 별도 계산해야 하며 GPIO 논리·펌웨어·모터 구동·실물 동작·안전은 검증하지 않습니다."))
