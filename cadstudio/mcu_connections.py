"""Explicit, side-effect-free MCU pin-to-net editing.

Physical pin maps are references for passive connectivity. A signal pin adds no
current source, output resistance, firmware, or proof of electrical safety.
MCU supply ``a``/``b`` remains a separate, explicitly entered DC operating point.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache

from .electrical import ElectricalComponent, ElectricalWorkspace


@dataclass(frozen=True, slots=True)
class ConnectionEndpoint:
    component_id: str
    terminal: str
    label: str
    node: str | None
    kind: str
    pin_kind: str = ""


@dataclass(frozen=True, slots=True)
class PinConnection:
    key: str
    label: str
    functions: tuple[str, ...]
    kind: str
    node: str | None
    targets: tuple[ConnectionEndpoint, ...]
    legacy: bool = False


def _pinout(catalog_id: str):
    from .board_pins import board_pinout

    return board_pinout(catalog_id)


def _product_diagram(catalog_id: str):
    from .product_diagrams import product_diagram

    return product_diagram(catalog_id)


def _safe_identifier(value: str) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 40
            and all(character.isascii() and (character.isalnum() or character in "_-") for character in value))


def _workspace(raw: ElectricalWorkspace | dict) -> ElectricalWorkspace:
    # Revalidation also detects stale model_copy() edits; the caller's models
    # and dictionaries are never the mutable result of these editing helpers.
    data = raw.model_dump() if isinstance(raw, ElectricalWorkspace) else raw
    return ElectricalWorkspace.model_validate(data).model_copy(deep=True)


def _component(workspace: ElectricalWorkspace, identifier: str) -> ElectricalComponent:
    for component in workspace.components:
        if component.id == identifier:
            return component
    raise ValueError(f"등록된 전장 부품을 찾을 수 없습니다: {identifier}")


def _mcu(workspace: ElectricalWorkspace, identifier: str) -> ElectricalComponent:
    component = _component(workspace, identifier)
    if component.kind != "mcu":
        raise ValueError("핀 연결은 MCU / 보드 항목을 선택한 뒤 지정하세요.")
    return component


@lru_cache(maxsize=32)
def _pin_groups(pinout) -> dict[str, frozenset[str]]:
    """Collapse manufacturer-documented duplicate connector GPIO aliases."""
    graph: dict[str, set[str]] = {pin.key: set() for pin in pinout.pins}
    for pin in pinout.pins:
        for function in pin.functions:
            if function.startswith("SAME_NET:"):
                other = function.partition(":")[2]
                if other not in graph:
                    raise ValueError("보드 핀 자료의 동일 GPIO 별칭을 확인하세요.")
                graph[pin.key].add(other)
                graph[other].add(pin.key)
    groups = {}
    for key in graph:
        if key in groups:
            continue
        seen = {key}
        queue = deque([key])
        while queue:
            for neighbor in graph[queue.popleft()]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        group = frozenset(seen)
        groups.update({member: group for member in seen})
    return groups


def pin_aliases(component: ElectricalComponent, key: str) -> frozenset[str]:
    """Physical connector labels referring to this same GPIO, if documented."""
    pinout = _pinout(component.catalog_id)
    return _pin_groups(pinout).get(key, frozenset((key,))) if pinout else frozenset((key,))


def validate_bound_pin_map(catalog_id: str, pinout_catalog_id: str, pins: dict[str, str]) -> None:
    """Strict checks apply only to mappings explicitly bound to a board model."""
    if catalog_id != pinout_catalog_id:
        raise ValueError("MCU 모델이 변경되었습니다. 기존 물리 핀 연결을 확인하고 모식도를 다시 지정하세요.")
    pinout = _pinout(pinout_catalog_id)
    if pinout is None:
        raise ValueError("이 MCU 모델의 물리 핀 모식도가 등록되어 있지 않습니다.")
    supported = {pin.key for pin in pinout.pins if pin.kind == "signal"}
    if any(key not in supported for key in pins):
        raise ValueError("선택한 보드의 신호 핀 목록에 없는 핀입니다. 전원 핀은 별도 전원 경로로 지정하세요.")
    groups = _pin_groups(pinout)
    for key in pins:
        nodes = {pins[alias] for alias in groups[key] if alias in pins}
        if len(nodes) > 1:
            raise ValueError("동일 GPIO의 물리 핀 별칭을 서로 다른 노드에 연결할 수 없습니다.")


def validate_bound_terminal_map(catalog_id: str, product_pinout_catalog_id: str, pins: dict[str, str]) -> None:
    if catalog_id != product_pinout_catalog_id:
        raise ValueError("전장 제품 모델이 변경되었습니다. 기존 물리 단자 연결을 확인하고 모식도를 다시 지정하세요.")
    diagram = _product_diagram(product_pinout_catalog_id)
    if diagram is None:
        raise ValueError("이 전장 제품 모델의 물리 단자 모식도가 등록되어 있지 않습니다.")
    supported = {terminal.key for terminal in diagram.terminals}
    if any(key not in supported for key in pins):
        raise ValueError("선택한 제품의 물리 단자 목록에 없는 단자입니다.")


def _resolved_node(component: ElectricalComponent, key: str, pinout=None) -> str | None:
    pinout = pinout if pinout is not None else _pinout(component.catalog_id)
    group = _pin_groups(pinout).get(key, frozenset((key,))) if pinout else frozenset((key,))
    nodes = {component.signal_pins[member] for member in group if member in component.signal_pins}
    # An unbound legacy alias conflict is deliberately not rendered as a
    # verified common net. Both original mappings remain available to repair.
    return next(iter(nodes)) if len(nodes) == 1 else component.signal_pins.get(key)


def _signal_key(component: ElectricalComponent, key: str, *, allow_legacy: bool = False) -> None:
    if not _safe_identifier(key):
        raise ValueError("핀 이름은 40자 이내의 영문·숫자·_·-로 지정하세요.")
    pinout = _pinout(component.catalog_id)
    if pinout:
        physical = next((pin for pin in pinout.pins if pin.key == key), None)
        if physical is not None and physical.kind != "signal":
            raise ValueError("물리 전원·GND·리셋 핀은 신호 연결로 지정하지 않습니다. 별도 전원 경로와 공식 자료를 확인하세요.")
        if physical is None and (component.pinout_catalog_id or not allow_legacy):
            raise ValueError("선택한 보드의 모식도에 없는 신호 핀입니다.")


def _set_pin(component: ElectricalComponent, key: str, node: str) -> None:
    pinout = _pinout(component.catalog_id)
    group = _pin_groups(pinout).get(key, frozenset((key,))) if pinout else frozenset((key,))
    # Moving a duplicated connector pad moves aliases of the *same* GPIO,
    # never another GPIO which merely shared its previous net.
    for alias in group:
        if alias == key or alias in component.signal_pins:
            component.signal_pins[alias] = node
    if pinout and not component.pinout_catalog_id:
        supported = {pin.key for pin in pinout.pins if pin.kind == "signal"}
        if set(component.signal_pins) <= supported:
            component.pinout_catalog_id = component.catalog_id


def _add_node(workspace: ElectricalWorkspace, node: str) -> None:
    if not _safe_identifier(node):
        raise ValueError("노드 ID는 40자 이내의 영문·숫자·_·-로 지정하세요.")
    if node not in workspace.nodes:
        if len(workspace.nodes) >= 128:
            raise ValueError("회로 노드는 최대 128개까지 지정할 수 있습니다. 기존 노드를 선택하세요.")
        workspace.nodes.append(node)


def _new_node(workspace: ElectricalWorkspace) -> str:
    index = 1
    while f"MCUNET_{index:03d}" in workspace.nodes:
        index += 1
    node = f"MCUNET_{index:03d}"
    _add_node(workspace, node)
    return node


def connection_endpoints(raw: ElectricalWorkspace | dict, exclude_mcu_id: str = "") -> tuple[ConnectionEndpoint, ...]:
    """Enumerate terminals, named sensor/driver ports, and physical signal pads."""
    workspace = _workspace(raw)
    endpoints = []
    for component in workspace.components:
        if component.id == exclude_mcu_id:
            continue
        for terminal, node in (("a", component.a), ("b", component.b)):
            suffix = ("VCC · DC 전원 모델" if terminal == "a" else "GND · DC 리턴 모델") if component.kind == "mcu" else ("+" if terminal == "a" else "−") if component.kind == "battery" else terminal.upper()
            endpoints.append(ConnectionEndpoint(component.id, terminal, f"{component.name} · {suffix}", node, component.kind, "power"))
        diagram = _product_diagram(component.catalog_id)
        known_ports = {terminal.key: terminal for terminal in diagram.terminals} if diagram else {}
        for key, terminal in known_ports.items():
            endpoints.append(ConnectionEndpoint(component.id, f"port:{key}", f"{component.name} · {terminal.label}", component.terminal_pins.get(key), component.kind, terminal.kind))
        for key, node in component.terminal_pins.items():
            if key not in known_ports:
                endpoints.append(ConnectionEndpoint(component.id, f"port:{key}", f"{component.name} · {key}", node, component.kind, "signal"))
        if component.kind != "mcu":
            continue
        pinout = _pinout(component.catalog_id)
        known = {pin.key for pin in pinout.pins} if pinout else set()
        if pinout:
            for pin in pinout.pins:
                if pin.kind == "signal":
                    endpoints.append(ConnectionEndpoint(component.id, f"pin:{pin.key}", f"{component.name} · {pin.label}", _resolved_node(component, pin.key, pinout), "mcu", "signal"))
                elif pin.kind in ("power","ground"):
                    endpoints.append(ConnectionEndpoint(component.id,f"supply:{pin.key}",f"{component.name} · {pin.label}",
                                                        component.board_supply_pins.get(pin.key),"mcu",pin.kind))
        for key, node in component.signal_pins.items():
            if key not in known:
                endpoints.append(ConnectionEndpoint(component.id, f"pin:{key}", f"{component.name} · {key} · 사용자 핀", node, "mcu", "signal"))
    return tuple(endpoints)


def pin_connections(raw: ElectricalWorkspace | dict, mcu_id: str) -> tuple[PinConnection, ...]:
    """Describe physical pads and preserved legacy labels without mutation."""
    workspace = _workspace(raw)
    component = _mcu(workspace, mcu_id)
    endpoints = connection_endpoints(workspace)
    pinout = _pinout(component.catalog_id)
    pins = []
    known = set()
    groups = _pin_groups(pinout) if pinout else {}

    def row(key, label, functions, kind, legacy=False):
        node = _resolved_node(component, key, pinout) if kind == "signal" else component.signal_pins.get(key) if legacy else None
        aliases = groups.get(key, frozenset((key,)))
        targets = tuple(endpoint for endpoint in endpoints if node is not None and endpoint.node == node
                        and not (endpoint.component_id == mcu_id and endpoint.terminal.startswith("pin:")
                                 and endpoint.terminal.partition(":")[2] in aliases))
        return PinConnection(key, label, tuple(function for function in functions if not function.startswith("SAME_NET:")), kind, node, targets, legacy)

    if pinout:
        for pin in pinout.pins:
            known.add(pin.key)
            pins.append(row(pin.key, pin.label, pin.functions, pin.kind,
                            legacy=pin.kind != "signal" and pin.key in component.signal_pins))
    for key in component.signal_pins:
        if key not in known:
            pins.append(row(key, f"{key} · 기존 사용자 핀", (), "signal", legacy=True))
    return tuple(pins)


def assign_pin_node(raw: ElectricalWorkspace | dict, mcu_id: str, pin_key: str, node_id: str) -> ElectricalWorkspace:
    """Join only this physical GPIO to an existing or explicitly named new net."""
    workspace = _workspace(raw)
    component = _mcu(workspace, mcu_id)
    _signal_key(component, pin_key, allow_legacy=True)
    _add_node(workspace, node_id)
    _set_pin(component, pin_key, node_id)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def assign_pin(raw: ElectricalWorkspace | dict, mcu_id: str, pin_key: str,
               target_component_id: str, target_terminal: str) -> ElectricalWorkspace:
    """Join a GPIO to one explicit target endpoint; never rewrite a shared net."""
    workspace = _workspace(raw)
    component = _mcu(workspace, mcu_id)
    _signal_key(component, pin_key, allow_legacy=True)
    target = _component(workspace, target_component_id)
    if target_terminal in ("a", "b"):
        node = getattr(target, target_terminal)
    elif target_terminal.startswith("port:"):
        key = target_terminal.partition(":")[2]
        diagram = _product_diagram(target.catalog_id)
        known_ports = {terminal.key for terminal in diagram.terminals} if diagram else set()
        if key not in target.terminal_pins and key not in known_ports:
            raise ValueError("연결할 부품의 추가 신호 단자가 등록되어 있지 않습니다.")
        node = target.terminal_pins.get(key) or _new_node(workspace)
        target.terminal_pins[key] = node
        if diagram and set(target.terminal_pins) <= known_ports:
            target.product_pinout_catalog_id = target.catalog_id
    elif target_terminal.startswith("pin:"):
        if target.kind != "mcu":
            raise ValueError("연결 대상 신호 핀은 MCU / 보드 항목에만 지정할 수 있습니다.")
        key = target_terminal.partition(":")[2]
        _signal_key(target, key, allow_legacy=key in target.signal_pins)
        pinout = _pinout(target.catalog_id)
        source_pinout = _pinout(component.catalog_id)
        source_group = _pin_groups(source_pinout).get(pin_key, frozenset((pin_key,))) if source_pinout else frozenset((pin_key,))
        if target_component_id == mcu_id and key in source_group:
            raise ValueError("같은 물리 GPIO를 자기 자신에게 연결할 수 없습니다.")
        node = _resolved_node(target, key, pinout) or _new_node(workspace)
        _set_pin(target, key, node)
    elif target_terminal.startswith("supply:"):
        from .board_supply import set_board_supply,supply_pin
        key=target_terminal.partition(":")[2]
        if target.kind!='mcu':raise ValueError("전원 핀은 확인된 보드의 핀을 선택하세요.")
        supply_pin(target.catalog_id,key)
        node=target.board_supply_pins.get(key) or _new_node(workspace)
        set_board_supply(target,key,node)
    else:
        raise ValueError("연결 대상 단자는 A/B 또는 등록된 신호 핀·추가 단자로 지정하세요.")
    _set_pin(component, pin_key, node)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def disconnect_pin(raw: ElectricalWorkspace | dict, mcu_id: str, pin_key: str) -> ElectricalWorkspace:
    """Disconnect a GPIO and its duplicate connector aliases; keep other users."""
    workspace = _workspace(raw)
    component = _mcu(workspace, mcu_id)
    if not _safe_identifier(pin_key):
        raise ValueError("핀 이름을 확인하세요.")
    pinout = _pinout(component.catalog_id)
    aliases = _pin_groups(pinout).get(pin_key, frozenset((pin_key,))) if pinout else frozenset((pin_key,))
    for alias in aliases:
        component.signal_pins.pop(alias, None)
    # Keep unused named nodes and all other connected devices by design.
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def change_mcu_model(raw: ElectricalWorkspace | dict, mcu_id: str, catalog_id: str,
                     *, allow_drop: bool = False) -> tuple[ElectricalWorkspace, dict[str, str]]:
    """Bind an exact pinout, requiring explicit confirmation of discarded pins.

    Changing boards never silently carries equal-looking GPIO labels to a
    physically different connector. Entered supply/load values are preserved.
    """
    workspace = _workspace(raw)
    component = _mcu(workspace, mcu_id)
    pinout = _pinout(catalog_id)
    if pinout is None:
        raise ValueError("선택한 MCU 모델의 물리 핀 모식도가 등록되어 있지 않습니다.")
    supported = {pin.key for pin in pinout.pins if pin.kind == "signal"}
    dropped = dict(component.signal_pins) if component.catalog_id != catalog_id else {
        key: node for key, node in component.signal_pins.items() if key not in supported}
    if component.catalog_id!=catalog_id:
        dropped.update({'supply:'+key:node for key,node in component.board_supply_pins.items()})
    if dropped and not allow_drop:
        raise ValueError("모델을 바꾸면 기존 핀 연결이 달라집니다. 연결 해제를 명시적으로 확인하세요.")
    for key in dropped:
        component.signal_pins.pop(key, None)
    if component.catalog_id!=catalog_id and (component.board_supply_pins or component.supply_pinout_catalog_id):
        component.board_supply_pins={};component.supply_pinout_catalog_id=''
    component.catalog_id = catalog_id
    component.pinout_catalog_id = catalog_id
    component.source_url = pinout.source_url
    # Conflicting legacy aliases are not implicitly solved by model binding.
    validate_bound_pin_map(catalog_id, catalog_id, component.signal_pins)
    return ElectricalWorkspace.model_validate(workspace.model_dump()), dropped


def topology_warnings(raw: ElectricalWorkspace | dict, language: str = "ko") -> tuple[str, ...]:
    """Passive connection diagnostics, never firmware or GPIO-drive approval."""
    workspace = _workspace(raw)
    graph: dict[str, set[str]] = defaultdict(set)
    for component in workspace.components:
        if component.kind in ("wire", "switch") and component.closed:
            graph[component.a].add(component.b)
            graph[component.b].add(component.a)

    def reachable(start):
        seen = {start}
        queue = deque([start])
        while queue:
            for other in graph[queue.popleft()]:
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return seen

    warnings = []
    english = language == "en"

    def warn(korean: str, translated: str):
        warnings.append(translated if english else korean)

    mcus = [component for component in workspace.components if component.kind == "mcu"]
    for component in mcus:
        pinout = _pinout(component.catalog_id)
        known = {pin.key: pin for pin in pinout.pins} if pinout else {}
        if component.signal_pins and not pinout:
            warn(f"{component.name}: 사용자 핀 이름의 수동 연결입니다. 실제 보드의 물리 핀·정격·신호 방향을 확인하세요.",
                 f"{component.name}: Manual user-defined pin labels. Check the actual board's physical pins, ratings and signal directions.")
        for key, node in component.signal_pins.items():
            pin = known.get(key)
            if pinout and (pin is None or pin.kind != "signal"):
                warn(f"{component.name}: 기존 핀 {key}는 선택한 보드의 신호 핀 목록과 다릅니다. 연결을 보존했으니 직접 확인하세요.",
                     f"{component.name}: Legacy pin {key} is outside this board's signal pin list. Its connection was preserved; review it explicitly.")
            net = reachable(node)
            for target in workspace.components:
                on_a, on_b = target.a in net, target.b in net
                if not (on_a or on_b):
                    continue
                if target.kind == "battery":
                    warn(f"{component.name} · {key}: 배터리 전원 단자와 연결되어 있습니다. GPIO는 전원 출력이 아니며 허용 전압·보호 회로를 확인해야 합니다.",
                         f"{component.name} · {key}: Connected to a battery power terminal. GPIO is not a power output; check voltage limits and protection.")
                elif target.kind == "motor":
                    warn(f"{component.name} · {key}: 모터 전력 단자와 직접 연결되어 있습니다. 별도 드라이버의 신호 단자를 사용하고 전력 배선을 분리하세요.",
                         f"{component.name} · {key}: Connected directly to a motor power terminal. Use a separate driver's signal terminal and separate power wiring.")
                elif target.kind == "load":
                    warn(f"{component.name} · {key}: 부하·센서·드라이버의 전력 단자와 연결되어 있습니다. GPIO로 전원을 공급하지 말고 별도 전원 경로와 추가 신호 단자를 지정하세요.",
                         f"{component.name} · {key}: Connected to a load/sensor/driver power terminal. Do not power it from GPIO; specify separate power wiring and named signal terminals.")
                elif target.kind == "mcu":
                    warn(f"{component.name} · {key}: 보드의 DC 전원·리턴 단자와 연결되어 있습니다. 신호 방향과 풀업·풀다운·허용 전압을 확인하세요.",
                         f"{component.name} · {key}: Connected to a board's DC supply/return terminal. Check signal direction, pull-up/pull-down and voltage limits.")
            for target in workspace.components:
                diagram = _product_diagram(target.catalog_id)
                if not diagram:
                    continue
                power_ports = {terminal.key for terminal in diagram.terminals if terminal.kind in ("power", "ground")}
                if any(target.terminal_pins.get(port) in net for port in power_ports):
                    warn(f"{component.name} · {key}: {target.name}의 물리 전원·GND 단자와 연결되어 있습니다. 신호 단자와 전력 배선을 구분하고 허용 전압·신호 방향을 확인하세요.",
                         f"{component.name} · {key}: Connected to a physical power/ground terminal of {target.name}. Separate signal and power wiring; check voltage limits and signal direction.")
                for terminal in diagram.terminals:
                    if (terminal.kind != "signal" or not terminal.signal_level_note
                            or target.terminal_pins.get(terminal.key) not in net):
                        continue
                    reference = pinout.logic_voltage_v if pinout else None
                    ko_reference = f" MCU 신호 기준은 {reference:g} V입니다." if reference is not None else ""
                    en_reference = f" MCU logic reference is {reference:g} V." if reference is not None else ""
                    warn(f"{component.name} · {key} ↔ {target.name} · {terminal.key}: {terminal.signal_level_note}{ko_reference} 실제 신호 전압·방향별 허용 입력·레벨 변환을 확인해야 하며 핀 연결만으로 호환성을 확인할 수 없습니다.",
                         f"{component.name} · {key} ↔ {target.name} · {terminal.key}: {terminal.signal_level_note_en or terminal.signal_level_note}{en_reference} Verify actual signal voltage, direction-specific input limits and level translation; a pin connection alone does not establish compatibility.")
            if pinout:
                for other in mcus:
                    if other.id == component.id:
                        continue
                    other_pinout = _pinout(other.catalog_id)
                    if (other_pinout and pinout.logic_voltage_v is not None and other_pinout.logic_voltage_v is not None
                            and pinout.logic_voltage_v != other_pinout.logic_voltage_v
                            and any(other_node in net for other_node in other.signal_pins.values())):
                        warn(f"{component.name} ↔ {other.name}: 신호 기준 전압 {pinout.logic_voltage_v:g} V / {other_pinout.logic_voltage_v:g} V가 다릅니다. 방향별 허용 전압과 레벨 변환을 확인하세요.",
                             f"{component.name} ↔ {other.name}: Different logic references ({pinout.logic_voltage_v:g} V / {other_pinout.logic_voltage_v:g} V). Check direction-specific voltage limits and level translation.")
        if pinout:
            for group in set(_pin_groups(pinout).values()):
                assigned = {component.signal_pins[key] for key in group if key in component.signal_pins}
                if len(assigned) > 1:
                    labels = ', '.join(sorted(group))
                    warn(f"{component.name}: 동일 GPIO의 물리 핀 별칭 {labels}가 서로 다른 노드에 연결되어 있습니다. 실제 보드에서 같은 핀이므로 연결을 수정하세요.",
                         f"{component.name}: Physical aliases {labels} of one GPIO were assigned different nets. These are the same GPIO on the actual board; correct the connections.")
    return tuple(dict.fromkeys(warnings))
