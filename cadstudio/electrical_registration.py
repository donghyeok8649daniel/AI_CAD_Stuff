"""Persistent, non-geometric electrical features attached to real CAD bodies.

Registering a model does not replace its CAD geometry with a manufacturer's
footprint or invent an operating current. Exact diagrams are passive terminal
references; unverified operating data remains outside the DC calculation.
"""

from __future__ import annotations

from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from .electrical import ElectricalComponent, ElectricalWorkspace, Kind
from .electrical_catalog import component_prefill, get_catalog_entry
from .mcu_connections import (
    ConnectionEndpoint, assign_pin, assign_pin_node, connection_endpoints,
)
from .models import Design


class RegistrationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    catalog_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    kind: Kind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    a: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    b: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    signal_pins: dict[str, str] | None = Field(default=None, max_length=144)
    terminal_pins: dict[str, str] | None = Field(default=None, max_length=144)
    analysis_enabled: bool | None = None
    apply_default_color: bool = False
    allow_drop_connections: bool = False
    voltage_v: float | None = Field(default=None, ge=0, le=1000)
    internal_resistance_ohm: float | None = Field(default=None, ge=0, le=10000)
    resistance_ohm: float | None = Field(default=None, ge=0, le=1e9)
    rated_voltage_v: float | None = Field(default=None, ge=0, le=1000)
    rated_current_a: float | None = Field(default=None, ge=0, le=10000)
    max_current_a: float | None = Field(default=None, gt=0, le=10000)
    startup_current_a: float | None = Field(default=None, gt=0, le=10000)
    length_mm: float | None = Field(default=None, ge=0, le=1e7)
    cross_section_mm2: float | None = Field(default=None, ge=0, le=1e5)
    resistivity_ohm_mm2_per_m: float | None = Field(default=None, gt=0, le=100)
    closed: bool | None = None
    contact_resistance_ohm: float | None = Field(default=None, gt=0, le=1000)


OPERATING_FIELDS = frozenset((
    "voltage_v", "internal_resistance_ohm", "resistance_ohm", "rated_voltage_v", "rated_current_a",
    "max_current_a", "startup_current_a", "length_mm", "cross_section_mm2",
    "resistivity_ohm_mm2_per_m", "closed", "contact_resistance_ohm",
))


def _design(raw: Design | dict) -> Design:
    return Design.model_validate(raw.model_dump() if isinstance(raw, Design) else deepcopy(raw))


def _body(design: Design, part_id: str):
    part = next((part for part in design.parts if part.id == part_id), None)
    if part is None:
        raise ValueError("전장으로 등록할 실제 CAD 부품을 찾을 수 없습니다: " + part_id)
    return part


def _registration(design: Design, part_id: str) -> ElectricalComponent | None:
    _body(design, part_id)
    matches = [component for component in (design.electrical.components if design.electrical else ())
               if component.part_id == part_id]
    if len(matches) > 1:
        raise ValueError("CAD 부품에 여러 전장 항목이 연결되어 있습니다. 기존 중복 연결을 정리한 뒤 등록하세요: " + part_id)
    return matches[0] if matches else None


def registration_for_part(raw: Design | dict, part_id: str) -> ElectricalComponent | None:
    component = _registration(_design(raw), part_id)
    return component.model_copy(deep=True) if component else None


def _new_identifier(workspace: ElectricalWorkspace) -> str:
    occupied = {component.id for component in workspace.components}
    index = 1
    while (f"ereg_{index:03d}" in occupied or f"ereg_{index:03d}_A" in workspace.nodes
           or f"ereg_{index:03d}_B" in workspace.nodes):
        index += 1
    return f"ereg_{index:03d}"


