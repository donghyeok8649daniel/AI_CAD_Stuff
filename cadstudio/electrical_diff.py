"""Read-only electrical differences for an AI draft's explicit apply review."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from .electrical import ElectricalWorkspace


@dataclass(frozen=True)
class ElectricalChange:
    component_id: str
    name: str
    field: str
    before: Any
    after: Any


def _canonical(value):
    # Compare actual values, including legacy omitted defaults. Stored history
    # serializers deliberately preserve field presence; that is not an edit.
    if isinstance(value, BaseModel):
        return {key: _canonical(getattr(value, key)) for key in type(value).model_fields}
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def electrical_snapshot(design):
    """Copy only the workspace and body names, never meshes/assets/history."""
    raw = design.get('electrical') if isinstance(design, dict) else getattr(design, 'electrical', None)
    parts = design.get('parts', ()) if isinstance(design, dict) else getattr(design, 'parts', ())
    workspace = (ElectricalWorkspace.model_validate(raw) if raw is not None
                 else ElectricalWorkspace(nodes=['GND'], components=[]))
    names = {p['id']: p['name'] for p in parts} if isinstance(design, dict) else {p.id: p.name for p in parts}
    return workspace.model_copy(deep=True), names


def electrical_changes(before, after) -> tuple[ElectricalChange, ...]:
    """Show added/removed items, real fields, CAD links, nodes and positions."""
    old, old_names = electrical_snapshot(before)
    new, new_names = electrical_snapshot(after)
    a, b = {c.id: c for c in old.components}, {c.id: c for c in new.components}
    result = []
    for identifier in dict.fromkeys([*a, *b]):
        source, target = a.get(identifier), b.get(identifier)
        name = (target or source).name
        if source is None or target is None:
            result.append(ElectricalChange(identifier, name, 'component',
                _canonical(source), _canonical(target)))
            continue
        previous, candidate = _canonical(source), _canonical(target)
        for field in previous:
            if previous[field] != candidate[field]:
                result.append(ElectricalChange(identifier, name, field, previous[field], candidate[field]))
        # Body renaming still matters when finding the same linked component.
        if (source.part_id == target.part_id and source.part_id and
                old_names.get(source.part_id) != new_names.get(target.part_id)):
            result.append(ElectricalChange(identifier, name, 'cad_name',
                old_names.get(source.part_id), new_names.get(target.part_id)))
    for field in ('nodes', 'schematic_positions', 'force_chain'):
        previous, candidate = _canonical(getattr(old, field)), _canonical(getattr(new, field))
        if field == 'nodes':
            previous, candidate = sorted(previous), sorted(candidate)
        if previous != candidate:
            result.append(ElectricalChange('', '회로 / Circuit', field, previous, candidate))
    return tuple(result)
