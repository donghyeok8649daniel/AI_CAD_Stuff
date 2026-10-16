"""Manual-editor regressions on tiny declared data, no Qt or real projects."""
from copy import deepcopy
import pytest
from cadstudio.pcb import PCBComponent,PCBQuote
from cadstudio.pcb_editor_data import preserve_library_metadata,pin_specs_from_rows


def original():
    return PCBComponent(ref='U1',mpn='exact model',source_url='https://example.com/drawing',
        pins=[dict(number='1'),dict(number='2',x_mm=2)],
        library_metadata=dict(model='exact model',source_url='https://example.com/drawing',revision='r1',
            pin1_number='1',mounted_side='F',orientation_reference='pin1 datum',body_height_mm=2,
            service_clearance_mm=1,geometry_complete_declared=True,footprint_review_state='source_reviewed',
            reviewed_by='fixture reviewer',reviewed_date='2026-10-16',review_note='explicit fixture source record',
            pin_specs=[dict(number='1',role='signal_in'),dict(number='2',role='ground')]))


def edit(component,**changes):
    raw=component.model_dump(mode='json');raw.pop('library_metadata',None);raw.update(changes)
    return PCBComponent.model_validate(raw)


def test_position_only_edit_preserves_exact_product_and_review():
    before=original();raw=deepcopy(before.model_dump(mode='json'))
    after=preserve_library_metadata(before,edit(before,x_mm=15,rotation_deg=90))
    assert after.library_metadata==before.library_metadata and before.model_dump(mode='json')==raw


def test_removed_pin_invalidates_review_without_none_date_or_missing_pin1():
    before=original();after=preserve_library_metadata(before,edit(before,pins=[dict(number='2',x_mm=2)]))
    meta=after.library_metadata
    assert not meta.geometry_complete_declared and meta.footprint_review_state=='user_declared'
    assert meta.reviewed_date=='' and meta.reviewed_by=='' and meta.pin1_number is None
    assert [s.number for s in meta.pin_specs]==['2']
    assert PCBComponent.model_validate_json(after.model_dump_json())==after


@pytest.mark.parametrize('changes',[dict(mpn='different SKU'),dict(source_url='https://example.com/different')])
def test_product_identity_edit_drops_old_library_binding(changes):
    before=original();after=preserve_library_metadata(before,edit(before,**changes))
    assert after.library_metadata is None and before.library_metadata is not None


def test_form_blanks_remain_unknown_and_zero_current_is_explicit():
    rows=pin_specs_from_rows([dict(number='1',role='power_in',operating_current_a='0',current_limit_a=None),dict(number='2')])
    assert rows[0]['operating_current_a']==0 and rows[0]['current_limit_a'] is None
    assert rows[1]['role']=='unknown' and rows[1]['operating_min_v'] is None


@pytest.mark.parametrize('value',['nan','inf','-1'])
def test_invalid_form_current_cannot_become_a_rating(value):
    with pytest.raises(ValueError):pin_specs_from_rows([dict(number='1',operating_current_a=value)])


def priced():
    raw=original().model_dump(mode='json')
    raw['quote']=PCBQuote(status='reference',unit_price='1.25',currency='USD',as_of='2026-01-01',
        supplier='Synthetic supplier',source_url='https://example.org/entered-quote').model_dump(mode='json')
    return PCBComponent.model_validate(raw)


def test_old_product_quote_does_not_silently_price_new_sku():
    before=priced();after=preserve_library_metadata(before,edit(before,mpn='New SKU'))
    assert after.quote.unit_price is None and before.quote.unit_price is not None


def test_explicit_new_quote_in_same_manual_edit_is_preserved():
    before=priced();quote=before.quote.model_dump(mode='json');quote['unit_price']='2.50'
    after=preserve_library_metadata(before,edit(before,mpn='New SKU',quote=quote))
    assert str(after.quote.unit_price)=='2.50'


def test_unknown_mpn_value_change_invalidates_inherited_quote():
    before=PCBComponent(ref='R1',value='100 ohm',pins=[dict(number='1')],quote=priced().quote)
    after=preserve_library_metadata(before,edit(before,value='10 kohm'))
    assert after.quote.unit_price is None