def _with_nodes(workspace: ElectricalWorkspace, component: dict) -> ElectricalWorkspace:
    data = workspace.model_dump()
    required = [component["a"], component["b"], *component.get("signal_pins", {}).values(),
                *component.get("terminal_pins", {}).values(),*component.get("board_supply_pins",{}).values()]
    for node in required:
        if node not in data["nodes"]:
            data["nodes"].append(node)
    for index, existing in enumerate(data["components"]):
        if existing["id"] == component["id"]:
            data["components"][index] = component
            break
    else:
        data["components"].append(component)
    return ElectricalWorkspace.model_validate(data)


def _checked_model(catalog_id: str, kind: str | None):
    from .board_pins import board_pinout
    from .product_diagrams import product_diagram

    entry = get_catalog_entry(catalog_id)
    board = board_pinout(catalog_id)
    product = product_diagram(catalog_id)
    if entry is None or (entry.reference_only and product is None):
        raise ValueError("확인된 특정 제품 모델을 선택하세요. 제품군·미확인 제품은 모델 없이 수동 등록하세요.")
    expected = entry.suggested_kind or ("mcu" if board else "load")
    if kind is not None and kind != expected:
        raise ValueError("선택한 제품 모델과 전장 부품 종류가 일치하지 않습니다.")
    return entry, expected, board, product


def register_part(raw: Design | dict, part_id: str, args: RegistrationSpec | dict) -> Design:
    """Register/update exactly one real body, preserving geometry and custom color.

    New entries default to pending. Existing ratings are retained on ordinary
    edits, but changing model/kind resets old operating values and disables DC
    analysis until the user explicitly confirms fresh data. Other nets survive.
    """
    design = _design(raw)
    body = _body(design, part_id)
    existing = _registration(design, part_id)
    spec = RegistrationSpec.model_validate(args)
    supplied = spec.model_dump(exclude_unset=True)
    catalog_id = spec.catalog_id if spec.catalog_id is not None else existing.catalog_id if existing else ""
    chosen_kind = spec.kind if spec.kind is not None else None
    entry = board = product = None
    if catalog_id:
        entry, kind, board, product = _checked_model(catalog_id, chosen_kind)
    else:
        kind = chosen_kind or (existing.kind if existing else "load")
    workspace = design.electrical.model_copy(deep=True) if design.electrical else ElectricalWorkspace()
    changed_model = existing is not None and (catalog_id != existing.catalog_id or kind != existing.kind)
    old_pins = {**existing.signal_pins, **existing.terminal_pins,
                **{'supply:'+key:node for key,node in existing.board_supply_pins.items()}} if existing else {}
    if changed_model and old_pins and not spec.allow_drop_connections:
        raise ValueError("제품 모델 변경으로 기존 핀·단자 연결이 해제됩니다. 연결 해제를 명시적으로 확인하세요.")
    if existing and not changed_model:
        component = existing.model_dump()
        # Adopting a legacy catalog label must not silently turn arbitrary
        # labels or conflicting aliases into verified physical connections.
        # Preserve valid mappings; discard only the mismatches after consent.
        dropped_signal = set()
        dropped_terminal = set()
        if board and "signal_pins" not in supplied:
            from .mcu_connections import _pin_groups

            supported = {pin.key for pin in board.pins if pin.kind == "signal"}
            dropped_signal = set(component["signal_pins"]) - supported
            for group in set(_pin_groups(board).values()):
                if len({component["signal_pins"][key] for key in group if key in component["signal_pins"]}) > 1:
                    dropped_signal.update(group & set(component["signal_pins"]))
        if product and "terminal_pins" not in supplied:
            dropped_terminal = set(component.get("terminal_pins", {})) - {terminal.key for terminal in product.terminals}
        if (dropped_signal or dropped_terminal) and not spec.allow_drop_connections:
            raise ValueError("기존 사용자 핀·단자와 실제 제품 모식도가 다릅니다. 해당 연결 해제를 명시적으로 확인하세요.")
        for key in dropped_signal:
            component["signal_pins"].pop(key)
        for key in dropped_terminal:
            component["terminal_pins"].pop(key)
    else:
        identifier = existing.id if existing else _new_identifier(workspace)
        component = dict(id=identifier, name=existing.name if existing else body.name, kind=kind,
                         a=existing.a if existing else identifier + "_A",
                         b=existing.b if existing else identifier + "_B", analysis_enabled=False)
        if entry:
            # Reference-only products provide identity/source/typed terminals,
            # never a made-up resistor equivalent or consumption current.
            component.update(component_prefill(entry))
        if existing:
            component["name"] = existing.name
    component.update(part_id=part_id, part_registration=True, kind=kind,
                     catalog_id=catalog_id, source_url=entry.source_url if entry else "")
    for field in (*OPERATING_FIELDS, "name", "a", "b", "signal_pins", "terminal_pins", "analysis_enabled"):
        if field in supplied and (supplied[field] is not None or field in ("max_current_a", "startup_current_a")):
            component[field] = supplied[field]
    if spec.analysis_enabled is None and not existing:
        component["analysis_enabled"] = False
    # Explicit binding makes later direct model edits detectable. Custom
    # boards retain unverified free labels; product voltage rails remain passive.
    component["pinout_catalog_id"] = catalog_id if board else ""
    component["product_pinout_catalog_id"] = catalog_id if product else ""
    checked = ElectricalComponent.model_validate(component)
    design.electrical = _with_nodes(workspace, checked.model_dump())
    body.role = "electrical"
    if spec.apply_default_color:
        from .part_roles import COLORS

        body.color = COLORS["electrical"]
    return Design.model_validate(design.model_dump())


