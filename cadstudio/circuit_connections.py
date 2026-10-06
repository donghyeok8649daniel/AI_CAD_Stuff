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


def preserve_physical_wire_connections(before: ElectricalWorkspace | dict,
                                       after: ElectricalWorkspace | dict) -> ElectricalWorkspace:
    """Reject a net reassignment that silently detaches an older physical wire.

    Legacy node-only circuits remain editable. Existing physical endpoint refs
    require the updated pad and the wire branch to agree after a node move.
    This read-only check never repairs or clears other cables implicitly.
    """
    previous = ElectricalWorkspace.model_validate(before.model_dump() if isinstance(before, ElectricalWorkspace) else before)
    candidate = ElectricalWorkspace.model_validate(after.model_dump() if isinstance(after, ElectricalWorkspace) else after)
    wired = [item for item in previous.components if item.kind == 'wire' and item.wire_endpoints]
    if not wired:
        return candidate
    old_nodes = {(item.component_id, item.terminal): item.node for item in connection_endpoints(previous)}
    new_nodes = {(item.component_id, item.terminal): item.node for item in connection_endpoints(candidate)}
    new_wires = {item.id: item for item in candidate.components if item.kind == 'wire'}
    for wire in wired:
        updated = new_wires.get(wire.id)
        if updated is None:
            continue  # An explicit wire deletion does not move a saved cable.
        for index, reference in enumerate(wire.wire_endpoints):
            key = (reference.component_id, reference.terminal)
            if key not in old_nodes or old_nodes[key] == new_nodes.get(key):
                continue
            branch = updated.a if index == 0 else updated.b
            kept_ref = len(updated.wire_endpoints) == 2 and updated.wire_endpoints[index] == reference
            if not kept_ref or new_nodes.get(key) is None or branch != new_nodes[key]:
                raise ValueError('이 핀에 연결된 전선을 먼저 삭제하거나 끝점을 편집하세요. 단자 재지정으로 기존 전선을 분리하지 않습니다. AI 도구: electrical_wire_edit · '
                                 + wire.id + ' / ' + reference.component_id + ' ' + reference.terminal)
    return candidate


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
    return preserve_physical_wire_connections(raw, workspace)


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
        return preserve_physical_wire_connections(raw,
            assign_pin(workspace, source_id, source_terminal.partition(":")[2], target_id, target_terminal))
    node_id = target.node
    if node_id is None:
        node_id = _new_node(workspace)
        workspace = _set_endpoint(workspace, target, node_id)
    workspace = _set_endpoint(workspace, source, node_id)
    return preserve_physical_wire_connections(raw, workspace)


def disconnect_schematic_terminal(raw: ElectricalWorkspace | dict, component_id: str,
                                  terminal: str) -> ElectricalWorkspace:
    """Isolate the selected terminal only; retain other devices and named nets."""
    workspace = _workspace(raw)
    endpoint = _endpoint(workspace, component_id, terminal)
    if terminal.startswith("pin:"):
        return preserve_physical_wire_connections(raw, disconnect_pin(workspace, component_id, terminal.partition(":")[2]))
    if terminal.startswith("supply:"):
        from .board_supply import disconnect_board_supply_pin
        return preserve_physical_wire_connections(raw, disconnect_board_supply_pin(workspace,component_id,terminal.partition(":")[2]))
    component = next(item for item in workspace.components if item.id == component_id)
    if terminal in ("a", "b"):
        # A/B are required net endpoints in the DC model. A fresh isolated net
        # represents an unplugged terminal without forging a ground return.
        setattr(component, terminal, _new_node(workspace))
    else:
        component.terminal_pins.pop(terminal.partition(":")[2], None)
    return preserve_physical_wire_connections(raw, workspace)


def add_schematic_wire(raw: ElectricalWorkspace | dict, source_id: str, source_terminal: str,
                       target_id: str, target_terminal: str, *, name: str,
                       length_mm: float, cross_section_mm2: float,
                       resistivity_ohm_mm2_per_m: float = .01724,
                       max_current_a: float | None = None, wire_color: str | None = None,
                       analysis_enabled: bool = True) -> ElectricalWorkspace:
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
    pair = {(source_id, source_terminal), (target_id, target_terminal)}
    if any(item.kind == 'wire' and item.wire_endpoints and
           {(ref.component_id, ref.terminal) for ref in item.wire_endpoints} == pair
           for item in workspace.components):
        raise ValueError("같은 핀 사이의 전선이 이미 있습니다. 기존 전선을 편집하세요.")
    source_node = source.node or _new_node(workspace)
    if source.node is None:
        workspace = _set_endpoint(workspace, source, source_node)
    target_node = target.node
    if target_node is None or target_node == source_node:
        # Inserting a cable into a previously shared label may detach one pad,
        # but must not leave an older cable's stored branch on that pad's old
        # net. Aliases of one GPIO also identify that same physical endpoint.
        terminals = {target_terminal}
        if target_terminal.startswith('pin:'):
            from .mcu_connections import pin_aliases
            component = next(item for item in workspace.components if item.id == target_id)
            terminals.update('pin:' + alias for alias in pin_aliases(component, target_terminal.partition(':')[2]))
        if target_node is not None and any(item.kind == 'wire' and
                any(ref.component_id == target_id and ref.terminal in terminals
                    for ref in item.wire_endpoints) for item in workspace.components):
            raise ValueError('이미 전선이 연결된 핀의 공유 노드를 분리할 수 없습니다. 기존 전선의 끝을 편집하거나 다른 핀을 선택하세요.')
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
        analysis_enabled=analysis_enabled,
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


