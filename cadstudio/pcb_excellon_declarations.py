"""Read-only, source-bound declaration draft. No inferred export profile."""
from .pcb import PCBProject,pcb_digest,copper_layers
from .pcb_drill_review import _holes
from .pcb_excellon_export import unavailable
from .pcb_excellon_split import DIALECT,FLAGS


def split_declaration_draft(project):
    try:p=PCBProject.model_validate(project)
    except (ValueError,TypeError) as exc:return unavailable('INVALID_PCB',str(exc).splitlines()[0])
    holes,zero=_holes(p);layers=copper_layers(p);digest=pcb_digest(p);inventory=[];blockers=[]
    for hole in sorted(holes,key=lambda h:h['id']):
        row=dict(source_id=hole['id'],source_kind=hole['kind'],component_fitted=hole.get('component_fitted'),
            source_net=hole.get('net'),source_xy_mm=[str(v) for v in hole['center_mm']],
            source_model_drill_mm=str(hole['diameter_mm']),source_copper_layers=hole['declared_copper_layers'])
        if hole['kind']=='via':
            row['source_expanded_copper_span']=hole['expanded_copper_span']
            if hole['expanded_copper_span']!=layers:blockers.append(dict(code='UNSUPPORTED_VIA_SPAN',source_id=hole['id']))
        inventory.append(row)
    if not holes:blockers.append(dict(code='NO_DECLARED_CIRCULAR_HOLES'))
    skeleton=dict(schema_version=1,dialect=DIALECT,source_pcb_sha256=digest,units=None,origin=None,coordinate_format=None,
        diameter_semantics=None,copper_layers=layers,profile_basis=None,tools=None,
        assignments=[dict(source_id=row['source_id'],plating=None,tool=None,declared_drill_span=None) for row in inventory])
    return dict(schema_version=1,kind='pcb-split-hole-declaration-draft-v1',status='REQUIRES_CALLER_DECLARATIONS',
        source_pcb_sha256=digest,source_model_units='mm',source_hole_count=len(inventory),source_inventory=inventory,
        zero_drill_pad_ids=sorted(zero),source_blockers=blockers,caller_profile_skeleton=skeleton,
        exportability='UNAVAILABLE',physical_plating='UNAVAILABLE',physical_finished_hole_interpretation='UNAVAILABLE',
        physical_depth='UNAVAILABLE',files_generated=[],source_data_modified=False,automatic_export=False,**FLAGS,
        instructions='Fill each required null with an explicit caller declaration, resolve source blockers, and submit the resulting profile with the unchanged source to explicit split preparation. Model drill values are not a finished-hole or bit-size declaration. No classification, tool, span or process interpretation is inferred.')
