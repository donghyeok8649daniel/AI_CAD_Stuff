"""Transactional pin-to-pin editing for the component circuit canvas.

Only an explicitly selected endpoint moves to another net. Sharing a saved net
does not authorize rewiring every terminal on it. Board signal aliases retain
their manufacturer-documented identity; physical power pads are not silently
substituted for the separate A/B DC power model.
"""

from __future__ import annotations

from .electrical import ElectricalComponent, ElectricalWorkspace
from .mcu_connections import (ConnectionEndpoint, assign_pin, assign_pin_node,
                              connection_endpoints, disconnect_pin)


def _workspace(raw: ElectricalWorkspace | dict) -> ElectricalWorkspace:
    data = raw.model_dump() if isinstance(raw, ElectricalWorkspace) else raw
    return ElectricalWorkspace.model_validate(data).model_copy(deep=True)


def _endpoint(workspace: ElectricalWorkspace, component_id: str, terminal: str) -> ConnectionEndpoint:
    endpoint = next((item for item in connection_endpoints(workspace)
                     if item.component_id == component_id and item.terminal == terminal), None)
    if endpoint is None:
        raise ValueError("등록된 전장 부품의 A/B 단자 또는 모식도 신호 핀·제품 단자를 선택하세요.")
    return endpoint


def _add_node(workspace: ElectricalWorkspace, node_id: str) -> None:
    if (not isinstance(node_id, str) or not 0 < len(node_id) <= 40
            or not all(character.isascii() and (character.isalnum() or character in "_-")
                       for character in node_id)):
        raise ValueError("노드 ID는 40자 이내의 영문·숫자·_·-로 지정하세요.")
    if node_id not in workspace.nodes:
        if len(workspace.nodes) >= 128:
            raise ValueError("회로 노드는 최대 128개까지 지정할 수 있습니다. 기존 노드를 선택하세요.")
        workspace.nodes.append(node_id)


def _new_node(workspace: ElectricalWorkspace) -> str:
    index = 1
    while f"SCHEMNET_{index:03d}" in workspace.nodes:
        index += 1
    node_id = f"SCHEMNET_{index:03d}"
    _add_node(workspace, node_id)
    return node_id


def _set_endpoint(workspace: ElectricalWorkspace, endpoint: ConnectionEndpoint,
                  node_id: str) -> ElectricalWorkspace:
    if endpoint.terminal.startswith("supply:"):
        from .board_supply import set_board_supply
        component=next(item for item in workspace.components if item.id==endpoint.component_id)
        set_board_supply(component,endpoint.terminal.partition(":")[2],node_id)
        return workspace
    if endpoint.terminal.startswith("pin:"):
        return assign_pin_node(workspace, endpoint.component_id, endpoint.terminal.partition(":")[2], node_id)
    component = next(item for item in workspace.components if item.id == endpoint.component_id)
    if endpoint.terminal in ("a", "b"):
        setattr(component, endpoint.terminal, node_id)
    else:
        key = endpoint.terminal.partition(":")[2]
        # _endpoint accepts only existing manual ports or documented product
        # terminals. Binding provenance never deletes a preserved legacy port.
        component.terminal_pins[key] = node_id
        from .product_diagrams import product_diagram

        diagram = product_diagram(component.catalog_id)
        if diagram and set(component.terminal_pins) <= {terminal.key for terminal in diagram.terminals}:
            component.product_pinout_catalog_id = component.catalog_id
    return workspace