def update_schematic_wire(raw: ElectricalWorkspace | dict, wire_id: str, **changes) -> ElectricalWorkspace:
    """Edit one saved wire, preserving its ID and all unrequested metadata.

    Endpoint changes require both ID and terminal for the changed side. Other
    devices and nets remain; old disconnected pads stay visible. Pure property
    edits also work for legacy wires without physical endpoint metadata.
    """
    from copy import deepcopy
    allowed = {'source_id', 'source_terminal', 'target_id', 'target_terminal',
               'name', 'length_mm', 'cross_section_mm2', 'resistivity_ohm_mm2_per_m',
               'max_current_a', 'wire_color', 'closed', 'analysis_enabled'}
    if not changes or set(changes) - allowed:
        raise ValueError('전선의 연결 핀·이름·길이·단면적·색상·연결 상태 중 바꿀 값을 지정하세요.')
    if any(field in changes and not isinstance(changes[field], bool)
           for field in ('closed', 'analysis_enabled')):
        raise ValueError('전선 연결·계산 상태는 true 또는 false로 지정하세요.')
    if any(field in changes and isinstance(changes[field], bool)
           for field in ('length_mm', 'cross_section_mm2', 'resistivity_ohm_mm2_per_m', 'max_current_a')):
        raise ValueError('전선 길이·단면적·저항률·허용 전류는 숫자로 지정하세요.')
    for side in ('source', 'target'):
        if (side + '_id' in changes) != (side + '_terminal' in changes):
            raise ValueError('바꿀 전선 끝에는 부품 ID와 단자 이름을 함께 지정하세요.')
    workspace = _workspace(raw)
    index = next((i for i, item in enumerate(workspace.components) if item.id == wire_id and item.kind == 'wire'), None)
    if index is None:
        raise ValueError('편집할 전선 ID를 선택하세요.')
    original = workspace.components[index].model_dump()
    properties = {key: deepcopy(value) for key, value in changes.items() if key not in
                  ('source_id', 'source_terminal', 'target_id', 'target_terminal')}
    if any(key in changes for key in ('source_id', 'target_id')):
        refs = workspace.components[index].wire_endpoints
        if not refs and not {'source_id', 'target_id'} <= set(changes):
            raise ValueError('기존 전선에 실제 핀 정보가 없습니다. 시작과 도착 핀을 모두 지정하세요.')
        source_id = changes.get('source_id', refs[0].component_id if refs else '')
        source_terminal = changes.get('source_terminal', refs[0].terminal if refs else '')
        target_id = changes.get('target_id', refs[1].component_id if refs else '')
        target_terminal = changes.get('target_terminal', refs[1].terminal if refs else '')
        layout = deepcopy(workspace.schematic_positions)
        without = delete_schematic_wire(workspace, wire_id)
        rewired = add_schematic_wire(without, source_id, source_terminal, target_id, target_terminal,
            name=properties.get('name', original['name']), length_mm=properties.get('length_mm', original['length_mm']),
            cross_section_mm2=properties.get('cross_section_mm2', original['cross_section_mm2']),
            resistivity_ohm_mm2_per_m=properties.get('resistivity_ohm_mm2_per_m', original['resistivity_ohm_mm2_per_m']),
            max_current_a=properties.get('max_current_a', original.get('max_current_a')),
            wire_color=properties.get('wire_color', original.get('wire_color')),
            analysis_enabled=properties.get('analysis_enabled', original.get('analysis_enabled', True)))
        new_branch = rewired.components.pop()
        original.update(a=new_branch.a, b=new_branch.b,
                        wire_endpoints=[ref.model_dump() for ref in new_branch.wire_endpoints])
        rewired.components.insert(index, ElectricalComponent.model_validate({**original, **properties}))
        rewired.schematic_positions = layout
        workspace = rewired
    else:
        workspace.components[index] = ElectricalComponent.model_validate({**original, **properties})
    return ElectricalWorkspace.model_validate(workspace.model_dump())