def connected_pins_for_part(raw: Design | dict, part_id: str) -> tuple[ConnectionEndpoint, ...]:
    """Other stored endpoints sharing this registration's nets, for UI review."""
    design = _design(raw)
    component = _registration(design, part_id)
    if component is None or design.electrical is None:
        return ()
    nodes = {component.a, component.b, *component.signal_pins.values(), *component.terminal_pins.values(),
             *component.board_supply_pins.values()}
    return tuple(endpoint for endpoint in connection_endpoints(design.electrical)
                 if endpoint.component_id != component.id and endpoint.node is not None and endpoint.node in nodes)


def unregister_part(raw: Design | dict, part_id: str) -> Design:
    design = _design(raw)
    component = _registration(design, part_id)
    if component is None:
        return design
    workspace = design.electrical.model_dump()
    workspace["components"] = [item for item in workspace["components"] if item["id"] != component.id]
    if "schematic_positions" in workspace:
        workspace["schematic_positions"].pop(component.id, None)
    design.electrical = ElectricalWorkspace.model_validate(workspace)
    # Roles/colors are independent classifications; removing a feature must
    # not erase a user-picked role, color, another endpoint, or an unused net.
    return Design.model_validate(design.model_dump())


def _registered_pair(raw, part_id, target_part_id):
    design = _design(raw)
    component = _registration(design, part_id)
    target = _registration(design, target_part_id)
    if component is None or target is None:
        raise ValueError("연결할 실제 CAD 부품 두 개를 먼저 전장 부품으로 등록하세요.")
    return design, component, target


def connect_registered_pin(raw: Design | dict, part_id: str, pin_key: str,
                           target_part_id: str, target_terminal: str) -> Design:
    from .board_pins import board_pinout

    design, component, target = _registered_pair(raw, part_id, target_part_id)
    board = board_pinout(component.catalog_id)
    if component.kind != "mcu" or board is None:
        raise ValueError("확인된 MCU / 보드 모델을 먼저 등록한 뒤 실제 신호 핀을 선택하세요.")
    if pin_key not in {pin.key for pin in board.pins if pin.kind == "signal"}:
        raise ValueError("선택한 MCU의 실제 신호 핀 목록에 없는 핀입니다.")
    design.electrical = assign_pin(design.electrical, component.id, pin_key, target.id, target_terminal)
    return Design.model_validate(design.model_dump())


