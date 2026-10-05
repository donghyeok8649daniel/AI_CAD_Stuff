"""Explicit physical board supply wiring, separate from the abstract DC load.

Only manufacturer-listed power and ground pads are assignable here. No rail,
consumption model, regulator or hidden GPIO connection is inferred from a pad.
"""
from __future__ import annotations

from .board_pins import board_pinout


def supply_pin(catalog_id: str, key: str):
    board=board_pinout(catalog_id)
    pin=next((pin for pin in board.pins if pin.key==key),None) if board else None
    if pin is None or pin.kind not in ('power','ground'):
        raise ValueError('확인된 보드의 실제 전원 또는 GND 핀을 선택하세요. GPIO·리셋·참조 핀은 전원 핀이 아닙니다.')
    return pin


def supply_aliases(catalog_id: str, key: str) -> frozenset[str]:
    """Known same-board rails; never confuse VIN, VBUS and regulator outputs."""
    pin=supply_pin(catalog_id,key);board=board_pinout(catalog_id)
    if pin.kind=='ground':
        return frozenset(member.key for member in board.pins if member.kind=='ground')
    return frozenset(member.key for member in board.pins
                     if member.kind=='power' and member.functions==pin.functions)


def validate_board_supply_map(catalog_id: str, provenance: str, mapping: dict[str,str]) -> None:
    if not provenance or provenance!=catalog_id or board_pinout(provenance) is None:
        raise ValueError('물리 전원 연결에는 확인된 정확한 보드 모델을 유지하세요.')
    for key in mapping:
        aliases=supply_aliases(catalog_id,key)
        if len({mapping[member] for member in aliases if member in mapping})>1:
            raise ValueError('같은 보드의 동일 전원 레일 또는 GND 핀을 서로 다른 노드에 연결할 수 없습니다.')


def set_board_supply(component,key: str,node: str) -> None:
    """Update this pad and already explicit same-rail assignments only."""
    if component.kind!='mcu':
        raise ValueError('물리 보드 전원 핀은 MCU / MPU 보드에만 지정합니다.')
    aliases=supply_aliases(component.catalog_id,key)
    for member in aliases:
        if member==key or member in component.board_supply_pins:
            component.board_supply_pins[member]=node
    component.supply_pinout_catalog_id=component.catalog_id


def assign_board_supply_node(raw,component_id: str,key: str,node: str):
    from .electrical import ElectricalWorkspace
    from .mcu_connections import _add_node
    workspace=ElectricalWorkspace.model_validate(raw.model_dump() if hasattr(raw,'model_dump') else raw).model_copy(deep=True)
    component=next((item for item in workspace.components if item.id==component_id),None)
    if component is None:raise ValueError('등록된 보드 부품을 선택하세요.')
    _add_node(workspace,node);set_board_supply(component,key,node)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def disconnect_board_supply_pin(raw,component_id: str,key: str):
    from .electrical import ElectricalWorkspace
    workspace=ElectricalWorkspace.model_validate(raw.model_dump() if hasattr(raw,'model_dump') else raw).model_copy(deep=True)
    component=next((item for item in workspace.components if item.id==component_id and item.kind=='mcu'),None)
    if component is None:raise ValueError('등록된 보드 부품을 선택하세요.')
    supply_pin(component.catalog_id,key)
    component.board_supply_pins.pop(key,None)
    return ElectricalWorkspace.model_validate(workspace.model_dump())


def board_supply_warnings(raw,result,language='ko') -> tuple[str,...]:
    """Warn from explicit pad rails and calculated net voltage, never MCU logic voltage."""
    if result is None:return ()
    import re
    from .electrical import ElectricalWorkspace,ElectricalResult
    workspace=ElectricalWorkspace.model_validate(raw.model_dump() if hasattr(raw,'model_dump') else raw)
    calculation=ElectricalResult.model_validate(result.model_dump() if hasattr(result,'model_dump') else result)
    warnings=[]
    for component in workspace.components:
        for key,node in component.board_supply_pins.items():
            pin=supply_pin(component.catalog_id,key);value=calculation.node_voltages_v.get(node)
            if value is None:continue
            text=None
            if pin.kind=='ground' and abs(value)>.1:
                text=(f'GND 핀이 {value:.4g} V 노드에 연결되었습니다.' if language=='ko'
                      else f'Ground pin is assigned to a {value:.4g} V net.')
            elif pin.kind=='power':
                match=re.search(r'(?<![\d.])(3\.3|5)\s*V\b',' '.join(pin.functions),re.I)
                expected=float(match.group(1)) if match else None
                if expected is not None and not .9*expected<=value<=1.1*expected:
                    text=(f'공식 {expected:g} V 레일 핀에 계산값 {value:.4g} V가 연결되었습니다.' if language=='ko'
                          else f'Documented {expected:g} V rail is assigned to a calculated {value:.4g} V net.')
            if text:warnings.append(f'{component.name} · {pin.label}: {text}')
    return tuple(warnings)
