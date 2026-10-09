"""Portable firmware review bundles retain exact legacy history and user data."""
from hashlib import sha256

import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.firmware_bundle import FirmwareBundle, create_binding, verify_bundle_binding
from cadstudio.models import Design
from cadstudio.native.document import Document, read_project


def workspace():
    return ElectricalWorkspace.model_validate(dict(nodes=['GND','PWR','LED'],components=[
        dict(id='pi',name='Research supervisor',kind='mcu',analysis_enabled=False,
             catalog_id='rpi4b',pinout_catalog_id='rpi4b',part_id='pi_body',part_registration=True,
             a='PWR',b='GND',signal_pins={'GPIO18':'LED'}),
    ]))


def candidate(circuit=None):
    circuit=circuit or workspace()
    source='# Source review only; no GPIO or device execution.\nvalue = 0\n'
    return FirmwareBundle.model_validate(dict(id='fw_review',name='User supervisor',
        target='raspberry_python',binding=create_binding(circuit,'pi').model_dump(mode='json'),
        entrypoint='supervisor.py',files=[dict(path='supervisor.py',content=source,
            sha256=sha256(source.encode('utf-8')).hexdigest(),role='source')],
        notes='Review candidate',missing_parameters=['Actual motor model'],pin_bindings=[]))


def test_absent_legacy_firmware_and_explicit_empty_are_distinct():
    old=workspace().model_dump(mode='json')
    assert 'firmware_bundles' not in old
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old
    old['firmware_bundles']=[]
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old


def test_bundle_save_reload_and_exact_history_undo_redo(tmp_path):
    original=Design.model_validate(dict(name='Research rig',parameters={'wall':'2 mm'},
        parts=[dict(id='pi_body',name='User controller',role='electrical',color='#112233',
            geometry=dict(kind='plate',length=85,width=56,thickness=2,hole_count=0))],
        electrical=workspace().model_dump(mode='json')))
    before=original.model_dump(mode='json')
    bundle=candidate(original.electrical)
    doc=Document();doc.commit(before,'Original')
    raw=original.model_dump(mode='json');raw['electrical']['firmware_bundles']=[bundle.model_dump(mode='json')]
    doc.commit(Design.model_validate(raw),'Save firmware',{'tool':'electrical-firmware'})
    file=tmp_path/'portable.cad.json';doc.write(file)
    restored=read_project(file)
    assert restored.design.electrical.firmware_bundles==[bundle]
    assert restored.design.parameters==original.parameters
    doc.load(restored,file);entries=doc.journal.path()
    assert doc.journal.at(entries[0]['id'])==before
    doc.commit(doc.journal.at(entries[0]['id']),'Undo',cursor=entries[0]['id'])
    assert 'firmware_bundles' not in doc.project().design.electrical.model_dump(mode='json')
    doc.commit(doc.journal.at(entries[-1]['id']),'Redo',cursor=entries[-1]['id'])
    assert doc.project().design.electrical.firmware_bundles==[bundle]
    assert original.model_dump(mode='json')==before


def test_duplicate_bundle_ids_and_deleted_bound_component_rejected():
    raw=workspace().model_dump(mode='json');raw['firmware_bundles']=[candidate().model_dump(mode='json')]*2
    with pytest.raises(ValueError,match='중복'):ElectricalWorkspace.model_validate(raw)
    raw['firmware_bundles']=raw['firmware_bundles'][:1];raw['components']=[]
    with pytest.raises(ValueError,match='펌웨어'):ElectricalWorkspace.model_validate(raw)


def test_saved_bundle_survives_wiring_edit_but_explicit_binding_check_detects_it():
    raw=workspace().model_dump(mode='json');raw['firmware_bundles']=[candidate().model_dump(mode='json')]
    raw['components'][0]['signal_pins']['GPIO18']='PWR'
    changed=ElectricalWorkspace.model_validate(raw)
    assert changed.firmware_bundles[0].files[0].content.startswith('# Source review')
    assert verify_bundle_binding(changed.firmware_bundles[0],changed).status=='stale'
