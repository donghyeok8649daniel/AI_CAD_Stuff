"""Owned current-preview display; never a motion or interference clearance."""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from .automatic_interference import design_digest
from .models import Design
from .preview_metadata import geometry_inputs,geometry_key


@dataclass(frozen=True)
class InitialMotionSnapshot:
    input_digest:str
    document_revision:object
    preview:dict
    preview_geometry_key:str
    normalized_geometry_key:str


def _same_geometry_values(before,after):
    """Permit only exact numeric representation changes in validated defaults."""
    if isinstance(before,dict) and isinstance(after,dict):
        return before.keys()==after.keys() and all(_same_geometry_values(before[k],after[k]) for k in before)
    if isinstance(before,list) and isinstance(after,list):
        return len(before)==len(after) and all(_same_geometry_values(a,b) for a,b in zip(before,after))
    if type(before) in (int,float) and type(after) in (int,float):return before==after
    return type(before) is type(after) and before==after


def _matches_display(design,preview,*,attested_key=None):
    expected=geometry_key(design) if attested_key is None else attested_key
    if not isinstance(preview,dict) or preview.get('_geometry_key')!=expected:return False
    meshes=preview.get('meshes');parts=design.get('parts',[])
    if not isinstance(meshes,list) or not meshes or len(meshes)!=len(parts):return False
    ids=[mesh.get('id') for mesh in meshes if isinstance(mesh,dict)]
    if len(ids)!=len(meshes) or not all(type(i) is str for i in ids) or len(set(ids))!=len(ids) or set(ids)!={p['id'] for p in parts}:return False
    stats=preview.get('stats')
    if not isinstance(stats,dict) or stats.get('parts')!=len(parts):return False
    for name in ('bounds','min','max'):
        values=stats.get(name)
        if not isinstance(values,list) or len(values)!=3 or not all(type(v) in (int,float) and isfinite(v) for v in values):return False
    if type(stats.get('volume')) not in (int,float) or not isfinite(stats['volume']):return False
    assembly=stats.get('assembly_constraints')
    if not isinstance(assembly,dict) or not all(type(assembly.get(k)) is int for k in ('mates','dof')) or not isinstance(stats.get('collisions'),list):return False
    for mesh in meshes:
        points=mesh.get('vertices');triangles=mesh.get('triangles')
        if not isinstance(points,list) or not isinstance(triangles,list) or len(points)%3 or len(triangles)%3:return False
        if not all(type(x) in (int,float) and isfinite(x) for x in points):return False
        if not all(type(i) is int and 0<=i<len(points)//3 for i in triangles):return False
    return True


def capture_initial_motion_snapshot(raw,preview,document_revision=None):
    """Copy the caller's committed meshes. Does not build or inspect geometry."""
    if not _matches_display(raw,preview):return None
    normalized=Design.model_validate(deepcopy(raw)).model_dump()
    if not _same_geometry_values(geometry_inputs(raw),geometry_inputs(normalized)):return None
    result=deepcopy(preview)
    parts={part['id']:part for part in raw['parts']}
    for mesh in result['meshes']:
        mesh.update(name=parts[mesh['id']]['name'],color=parts[mesh['id']]['color'])
    return InitialMotionSnapshot(design_digest(raw),deepcopy(document_revision),result,geometry_key(raw),geometry_key(normalized))


def bound_initial_motion_preview(snapshot,normalized,input_digest,document_revision):
    if not isinstance(snapshot,InitialMotionSnapshot):return None,'missing'
    if snapshot.input_digest!=input_digest or snapshot.document_revision!=document_revision:return None,'stale'
    if snapshot.normalized_geometry_key!=geometry_key(normalized):return None,'stale'
    if not _matches_display(normalized,snapshot.preview,attested_key=snapshot.preview_geometry_key):return None,'stale'
    return snapshot.preview,'current'