def assign_schematic_node(raw: ElectricalWorkspace | dict, component_id: str,
                          terminal: str, node_id: str) -> ElectricalWorkspace:
    """Assign one existing canvas terminal to an explicit existing/new net."""
    workspace = _workspace(raw)
    endpoint = _endpoint(workspace, component_id, terminal)
    _add_node(workspace, node_id)
    workspace = _set_endpoint(workspace, endpoint, node_id)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def connect_schematic_terminals(raw: ElectricalWorkspace | dict, source_id: str,
                                source_terminal: str, target_id: str,
                                target_terminal: str) -> ElectricalWorkspace:
    """Join the selected source to the target net, leaving old peers intact.

    An unassigned physical signal/product terminal gains a fresh bounded node.
    Self-connections, including two aliases of one GPIO, are rejected rather
    than turning a component's own supply pair into a short circuit.
    """
    workspace = _workspace(raw)
    source = _endpoint(workspace, source_id, source_terminal)
    target = _endpoint(workspace, target_id, target_terminal)
    if source_id == target_id:
        raise ValueError("같은 부품의 단자끼리 직접 연결할 수 없습니다. 다른 부품의 연결 단자를 선택하세요.")
    if source_terminal.startswith("pin:") and not target_terminal.startswith("supply:"):
        # Keep the existing GPIO alias and board-provenance behavior, including
        # a newly connected target pad and product terminal.
        return assign_pin(workspace, source_id, source_terminal.partition(":")[2], target_id, target_terminal)
    node_id = target.node
    if node_id is None:
        node_id = _new_node(workspace)
        workspace = _set_endpoint(workspace, target, node_id)
    workspace = _set_endpoint(workspace, source, node_id)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def disconnect_schematic_terminal(raw: ElectricalWorkspace | dict, component_id: str,
                                  terminal: str) -> ElectricalWorkspace:
    """Isolate the selected terminal only; retain other devices and named nets."""
    workspace = _workspace(raw)
    endpoint = _endpoint(workspace, component_id, terminal)
    if terminal.startswith("pin:"):
        return disconnect_pin(workspace, component_id, terminal.partition(":")[2])
    if terminal.startswith("supply:"):
        from .board_supply import disconnect_board_supply_pin
        return disconnect_board_supply_pin(workspace,component_id,terminal.partition(":")[2])
    component = next(item for item in workspace.components if item.id == component_id)
    if terminal in ("a", "b"):
        # A/B are required net endpoints in the DC model. A fresh isolated net
        # represents an unplugged terminal without forging a ground return.
        setattr(component, terminal, _new_node(workspace))
    else:
        component.terminal_pins.pop(terminal.partition(":")[2], None)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def add_schematic_wire(raw: ElectricalWorkspace | dict, source_id: str, source_terminal: str,
                       target_id: str, target_terminal: str, *, name: str,
                       length_mm: float, cross_section_mm2: float,
                       resistivity_ohm_mm2_per_m: float = .01724,
                       max_current_a: float | None = None, wire_color: str | None = None) -> ElectricalWorkspace:
    """Insert one real resistive branch between explicitly selected terminals.

    If both terminals already share a net, detach only the selected target
    terminal to insert the wire there. Other peers and saved named nets stay
    untouched; wire deletion later leaves that terminal visibly unpowered.
    """
    workspace = _workspace(raw)
    source = _endpoint(workspace, source_id, source_terminal)
    target = _endpoint(workspace, target_id, target_terminal)
    if source_id == target_id:
        raise ValueError("서로 다른 부품의 시작·도착 핀 또는 단자를 선택하세요.")
    source_node = source.node or _new_node(workspace)
    if source.node is None:
        workspace = _set_endpoint(workspace, source, source_node)
    target_node = target.node
    if target_node is None or target_node == source_node:
        target_node = _new_node(workspace)
        workspace = _set_endpoint(workspace, target, target_node)
    index = 1
    occupied = {component.id for component in workspace.components}
    while f"WIRE_{index:03d}" in occupied:
        index += 1
    wire = ElectricalComponent(id=f"WIRE_{index:03d}", name=name, kind="wire",
        a=source_node, b=target_node, length_mm=length_mm,
        cross_section_mm2=cross_section_mm2,
        resistivity_ohm_mm2_per_m=resistivity_ohm_mm2_per_m,
        max_current_a=max_current_a,wire_color=wire_color,
        wire_endpoints=[dict(component_id=source_id,terminal=source_terminal),
                        dict(component_id=target_id,terminal=target_terminal)])
    workspace.components.append(wire)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def delete_schematic_wire(raw: ElectricalWorkspace | dict, wire_id: str) -> ElectricalWorkspace:
    """Remove only one selected wire; never remove pins, devices or shared nets."""
    workspace = _workspace(raw)
    component = next((item for item in workspace.components if item.id == wire_id), None)
    if component is None or component.kind != "wire":
        raise ValueError("삭제할 전선 부품을 선택하세요. 일반 부품·공유 노드는 삭제하지 않습니다.")
    workspace.components = [item for item in workspace.components if item.id != wire_id]
    workspace.schematic_positions.pop(wire_id, None)
    return ElectricalWorkspace.model_validate(workspace.model_dump())
