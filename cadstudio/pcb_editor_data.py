"""Data rules shared by the manual footprint and embedded-product forms."""
from .pcb import PCBComponent, PCBPinSpec, PCBQuote


PIN_SPEC_COLUMNS = ('number','logical_pin_key','function','role','operating_min_v',
    'operating_max_v','operating_current_a','current_limit_a','ground_reference_net','source_url','condition')


def pin_specs_from_rows(rows):
    result=[]
    for row in rows:
        values={key:('' if row.get(key) is None else str(row.get(key,''))).strip() for key in PIN_SPEC_COLUMNS}
        for key in ('operating_min_v','operating_max_v','operating_current_a','current_limit_a'):
            values[key]=float(values[key]) if values[key] else None
        values['ground_reference_net']=values['ground_reference_net'] or None
        values['role']=values['role'] or 'unknown'
        result.append(PCBPinSpec.model_validate(values).model_dump(mode='json'))
    return result


def preserve_library_metadata(original, candidate):
    """Geometry edits invalidate review; changing product identity drops binding."""
    original=PCBComponent.model_validate(original)
    candidate=PCBComponent.model_validate(candidate)
    identity_changed=(candidate.mpn!=original.mpn or not candidate.mpn and any(
        getattr(candidate,key)!=getattr(original,key) for key in ('value','footprint','model')))
    if identity_changed and candidate.quote==original.quote:
        raw=candidate.model_dump(mode='json');raw['quote']=PCBQuote().model_dump(mode='json')
        candidate=PCBComponent.model_validate(raw)
    meta=original.library_metadata
    if meta is None or candidate.mpn!=original.mpn or candidate.source_url!=original.source_url:
        return candidate
    metadata=meta.model_dump(mode='json')
    before=original.model_dump(mode='json');after=candidate.model_dump(mode='json')
    if any(before.get(key)!=after.get(key) for key in ('pins','body_width_mm','body_height_mm','footprint','footprint_basis')):
        metadata.update(geometry_complete_declared=False,footprint_review_state='user_declared',
            reviewed_by='',reviewed_date='',review_note='패드/몸체 편집 후 실제 도면 재확인 필요')
        numbers={pin.number for pin in candidate.pins}
        metadata['pin_specs']=[row for row in metadata.get('pin_specs',[]) if row['number'] in numbers]
        if metadata.get('pin1_number') not in numbers:metadata['pin1_number']=None
    raw=candidate.model_dump(mode='json');raw['library_metadata']=metadata
    return PCBComponent.model_validate(raw)