def _terminal_key(component: ElectricalComponent, key: str, *, allow_create=False) -> str:
    from .mcu_connections import _safe_identifier
    from .product_diagrams import product_diagram

    key = key.partition(":")[2] if key.startswith("port:") else key
    if not _safe_identifier(key):
        raise ValueError("전장 단자 이름은 40자 이내 영문·숫자·_·-로 지정하세요.")
    if component.kind not in ("load", "motor"):
        raise ValueError("이 전장 항목은 추가 물리 단자 연결을 지원하지 않습니다.")
    diagram = product_diagram(component.catalog_id)
    if diagram and key not in {terminal.key for terminal in diagram.terminals}:
        raise ValueError("선택한 실제 제품의 물리 단자 목록에 없는 단자입니다.")
    if not diagram and key not in component.terminal_pins and not allow_create:
        raise ValueError("수동 제품은 먼저 추가 단자 이름을 등록하세요.")
    return key


def register_terminal_node(raw: Design | dict, part_id: str, terminal_key: str, node_id: str) -> Design:
    from .mcu_connections import _add_node

    design = _design(raw)
    component = _registration(design, part_id)
    if component is None:
        raise ValueError("실제 CAD 부품을 먼저 전장 부품으로 등록하세요.")
    if component.kind == "mcu":
        if terminal_key.startswith('supply:'):
            from .board_supply import assign_board_supply_node
            design.electrical=assign_board_supply_node(design.electrical,component.id,terminal_key.partition(':')[2],node_id)
        else:design.electrical = assign_pin_node(design.electrical, component.id, terminal_key, node_id)
    else:
        key = _terminal_key(component, terminal_key, allow_create=True)
        _add_node(design.electrical, node_id)
        component.terminal_pins[key] = node_id
    return Design.model_validate(design.model_dump())


def connect_registered_terminal(raw: Design | dict, part_id: str, terminal: str,
                                target_part_id: str, target_terminal: str) -> Design:
    """Connect an explicit product terminal; its voltage rail is never inferred."""
    from .mcu_connections import _add_node, _new_node

    design, source, target = _registered_pair(raw, part_id, target_part_id)
    if terminal.startswith('supply:') or target_terminal.startswith('supply:'):
        from .circuit_connections import connect_schematic_terminals
        source_terminal=terminal if terminal in ('a','b') or terminal.startswith('supply:') else 'port:'+_terminal_key(source,terminal)
        design.electrical=connect_schematic_terminals(design.electrical,source.id,source_terminal,target.id,target_terminal)
        return Design.model_validate(design.model_dump())
    source_terminal = terminal if terminal in ("a", "b") else "port:" + _terminal_key(source, terminal)
    if source.id == target.id and source_terminal == target_terminal:
        raise ValueError("전장 단자를 자기 자신에게 연결할 수 없습니다.")
    if target_terminal.startswith("pin:"):
        # Reverse the passive join: this also handles canonical MCU aliases
        # and creates a fresh unique net for an unassigned product terminal.
        design.electrical = assign_pin(design.electrical, target.id, target_terminal.partition(":")[2],
                                       source.id, source_terminal)
    else:
        if target_terminal in ("a", "b"):
            node = getattr(target, target_terminal)
        elif target_terminal.startswith("port:"):
            key = _terminal_key(target, target_terminal)
            node = target.terminal_pins.get(key) or _new_node(design.electrical)
            target.terminal_pins[key] = node
        else:
            raise ValueError("연결 대상은 실제 등록된 전장 부품의 단자 A/B·신호 핀·제품 단자로 선택하세요.")
        _add_node(design.electrical, node)
        if source_terminal in ("a", "b"):
            setattr(source, source_terminal, node)
        else:
            source.terminal_pins[source_terminal.partition(":")[2]] = node
    return Design.model_validate(design.model_dump())
