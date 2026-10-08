import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.models import Design, Project
from cadstudio.native.document import Document, read_project
from cadstudio.program_attachment import attach_source


def board_workspace():
    return ElectricalWorkspace.model_validate({'nodes':['GND','V'], 'components':[
        dict(id='board',name='Pi4',kind='mcu',a='V',b='GND',catalog_id='rpi4b',analysis_enabled=False),
    ]})


def program():
    return attach_source('idle.py','import RPi.GPIO as GPIO\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(18, GPIO.OUT)\nGPIO.output(18, GPIO.LOW)\n',board_component_id='board')


def test_legacy_absent_programs_exact_snapshot_and_explicit_empty():
    old=board_workspace().model_dump(mode='json')
    assert 'programs' not in old
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old
    old['programs']=[]
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old


def test_portable_code_history_save_reload_undo_redo(tmp_path):
    original=Design(electrical=board_workspace())
    doc=Document();doc.commit(original,'Start')
    raw=original.model_dump(mode='json')
    raw['electrical']['programs']=[program().model_dump(mode='json')]
    doc.commit(Design.model_validate(raw),'Attach program',{'tool':'electrical-program'})
    path=tmp_path/'portable.cad.json';doc.write(path)
    restored=read_project(path)
    assert restored.design.electrical.programs[0]==program()
    doc.load(restored,path)
    entries=doc.journal.path()
    before=doc.journal.at(entries[0]['id'])
    assert before==original.model_dump()
    doc.commit(before,'Undo',cursor=entries[0]['id'])
    assert 'programs' not in doc.project().design.electrical.model_dump()
    after=doc.journal.at(entries[-1]['id'])
    doc.commit(after,'Redo',cursor=entries[-1]['id'])
    assert doc.project().design.electrical.programs[0]==program()


def test_stale_deleted_board_and_duplicate_attachment_rejected():
    raw=board_workspace().model_dump()
    raw['programs']=[program().model_dump()]
    raw['components']=[]
    with pytest.raises(ValueError,match='등록된 MCU'):ElectricalWorkspace.model_validate(raw)
    raw=board_workspace().model_dump()
    raw['programs']=[program().model_dump()]*2
    with pytest.raises(ValueError,match='중복'):ElectricalWorkspace.model_validate(raw)
