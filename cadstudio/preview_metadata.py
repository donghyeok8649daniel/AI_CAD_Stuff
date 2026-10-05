"""Reuse verified preview geometry only when no geometric input changed."""
from copy import deepcopy
import hashlib
import json
from .models import Design


def geometry_inputs(design):
    """Conservative key: exclude only metadata that the geometry kernel ignores."""
    data = design.model_dump() if isinstance(design, Design) else deepcopy(design)
    data.pop('name', None)
    data.pop('electrical', None)
    for part in data.get('parts', []):
        # Material changes affect physical studies, not BREP/mesh/collision data.
        # Those studies read the current Design independently of this cache.
        for key in ('name', 'color', 'role', 'material'):
            part.pop(key, None)
    return data


def geometry_key(design):
    data=json.dumps(geometry_inputs(design),sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def reuse_preview(design, baseline, result):
    """Return new metadata around immutable geometry; None requires full preview.

    Both designs have to be validated before calling. Poses, constraints,
    parameters, sketches, features and imported assets stay in the comparison.
    No new geometry or interference verdict is invented here.
    """
    if baseline is None or result is None:
        return None
    if geometry_inputs(design) != geometry_inputs(baseline):
        return None
    # A preview must attest to the same design that the document has committed.
    # A failed transaction or a dialog's result may share IDs but not geometry.
    if result.get('_geometry_key') != geometry_key(design):
        return None
    parts = {part.id: part for part in design.parts}
    if set(parts) != {mesh['id'] for mesh in result.get('meshes', [])}:
        return None
    return {**result, 'meshes': [dict(mesh, name=parts[mesh['id']].name,
                                    color=parts[mesh['id']].color)
                                for mesh in result['meshes']]}
